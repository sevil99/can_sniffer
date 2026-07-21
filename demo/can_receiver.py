import ctypes
import threading
import time
from datetime import datetime
import queue
import struct

# Константы из chai.h
CIO_CAN11 = 0x01
CIO_CAN29 = 0x02

# Флаги CAN сообщений
CAN_FLAG_RTR = 0x01
CAN_FLAG_EFF = 0x04

# Коды ошибок
ECIINVAL = -1
ECINODEV = -2
ECIBUSY = -3
ECIMFAULT = -4
ECISTATE = -5
ECINORES = -6

# Структура CAN сообщения
class CANMSG_T(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("data", ctypes.c_uint8 * 8),
        ("len", ctypes.c_uint8),
        ("flags", ctypes.c_uint16),
        ("ts", ctypes.c_uint32)
    ]

class CANBOARD_T(ctypes.Structure):
    _fields_ = [
        ("brdnum", ctypes.c_uint8),
        ("hwver", ctypes.c_uint32),
        ("chip", ctypes.c_int16 * 4),
        ("name", ctypes.c_char * 64),
        ("manufacturer", ctypes.c_char * 64)
    ]

class CANMessage:
    """Класс-обертка для CAN сообщений"""
    
    def __init__(self, canmsg=None):
        if canmsg:
            self.id = canmsg.id
            self.data = bytes(canmsg.data[:canmsg.len])
            self.length = canmsg.len
            self.flags = canmsg.flags
            self.timestamp = canmsg.ts
            self.receive_time = datetime.now()
            # Добавлено: извлечение float из первых 4 байт (маленький endian)
            self.float_value = self._extract_float_value()
        else:
            self.msg_zero()
    
    def msg_zero(self):
        """Обнуляет кадр"""
        self.id = 0
        self.data = b''
        self.length = 0
        self.flags = 0
        self.timestamp = 0
        self.receive_time = datetime.now()
        self.float_value = None
    
    def _extract_float_value(self):
        """Извлечение float значения из первых 4 байт сообщения"""
        if self.length >= 4:
            try:
                # Предполагаем little-endian формат
                float_bytes = self.data[:4]
                return struct.unpack('<f', float_bytes)[0]
            except:
                return None
        return None
    
    def msg_isrtr(self):
        """Проверка RTR флага"""
        return bool(self.flags & CAN_FLAG_RTR)
    
    def msg_iseff(self):
        """Проверка расширенного формата"""
        return bool(self.flags & CAN_FLAG_EFF)
    
    def get_id_string(self):
        """Строковое представление ID"""
        if self.msg_iseff():
            return f"0x{self.id:08X}"  # 29-bit extended
        else:
            return f"0x{self.id:03X}"   # 11-bit standard
    
    def get_data_hex(self):
        """HEX представление данных"""
        return ' '.join(f'{b:02X}' for b in self.data) if self.data else ""
    
    def get_data_hex_string(self):
        """HEX представление данных как строка"""
        return ''.join(f'{b:02X}' for b in self.data) if self.data else ""
    
    def get_frame_type(self):
        """Тип фрейма"""
        return "EXT" if self.msg_iseff() else "STD"
    
    def get_rtr_status(self):
        """Статус RTR"""
        return "RTR" if self.msg_isrtr() else "DATA"
    
    def get_timestamp_ms(self):
        """Временная метка в миллисекундах"""
        return self.timestamp / 1000.0
    
    def __str__(self):
        """Строковое представление"""
        rtr_flag = " RTR" if self.msg_isrtr() else ""
        float_str = f" Float: {self.float_value:.6f}" if self.float_value is not None else ""
        return (f"CAN {self.get_frame_type()} ID: {self.get_id_string()}{rtr_flag} "
                f"Len: {self.length} Data: {self.get_data_hex()}{float_str}")

