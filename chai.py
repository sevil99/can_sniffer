import ctypes
import threading
import time
from datetime import datetime
import queue

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
        return (f"CAN {self.get_frame_type()} ID: {self.get_id_string()}{rtr_flag} "
                f"Len: {self.length} Data: {self.get_data_hex()}")

class CHAIReceiver:
    def __init__(self, dll_path="chai.dll"):
        try:
            self.chai = ctypes.CDLL(dll_path)
            self.setup_prototypes()
            self.channel = None
            self.is_connected = False
            self.read_thread = None
            self.stop_event = threading.Event()
            self.message_queue = queue.Queue()
            self.message_count = 0
            print(f"✅ Библиотека CHAI загружена из {dll_path}")
        except Exception as e:
            raise Exception(f"Ошибка загрузки библиотеки: {e}")
        
    def setup_prototypes(self):
        """Настройка прототипов функций CHAI"""
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
        print("🔧 Инициализация библиотеки CHAI...")
        result = self.chai.CiInit()
        if result < 0:
            raise Exception(f"Ошибка инициализации CHAI: {result}")
        print("✅ Библиотека CHAI инициализирована")
        return True

    def scan_devices(self):
        """Сканирование устройств CAN"""
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
        print(f"🔓 Открытие канала {channel}...")
        result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
        if result < 0:
            raise Exception(f"Ошибка открытия канала {channel}: {result}")
        print(f"✅ Канал {channel} открыт")
        self.channel = channel
        return True

    def configure_channel(self, baud_rate=500000):
        """Конфигурирование канала с правильными настройками для SJA1000"""
        if self.channel is None:
            raise Exception("Канал не открыт")
            
        print("⚙️ Конфигурирование канала...")
        
        # Установка скорости 500 Kbit/s (как в CANwise)
        print(f"   🚀 Установка скорости {baud_rate} bps (500 Kbit/s)...")
        btr0, btr1 = self._get_btr_settings(baud_rate)
        result = self.chai.CiSetBaud(self.channel, btr0, btr1)
        if result < 0:
            raise Exception(f"Ошибка установки скорости: {result}")
        print(f"   ✅ Скорость {baud_rate} bps установлена (BTR0=0x{btr0:02X}, BTR1=0x{btr1:02X})")
        
        # Настройка фильтра на ВСЕ сообщения
        print("   🎯 Настройка фильтра на прием ВСЕХ сообщений...")
        result = self.chai.CiSetFilter(self.channel, 0, 0)  # acode=0, amask=0
        if result < 0:
            raise Exception(f"Ошибка настройки фильтра: {result}")
        print("   ✅ Фильтр настроен на прием ВСЕХ сообщений")
        
        return True

    def start_channel(self):
        """Запуск канала"""
        print("🚀 Запуск канала...")
        result = self.chai.CiStart(self.channel)
        if result < 0:
            raise Exception(f"Ошибка запуска канала: {result}")
        print("✅ Канал запущен")
        self.is_connected = True
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

    def start_reading(self):
        """Запуск потока чтения сообщений"""
        if self.read_thread and self.read_thread.is_alive():
            return
            
        self.stop_event.clear()
        self.read_thread = threading.Thread(target=self._reading_loop)
        self.read_thread.daemon = True
        self.read_thread.start()
        print("🔄 Поток чтения CAN сообщений запущен")

    def _reading_loop(self):
        """Основной цикл чтения CAN сообщений"""
        print("🎯 Начало чтения CAN сообщений...")
        
        consecutive_errors = 0
        max_errors = 10
        
        while not self.stop_event.is_set() and self.is_connected:
            try:
                # Прямое чтение через CiRead (polling)
                messages_read = self._read_available_messages()
                
                if messages_read > 0:
                    consecutive_errors = 0
                    # Короткая пауза когда есть сообщения
                    time.sleep(0.001)
                else:
                    # Нет сообщений - увеличиваем паузу
                    time.sleep(0.01)
                    
            except Exception as e:
                consecutive_errors += 1
                print(f"❌ Ошибка в цикле чтения ({consecutive_errors}/{max_errors}): {e}")
                if consecutive_errors >= max_errors:
                    print("❌ Превышено максимальное количество ошибок, остановка чтения")
                    break
                time.sleep(0.1)

    def _read_available_messages(self):
        """Чтение доступных CAN сообщений"""
        if not self.is_connected or self.channel is None:
            return 0
            
        # Буфер для чтения сообщений
        msg_buffer = (CANMSG_T * 64)()  # Увеличили буфер
        result = self.chai.CiRead(self.channel, msg_buffer, 64)
        
        if result > 0:
            # Успешно прочитали сообщения
            for i in range(result):
                can_message = CANMessage(msg_buffer[i])
                self._process_message(can_message)
            return result
            
        elif result == ECINORES:  # -6 - нет данных
            return 0  # Это нормально
            
        elif result < 0:
            # Другие ошибки логируем только иногда
            if result != ECIINVAL:  # ECIINVAL тоже может быть при отсутствии данных
                print(f"⚠️ Ошибка чтения: {result}")
            return 0
            
        return 0

    def _process_message(self, can_message):
        """Обработка полученного CAN сообщения"""
        self.message_count += 1
        self.message_queue.put(can_message)
        
        # Форматируем вывод как в CANwise
        frame_type = "SFF" if not can_message.msg_iseff() else "EFF"
        id_str = can_message.get_id_string().upper()
        data_hex = can_message.get_data_hex()
        timestamp = can_message.timestamp
        
        # Вывод в формате похожем на CANwise
        print(f"RX {self.message_count:08d} {frame_type} {id_str} {can_message.length:1d} "
              f"HEX {data_hex:<23} {timestamp:010d} {datetime.now().strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]}")

    def connect(self, channel=0, baud_rate=500000):
        """Подключение для чтения ВСЕХ сообщений"""
        try:
            print(f"🚀 Подключение к CAN сети...")
            print(f"   Канал: {channel}")
            print(f"   Скорость: {baud_rate} bit/s (500 Kbit/s)")
            print(f"   Фильтр: ВСЕ сообщения")
            print(f"   Чип: SJA1000")
            
            self.initialize_library()
            devices = self.scan_devices()
            
            if not devices:
                raise Exception("CAN устройства не найдены")
            
            if channel not in devices:
                print(f"⚠️ Канал {channel} не найден, использую первый доступный: {devices[0]}")
                channel = devices[0]
            
            self.open_channel(channel)
            self.configure_channel(baud_rate)
            self.start_channel()
            self.start_reading()
            
            print(f"\n✅ Успешно подключено!")
            print("🎯 Ожидаю сообщения CAN...")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        """Отключение от CAN канала"""
        print("\n🔴 Отключение от CAN канала...")
        
        self.stop_event.set()
        self.is_connected = False
        
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=2.0)
        
        if self.channel is not None:
            try:
                self.chai.CiStop(self.channel)
                self.chai.CiClose(self.channel)
                print("✅ Канал закрыт")
            except Exception as e:
                print(f"⚠️ Ошибка при отключении: {e}")
        
        self.channel = None
        print(f"📊 Всего получено сообщений: {self.message_count}")
        print("✅ Отключение завершено")

    def get_message(self, timeout=0.1):
        """Получение сообщения из очереди"""
        try:
            return self.message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