class CHAIReceiver:
    def __init__(self, dll_path="chai.dll"):
        self.chai = None
        self.is_loaded = False
        self.channels = {}  # Словарь для хранения открытых каналов
        try:
            self.chai = ctypes.CDLL(dll_path)
            self.setup_prototypes()
            self.is_loaded = True
            self.is_connected = False
            self.read_threads = {}  # Словарь потоков чтения для каждого канала
            self.stop_events = {}   # Словарь событий остановки для каждого канала
            self.message_queues = {} # Словарь очередей сообщений для каждого канала
            self.message_counts = {} # Словарь счетчиков сообщений для каждого канала
            print(f"✅ Библиотека CHAI загружена из {dll_path}")
        except Exception as e:
            print(f"❌ Ошибка загрузки библиотеки: {e}")
            self.is_loaded = False
        
    def setup_prototypes(self):
        """Настройка прототипов функций CHAI"""
        if not self.chai:
            return
            
        self.chai.CiInit.argtypes = []
        self.chai.CiInit.restype = ctypes.c_int16
        
        self.chai.CiBoardInfo.argtypes = [ctypes.POINTER(CANBOARD_T)]
        self.chai.CiBoardInfo.restype = ctypes.c_int16
        
        self.chai.CiOpen.argtypes = [ctypes.c_uint8, ctypes.c_uint8]
        self.chai.CiOpen.restype = ctypes.c_int16
        
        self.chai.CiClose.argtypes = [ctypes.c_uint8]
        self.chai.CiClose.restype = ctypes.c_int16
        
        self.chai.CiSetBaud.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8]
        self.chai.CiSetBaud.restype = ctypes.c_int16
        
        self.chai.CiSetFilter.argtypes = [ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32]
        self.chai.CiSetFilter.restype = ctypes.c_int16
        
        self.chai.CiStart.argtypes = [ctypes.c_uint8]
        self.chai.CiStart.restype = ctypes.c_int16
        
        self.chai.CiStop.argtypes = [ctypes.c_uint8]
        self.chai.CiStop.restype = ctypes.c_int16
        
        # CiRead - ОСНОВНАЯ ФУНКЦИЯ ДЛЯ ЧТЕНИЯ
        self.chai.CiRead.argtypes = [
            ctypes.c_uint8,
            ctypes.POINTER(CANMSG_T),
            ctypes.c_int16
        ]
        self.chai.CiRead.restype = ctypes.c_int16

    def initialize_library(self):
        """Инициализация библиотеки"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        print("🔧 Инициализация библиотеки CHAI...")
        result = self.chai.CiInit()
        if result < 0:
            raise Exception(f"Ошибка инициализации CHAI: {result}")
        print("✅ Библиотека CHAI инициализирована")
        return True

    def scan_devices(self):
        """Сканирование устройств CAN"""
        if not self.is_loaded:
            print("❌ Библиотека CHAI не загружена")
            return []
            
        print("🔍 Сканирование устройств CAN...")
        available_channels = []
        
        binfo = CANBOARD_T()
        
        for brdnum in range(8):
            binfo.brdnum = brdnum
            result = self.chai.CiBoardInfo(ctypes.byref(binfo))
            
            if result >= 0:
                board_name = binfo.name.decode('utf-8', errors='ignore').strip()
                manufacturer = binfo.manufacturer.decode('utf-8', errors='ignore').strip()
                print(f"✅ Плата {brdnum}: {board_name} ({manufacturer})")
                
                for i in range(4):
                    if binfo.chip[i] >= 0:
                        channel = binfo.chip[i]
                        available_channels.append(channel)
                        print(f"   📍 Канал {channel} доступен")
            elif result == ECIINVAL:
                break
        
        return available_channels

    def open_channel(self, channel):
        """Открытие канала"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        print(f"🔓 Открытие канала {channel}...")
        result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
        if result < 0:
            raise Exception(f"Ошибка открытия канала {channel}: {result}")
        print(f"✅ Канал {channel} открыт")
        self.channels[channel] = True
        return True

    def configure_channel(self, channel, baud_rate=500000):
        """Конфигурирование канала с правильными настройками для SJA1000"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        if channel not in self.channels:
            raise Exception(f"Канал {channel} не открыт")
            
        print(f"⚙️ Конфигурирование канала {channel}...")
        
        # Установка скорости 500 Kbit/s (как в CANwise)
        print(f"   🚀 Установка скорости {baud_rate} bps (500 Kbit/s)...")
        btr0, btr1 = self._get_btr_settings(baud_rate)
        result = self.chai.CiSetBaud(channel, btr0, btr1)
        if result < 0:
            raise Exception(f"Ошибка установки скорости: {result}")
        print(f"   ✅ Скорость {baud_rate} bps установлена (BTR0=0x{btr0:02X}, BTR1=0x{btr1:02X})")
        
        # Настройка фильтра на ВСЕ сообщения
        print(f"   🎯 Настройка фильтра на прием ВСЕХ сообщений...")
        result = self.chai.CiSetFilter(channel, 0, 0)  # acode=0, amask=0
        if result < 0:
            raise Exception(f"Ошибка настройки фильтра: {result}")
        print(f"   ✅ Фильтр настроен на прием ВСЕХ сообщений")
        
        return True

    def start_channel(self, channel):
        """Запуск канала"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        print(f"🚀 Запуск канала {channel}...")
        result = self.chai.CiStart(channel)
        if result < 0:
            raise Exception(f"Ошибка запуска канала {channel}: {result}")
        print(f"✅ Канал {channel} запущен")
        return True

    def _get_btr_settings(self, baud_rate):
        """Правильные настройки BTR для SJA1000 (как в CANwise)"""
        # Настройки для SJA1000 с кварцем 16MHz (самый распространенный вариант)
        btr_settings = {
            10000: (0x31, 0x1C),    # 10 kbps
            20000: (0x18, 0x1C),    # 20 kbps  
            50000: (0x09, 0x1C),    # 50 kbps
            100000: (0x04, 0x1C),   # 100 kbps
            125000: (0x03, 0x1C),   # 125 kbps
            250000: (0x01, 0x1C),   # 250 kbps
            500000: (0x00, 0x1C),   # 500 kbps - ОСНОВНАЯ СКОРОСТЬ
            800000: (0x00, 0x16),   # 800 kbps
            1000000: (0x00, 0x14)   # 1000 kbps
        }
        
        if baud_rate not in btr_settings:
            # Если точной скорости нет, используем ближайшую
            closest_rate = min(btr_settings.keys(), key=lambda x: abs(x - baud_rate))
            print(f"⚠️  Скорость {baud_rate} не найдена, использую {closest_rate}")
            return btr_settings[closest_rate]
            
        return btr_settings[baud_rate]

    def start_reading_channel(self, channel):
        """Запуск потока чтения сообщений для конкретного канала"""
        if not self.is_loaded:
            return False
            
        if channel in self.read_threads and self.read_threads[channel].is_alive():
            return True
            
        # Инициализация структур для канала
        self.stop_events[channel] = threading.Event()
        self.message_queues[channel] = queue.Queue()
        self.message_counts[channel] = 0
        
        # Запуск потока чтения
        self.stop_events[channel].clear()
        thread = threading.Thread(target=self._reading_loop, args=(channel,))
        thread.daemon = True
        self.read_threads[channel] = thread
        thread.start()
        
        print(f"🔄 Поток чтения CAN сообщений для канала {channel} запущен")
        return True

    def _reading_loop(self, channel):
        """Основной цикл чтения CAN сообщений для конкретного канала"""
        print(f"🎯 Начало чтения CAN сообщений с канала {channel}...")

        consecutive_errors = 0
        max_errors = 10

        while not self.stop_events[channel].is_set() and channel in self.channels:
            try:
                # ВСЕГДА вызываем чтение, даже если результат 0
                messages_read = self._read_available_messages(channel)

                if messages_read > 0:
                    consecutive_errors = 0
                    # Если есть сообщения, меньше спим
                    time.sleep(0.001)
                else:
                    # Нет сообщений - нормальная ситуация для CAN
                    # Увеличиваем паузу, но не слишком много
                    time.sleep(0.01)

            except Exception as e:
                consecutive_errors += 1
                print(f"❌ Ошибка в цикле чтения канала {channel} ({consecutive_errors}/{max_errors}): {e}")
                if consecutive_errors >= max_errors:
                    print(f"❌ Превышено максимальное количество ошибок для канала {channel}, остановка чтения")
                    break
                time.sleep(0.1)

    def _read_available_messages(self, channel):
        """Чтение доступных CAN сообщений с указанного канала"""
        if not self.is_loaded or channel not in self.channels:
            return 0

        # ВАЖНО: Создаем ОДНУ структуру, а не массив
        canmsg = CANMSG_T()

        # Пытаемся читать до 64 сообщений за раз
        messages_read = 0

        for _ in range(64):  # Максимум 64 сообщения за раз
            # Читаем ОДНО сообщение
            result = self.chai.CiRead(channel, ctypes.byref(canmsg), 1)

            if result == 1:  # Успешно прочитано 1 сообщение
                messages_read += 1
                can_message = CANMessage(canmsg)
                self._process_message(channel, can_message)

            elif result == ECINORES:  # -6 - нет данных
                break  # Нет больше сообщений

            elif result < 0:
                # Другие ошибки
                if result not in [ECIINVAL, ECINORES]:
                    print(f"⚠️ Ошибка чтения канала {channel}: код {result}")
                break  # Прерываем цикл при ошибке

            else:
                # Результат 0 или другой - тоже прерываем
                break
            
        return messages_read

    def _process_message(self, channel, can_message):
        """Обработка полученного CAN сообщения"""
        # ДОБАВЬТЕ ЭТУ СТРОКУ:
        can_message.channel = channel  # Добавляем информацию о канале в сообщение

        self.message_counts[channel] += 1
        self.message_queues[channel].put(can_message)

        # Форматируем вывод как в CANwise
        frame_type = "SFF" if not can_message.msg_iseff() else "EFF"
        id_str = can_message.get_id_string().upper()
        data_hex = can_message.get_data_hex()
        timestamp = can_message.timestamp

        # Вывод float значения если оно есть
        float_str = f" [{can_message.float_value:.6f}]" if can_message.float_value is not None else ""

        # Вывод в формате похожем на CANwise
        print(f"CH{channel} RX {self.message_counts[channel]:08d} {frame_type} {id_str} {can_message.length:1d} "
              f"HEX {data_hex:<23} {timestamp:010d}{float_str} {datetime.now().strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]}")

        # ДОБАВЬТЕ ДЛЯ ОТЛАДКИ:
        print(f"📨 Сообщение добавлено в очередь канала {channel}, всего: {self.message_counts[channel]}")
    
    def connect(self, channels=[0], baud_rate=500000):
        """Подключение для чтения ВСЕХ сообщений с указанных каналов"""
        try:
            if not self.is_loaded:
                raise Exception("Библиотека CHAI не загружена")

            print(f"🚀 Подключение к CAN сети...")
            print(f"   Каналы: {channels}")
            print(f"   Скорость: {baud_rate} bit/s (500 Kbit/s)")
            print(f"   Фильтр: ВСЕ сообщения")
            print(f"   Чип: SJA1000")

            self.initialize_library()
            available_devices = self.scan_devices()

            if not available_devices:
                raise Exception("CAN устройства не найдены")

            # Сбрасываем состояние
            self.channels.clear()
            self.message_queues.clear()

            # Подключаемся к каждому указанному каналу
            for channel in channels:
                if channel not in available_devices:
                    print(f"⚠️ Канал {channel} не найден, доступные каналы: {available_devices}")
                    continue
                
                print(f"\n📡 Настройка канала {channel}:")
                self.open_channel(channel)
                self.configure_channel(channel, baud_rate)
                self.start_channel(channel)
                self.start_reading_channel(channel)

            self.is_connected = True

            print(f"\n✅ Успешно подключено к каналам: {[c for c in channels if c in self.channels]}!")
            print("🎯 Ожидаю сообщения CAN...")

            return True

        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        """Отключение от всех CAN каналов"""
        print("\n🔴 Отключение от всех CAN каналов...")
        
        # Останавливаем все потоки чтения
        for channel in list(self.read_threads.keys()):
            if channel in self.stop_events:
                self.stop_events[channel].set()
        
        # Ждем завершения потоков
        for channel, thread in self.read_threads.items():
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        # Закрываем все каналы
        for channel in list(self.channels.keys()):
            try:
                if self.is_loaded:
                    self.chai.CiStop(channel)
                    self.chai.CiClose(channel)
                    print(f"✅ Канал {channel} закрыт")
            except Exception as e:
                print(f"⚠️ Ошибка при отключении канала {channel}: {e}")
        
        self.channels.clear()
        self.read_threads.clear()
        self.stop_events.clear()
        self.message_queues.clear()
        self.is_connected = False
        
        # Выводим статистику
        total_messages = sum(self.message_counts.values())
        print(f"📊 Всего получено сообщений: {total_messages}")
        for channel, count in self.message_counts.items():
            print(f"   Канал {channel}: {count} сообщений")
        
        print("✅ Отключение завершено")

    def get_message(self, channel, timeout=0.1):
        """Получение сообщения из очереди указанного канала"""
        if channel not in self.message_queues:
            return None
        try:
            return self.message_queues[channel].get(timeout=timeout)
        except queue.Empty:
            return None

    def get_all_messages(self, timeout=0.1):
        """Получение сообщений со всех каналов"""
        messages = {}
        for channel in self.message_queues.keys():
            msg = self.get_message(channel, timeout)
            if msg:
                messages[channel] = msg
        return messages

# Демо-режим для тестирования без оборудования
class DemoReceiver:
    def __init__(self):
        self.is_loaded = True
        self.is_connected = False
        self.channels = {}
        self.message_queues = {}
        self.message_counts = {}
        self.demo_threads = {}
        self.stop_events = {}
        print("✅ Демо-режим активирован (без реального CAN оборудования)")
    
    def scan_devices(self):
        print("🔍 Демо: Сканирование устройств CAN...")
        return [0, 1]  # Демо-каналы
    
    def connect(self, channels=[0], baud_rate=500000):
        print(f"🚀 Демо: Подключение к каналам {channels}, скорость {baud_rate}")
        for channel in channels:
            self.channels[channel] = True
            self.message_queues[channel] = queue.Queue()
            self.message_counts[channel] = 0
            self.stop_events[channel] = threading.Event()
            self.start_demo_messages(channel)
        self.is_connected = True
        return True
    
    def start_demo_messages(self, channel):
        """Генерация демо-сообщений для указанного канала"""
        thread = threading.Thread(target=self._demo_loop, args=(channel,))
        thread.daemon = True
        self.demo_threads[channel] = thread
        thread.start()
    
    def _demo_loop(self, channel):
        """Цикл генерации демо-сообщений для канала"""
        import random
        
        # Демо-сообщения с разными ID и float значениями
        demo_messages = [
            # (ID, float_value для первых 4 байт)
            (0x100, 12.34),
            (0x101, 56.78),
            (0x102, 90.12),
            (0x200, -15.5),
            (0x201, 25.75),
        ]
        
        while not self.stop_events[channel].is_set() and channel in self.channels:
            try:
                # Случайное сообщение из демо-набора
                msg_id, float_value = random.choice(demo_messages)
                
                # Преобразуем float в байты (little-endian)
                float_bytes = struct.pack('<f', float_value)
                
                # Создаем демо-сообщение с float в первых 4 байтах
                canmsg = CANMSG_T()
                canmsg.id = msg_id
                canmsg.len = 8
                
                # Записываем float в первые 4 байта
                for i in range(4):
                    canmsg.data[i] = float_bytes[i]
                
                # Остальные байты заполняем случайными значениями
                for i in range(4, 8):
                    canmsg.data[i] = random.randint(0, 255)
                
                canmsg.flags = 0
                canmsg.ts = int(time.time() * 1000000)
                
                message = CANMessage(canmsg)
                self._process_message(channel, message)
                
                # Разный интервал для разных каналов
                interval = 0.5 + channel * 0.1
                time.sleep(interval)
                
            except Exception as e:
                print(f"Демо ошибка канал {channel}: {e}")
                time.sleep(1)
    
    def _process_message(self, channel, can_message):
        """Обработка полученного CAN сообщения"""
        # Добавляем информацию о канале
        can_message.channel = channel
        
        # Увеличиваем счетчик
        if channel not in self.message_counts:
            self.message_counts[channel] = 0
        self.message_counts[channel] += 1
        
        # Добавляем в очередь
        if channel not in self.message_queues:
            self.message_queues[channel] = queue.Queue()
        self.message_queues[channel].put(can_message)
        
        # Форматируем и выводим сообщение
        frame_type = "STD" if not can_message.msg_iseff() else "EXT"
        rtr_flag = " RTR" if can_message.msg_isrtr() else ""
        id_str = can_message.get_id_string()
        data_hex = can_message.get_data_hex()
        timestamp = can_message.timestamp
        count = self.message_counts[channel]
        
        # Float значение если есть
        float_str = ""
        if can_message.float_value is not None:
            float_str = f" | Float: {can_message.float_value:.6f}"
        
        # Выводим в читаемом формате
        print(f"📥 CH{channel} #{count:04d} | {frame_type}{rtr_flag} ID: {id_str} "
              f"| Len: {can_message.length} | Data: {data_hex}"
              f"{float_str} | TS: {timestamp}")
        
        # Специальный отладочный вывод
        print(f"✅ Сообщение #{count} добавлено в очередь канала {channel}")
        print(f"   Очередь канала {channel}: {self.message_queues[channel].qsize()} сообщений")

    def disconnect(self):
        print("🔴 Демо: Отключение")
        for channel in self.stop_events:
            self.stop_events[channel].set()
        
        self.is_connected = False
        self.channels.clear()
        self.demo_threads.clear()
    
    def get_message(self, channel, timeout=0.1):
        if channel not in self.message_queues:
            return None
        try:
            return self.message_queues[channel].get(timeout=timeout)
        except queue.Empty:
            return None