# Основная программа
def main():
    receiver = CHAIReceiver()
    
    try:
        # Подключаемся с правильными настройками
        if receiver.connect(channel=0, baud_rate=500000):  # 500 Kbit/s!
            print("\n" + "="*60)
            print("🎯 CAN MONITOR - ЧТЕНИЕ ВСЕХ СООБЩЕНИЙ")
            print("="*60)
            print("Настройки:")
            print("  • Скорость: 500 Kbit/s (как в CANwise)")
            print("  • Фильтр: ВСЕ сообщения (acode=0, amask=0)")
            print("  • Форматы: SFF (11-bit) и EFF (29-bit)")
            print("  • Типы: DATA и RTR фреймы")
            print("="*60)
            print("Формат вывода:")
            print("  RX [номер] [тип] [ID] [длина] HEX [данные] [временная_метка] [время]")
            print("="*60)
            print("Нажмите Ctrl+C для остановки\n")
            
            # Простой цикл ожидания
            last_count = 0
            last_time = time.time()
            
            while True:
                current_time = time.time()
                if current_time - last_time >= 5.0:
                    current_count = receiver.message_count
                    new_messages = current_count - last_count
                    print(f"📊 Статистика: {new_messages} сообщений за 5 сек, всего: {current_count}")
                    last_count = current_count
                    last_time = current_time
                
                time.sleep(0.1)
                    
    except KeyboardInterrupt:
        print("\n\n🛑 Остановка по команде пользователя")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
    finally:
        receiver.disconnect()

if __name__ == "__main__":
    main()