# Автоматический выбор между реальным и демо-режимом
def create_receiver():
    try:
        receiver = CHAIReceiver()
        if receiver.is_loaded:
            return receiver
        else:
            raise Exception("Библиотека не загружена")
    except:
        print("⚠️  Режим CHAI недоступен, активирую демо-режим")
        return DemoReceiver()

# Пример использования с парсингом float из канала 1
def main():
    # Создаем приемник
    receiver = create_receiver()
    
    try:
        # Подключаемся к каналу 1 (и другим каналам если нужно)
        if receiver.connect(channels=[1], baud_rate=500000):
            print("\n📊 Ожидание сообщений с канала 1...")
            print("   Будут извлекаться float значения из первых 4 байт сообщений")
            print("   Нажмите Ctrl+C для остановки\n")
            
            # Основной цикл обработки сообщений
            while True:
                # Получаем сообщения с канала 1
                message = receiver.get_message(1, timeout=0.5)
                
                if message:
                    # Здесь можно обрабатывать сообщения
                    # Float значение уже извлечено и доступно как message.float_value
                    
                    # Пример обработки только сообщений с float значениями
                    if message.float_value is not None:
                        print(f"📈 Канал 1: ID={message.get_id_string()}, Float={message.float_value:.6f}, "
                              f"Время={message.receive_time.strftime('%H:%M:%S.%f')[:-3]}")
                
                # Можно также обрабатывать сообщения с других каналов
                # message_ch2 = receiver.get_message(2, timeout=0.01)
                # if message_ch2 and message_ch2.float_value is not None:
                #     print(f"📈 Канал 2: ID={message_ch2.get_id_string()}, Float={message_ch2.float_value:.6f}")
                
                time.sleep(0.01)
                
    except KeyboardInterrupt:
        print("\n⏹️  Остановка по команде пользователя")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        receiver.disconnect()

if __name__ == "__main__":
    main()