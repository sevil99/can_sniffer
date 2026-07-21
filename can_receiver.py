import ctypes
import threading
import time
from datetime import datetime
import queue
import os

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
        self.chai = None
        self.is_loaded = False
        self._initialized = False
        
        print(f"🔧 Инициализация CHAIReceiver...")
        
        try:
            self.chai = ctypes.WinDLL(dll_path)
            self.setup_prototypes()
            self.is_loaded = True
            
            self.channel = None
            self.is_connected = False
            self.read_thread = None
            self.stop_event = threading.Event()
            self.message_queue = queue.Queue()
            self.message_count = 0
            
            # Для канала 1
            self.channel1_last_success = 0
            self.channel1_error_count = 0
            self.channel1_working_method = None
            
            print(f"✅ Библиотека CHAI загружена")
            
        except Exception as e:
            print(f"❌ Ошибка загрузки библиотеки: {e}")
            self.is_loaded = False
            
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
        """Инициализация библиотеки (вызывается только один раз)"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
        
        if self._initialized:
            return True
            
        print("🔧 Инициализация библиотеки CHAI...")
        result = self.chai.CiInit()
        if result < 0:
            raise Exception(f"Ошибка инициализации CHAI: {result}")
        
        self._initialized = True
        print("✅ Библиотека CHAI инициализирована")
        return True

    def scan_devices(self):
        """Сканирование устройств CAN - УЛУЧШЕННАЯ ВЕРСИЯ"""
        if not self.is_loaded:
            print("❌ Библиотека CHAI не загружена")
            return []

        print("🔍 Сканирование устройств CAN...")
        available_channels = []

        try:
            # Инициализируем библиотеку если не инициализирована
            if not self._initialized:
                result = self.chai.CiInit()
                if result < 0:
                    print(f"⚠️  Ошибка инициализации CHAI при сканировании: {result}")
                    # Возвращаем каналы 0 и 1 по умолчанию
                    return [0, 1]
                self._initialized = True
                print("✅ Библиотека CHAI инициализирована для сканирования")

            binfo = CANBOARD_T()
            binfo.brdnum = 0
            
            result = self.chai.CiBoardInfo(ctypes.byref(binfo))
            print(f"   Результат CiBoardInfo: {result}")

            if result >= 0:
                board_name = binfo.name.decode('utf-8', errors='ignore').strip()
                manufacturer = binfo.manufacturer.decode('utf-8', errors='ignore').strip()
                print(f"   ✅ Найдена плата: '{board_name}' от '{manufacturer}'")

                print(f"   Информация о чипах: {list(binfo.chip)}")
                for i in range(4):
                    chip_value = binfo.chip[i]
                    if chip_value >= 0:
                        channel = chip_value
                        available_channels.append(channel)
                        print(f"      📍 Канал {channel} (чип {i}) - ДОСТУПЕН")
                    else:
                        print(f"      ✗ Чип {i} значение {chip_value} - НЕДОСТУПЕН")
            else:
                print(f"⚠️  CiBoardInfo вернул ошибку: {result}")
                # Если CiBoardInfo не работает, пробуем прямой тест каналов
                print("   Пробую прямой тест каналов 0 и 1...")
                for channel in [0, 1]:
                    try:
                        result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
                        if result >= 0:
                            available_channels.append(channel)
                            print(f"      ✅ Канал {channel} доступен")
                            self.chai.CiClose(channel)  # Закрываем после теста
                        else:
                            print(f"      ✗ Канал {channel} недоступен (ошибка: {result})")
                            
                            # Для канала 1 пробуем только 11-bit
                            if channel == 1:
                                result = self.chai.CiOpen(1, CIO_CAN11)
                                if result >= 0:
                                    available_channels.append(channel)
                                    print(f"      ✅ Канал {channel} доступен в 11-bit режиме")
                                    self.chai.CiClose(1)
                    except Exception as channel_error:
                        print(f"      ✗ Ошибка теста канала {channel}: {channel_error}")
                
        except Exception as e:
            print(f"❌ Ошибка при сканировании устройств: {e}")
            print("   Возвращаю каналы 0 и 1 по умолчанию")
            available_channels = [0, 1]

        print(f"✅ Доступные каналы: {available_channels}")
        return available_channels

    def open_channel(self, channel):
        """Открытие канала с особой логикой для канала 1"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        print(f"🔓 Открытие канала {channel}...")
        
        if channel == 1:
            print(f"   Для канала 1 пробуем разные варианты открытия...")
            
            result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
            print(f"   Вариант 1 (CIO_CAN11|CIO_CAN29): результат {result}")
            
            if result >= 0:
                print(f"   ✅ Канал {channel} открыт успешно")
                self.channel = channel
                return True
            
            print(f"   Пробую открыть только в режиме 11-bit...")
            result = self.chai.CiOpen(channel, CIO_CAN11)
            if result >= 0:
                print(f"   ✅ Канал {channel} открыт в режиме 11-bit")
                self.channel = channel
                return True
            else:
                print(f"   ❌ Ошибка открытия канала {channel}: {result}")
                raise Exception(f"Не удалось открыть канал {channel}")
        else:
            result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
            if result < 0:
                raise Exception(f"Ошибка открытия канала {channel}: {result}")
            
            print(f"✅ Канал {channel} открыт")
            self.channel = channel
            return True

    def configure_channel(self, baud_rate=500000):
        """Конфигурирование канала"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")
            
        if self.channel is None:
            raise Exception("Канал не открыт")
            
        print("⚙️ Конфигурирование канала...")
        
        print(f"   🚀 Установка скорости {baud_rate} bps...")
        btr0, btr1 = self._get_btr_settings(baud_rate)
        result = self.chai.CiSetBaud(self.channel, btr0, btr1)
        if result < 0:
            raise Exception(f"Ошибка установки скорости: {result}")
        print(f"   ✅ Скорость {baud_rate} bps установлена (BTR0=0x{btr0:02X}, BTR1=0x{btr1:02X})")
        
        print("   🎯 Настройка фильтра на прием ВСЕХ сообщений...")
        result = self.chai.CiSetFilter(self.channel, 0, 0)
        if result < 0:
            raise Exception(f"Ошибка настройки фильтра: {result}")
        print("   ✅ Фильтр настроен на прием ВСЕХ сообщений")
        
        return True

    def start_channel(self):
        """Запуск канала"""
        if not self.is_loaded:
            raise Exception("Библиотека не загружена")

        if self.channel is None:
            raise Exception("Канал не открыт")

        print(f"🚀 Запуск канала {self.channel}...")
        result = self.chai.CiStart(self.channel)
        if result < 0:
            raise Exception(f"Ошибка запуска канала {self.channel}: {result}")
        
        print(f"✅ Канал {self.channel} запущен")
        return True
    
    def _get_btr_settings(self, baud_rate):
        """Настройки BTR для SJA1000"""
        btr_settings = {
            10000: (0x31, 0x1C),
            20000: (0x18, 0x1C),  
            50000: (0x09, 0x1C),
            100000: (0x04, 0x1C),
            125000: (0x03, 0x1C),
            250000: (0x01, 0x1C),
            500000: (0x00, 0x1C),
            800000: (0x00, 0x16),
            1000000: (0x00, 0x14)
        }
        
        if baud_rate not in btr_settings:
            closest_rate = min(btr_settings.keys(), key=lambda x: abs(x - baud_rate))
            print(f"⚠️  Скорость {baud_rate} не найдена, использую {closest_rate}")
            return btr_settings[closest_rate]
            
        return btr_settings[baud_rate]

    def connect(self, channel=0, baud_rate=500000):
        """Подключение к CAN каналу - ОСНОВНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        try:
            if not self.is_loaded:
                raise Exception("Библиотека CHAI не загружена")
            
            print(f"🚀 Подключение к CAN сети...")
            print(f"   Канал: {channel}")
            print(f"   Скорость: {baud_rate} bit/s")
            
            # ВАЖНОЕ ИСПРАВЛЕНИЕ: Проверяем, что channel не None
            if channel is None:
                raise Exception("Канал не выбран. Выберите канал (0 или 1) для подключения")
            
            # Останавливаем предыдущее подключение
            if self.is_connected:
                self.disconnect()
                time.sleep(0.5)
            
            # Инициализируем библиотеку если не инициализирована
            if not self._initialized:
                print("🔧 Инициализация библиотеки CHAI...")
                result = self.chai.CiInit()
                if result < 0:
                    raise Exception(f"Ошибка инициализации CHAI: {result}")
                self._initialized = True
                print("✅ Библиотека CHAI инициализирована")
            
            # Сканируем устройства (но не блокируем подключение если сканирование не работает)
            print("🔍 Сканирование доступных каналов...")
            devices = []
            try:
                devices = self.scan_devices()
                if devices:
                    print(f"   Найдены каналы: {devices}")
                    
                    # Проверяем доступность канала
                    if channel not in devices:
                        print(f"⚠️  ВНИМАНИЕ: Канал {channel} не найден в сканированных каналах")
                        print(f"   Это может быть нормально для канала 1")
                        print(f"   Продолжаю попытку подключения...")
                else:
                    print("⚠️  Не удалось определить доступные каналы")
                    print(f"   Пробую прямое подключение к каналу {channel}...")
            except Exception as scan_error:
                print(f"⚠️  Ошибка при сканировании: {scan_error}")
                print(f"   Продолжаю прямое подключение к каналу {channel}...")
            
            # Открываем канал
            print(f"🔓 Открытие канала {channel}...")
            
            if channel == 1:
                # Пробуем оба варианта для канала 1
                print("   Для канала 1 пробуем разные варианты...")
                
                # Вариант 1: Только 11-bit
                result = self.chai.CiOpen(1, CIO_CAN11)
                print(f"   Вариант 1 (только 11-bit): результат {result}")
                
                if result < 0:
                    # Вариант 2: 11-bit и 29-bit
                    result = self.chai.CiOpen(1, CIO_CAN11 | CIO_CAN29)
                    print(f"   Вариант 2 (11-bit и 29-bit): результат {result}")
                    
                if result < 0:
                    raise Exception(f"Ошибка открытия канала 1: {result}")
            else:
                # Для канала 0 используем оба режима
                result = self.chai.CiOpen(channel, CIO_CAN11 | CIO_CAN29)
                if result < 0:
                    raise Exception(f"Ошибка открытия канала {channel}: {result}")
            
            print(f"✅ Канал {channel} открыт")
            self.channel = channel
            
            # Конфигурируем
            print("⚙️ Конфигурирование канала...")
            btr0, btr1 = self._get_btr_settings(baud_rate)
            result = self.chai.CiSetBaud(channel, btr0, btr1)
            if result < 0:
                raise Exception(f"Ошибка установки скорости: {result}")
            print(f"   ✅ Скорость {baud_rate} bps установлена (BTR0=0x{btr0:02X}, BTR1=0x{btr1:02X})")
            
            print("   🎯 Настройка фильтра на прием ВСЕХ сообщений...")
            result = self.chai.CiSetFilter(channel, 0, 0)
            if result < 0:
                raise Exception(f"Ошибка настройки фильтра: {result}")
            print("   ✅ Фильтр настроен на прием ВСЕХ сообщений")
            
            # Запускаем канал
            print(f"🚀 Запуск канала {channel}...")
            result = self.chai.CiStart(channel)
            if result < 0:
                raise Exception(f"Ошибка запуска канала {channel}: {result}")
            print(f"✅ Канал {channel} запущен")
            
            # Для канала 1 тестируем чтение
            if channel == 1:
                print("🔍 Тестирование чтения канала 1...")
                if self._test_channel1_read():
                    print("✅ Чтение канала 1 работает!")
                    self.channel1_working_method = "direct"
                else:
                    print("⚠️  Прямое чтение не работает, использую альтернативный метод")
                    self.channel1_working_method = "alternative"
            
            # Сбрасываем флаги и счетчики
            self.message_count = 0
            self.is_connected = True
            self.stop_event.clear()
            
            # Запускаем поток чтения
            self.start_reading()
            
            print(f"\n✅ Успешно подключено к каналу {channel}!")
            print("🎯 Ожидаю сообщения CAN...")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            self.is_connected = False
            return False
    
    def _test_channel1_read(self):
        """Тестирование чтения канала 1"""
        try:
            test_params = [1, 0, 10, 50, 100, -1]
            
            for param in test_params:
                msg = CANMSG_T()
                result = self.chai.CiRead(1, ctypes.byref(msg), param)
                
                if result == 1:
                    print(f"   ✅ Параметр {param}: получено сообщение")
                    can_message = CANMessage(msg)
                    can_message.channel = 1
                    # Добавляем в очередь для веб-интерфейса
                    self._process_message(can_message)
                    return True
                elif result == 0:
                    print(f"   ⚠️  Параметр {param}: нет данных (таймаут)")
                    return True
                elif result == ECIINVAL:
                    print(f"   ❌ Параметр {param}: ECIINVAL")
                else:
                    print(f"   ❌ Параметр {param}: ошибка {result}")
            
            return False
            
        except Exception as e:
            print(f"   ❌ Исключение при тестировании: {e}")
            return False
    
    def start_reading(self):
        """Запуск потока чтения сообщений"""
        if not self.is_loaded or not self.is_connected:
            return False
            
        if self.read_thread and self.read_thread.is_alive():
            self.stop_event.set()
            self.read_thread.join(timeout=1.0)
        
        self.stop_event.clear()
        self.read_thread = threading.Thread(target=self._reading_loop)
        self.read_thread.daemon = True
        self.read_thread.start()
        print(f"🔄 Поток чтения CAN сообщений запущен для канала {self.channel}")
        return True
    
    def _reading_loop(self):
        """Основной цикл чтения CAN сообщений"""
        print(f"🎯 Начало чтения CAN сообщений с канала {self.channel}...")
        
        success_count = 0
        empty_cycles = 0
        last_success_time = time.time()
        
        while not self.stop_event.is_set() and self.is_connected:
            try:
                messages_read = 0
                
                if self.channel == 0:
                    messages_read = self._read_channel0()
                elif self.channel == 1:
                    messages_read = self._read_channel1_optimized()
                
                if messages_read > 0:
                    success_count += messages_read
                    empty_cycles = 0
                    last_success_time = time.time()
                    
                    if success_count <= 5 or success_count % 10 == 0:
                        print(f"📥 Канал {self.channel}: получено {success_count} сообщений")
                    
                    time.sleep(0.001)
                else:
                    empty_cycles += 1
                    
                    if empty_cycles % 100 == 0:
                        current_time = time.time()
                        time_since_last = current_time - last_success_time
                        print(f"ℹ️  Канал {self.channel}: нет сообщений {empty_cycles} циклов "
                              f"(последнее успешное: {time_since_last:.1f} сек назад)")
                    
                    if empty_cycles < 10:
                        time.sleep(0.01)
                    elif empty_cycles < 100:
                        time.sleep(0.05)
                    else:
                        time.sleep(0.1)
                        
            except Exception as e:
                print(f"❌ Ошибка в цикле чтения канала {self.channel}: {e}")
                time.sleep(0.1)
        
        print(f"🛑 Цикл чтения для канала {self.channel} остановлен")
        print(f"📊 Итог: получено {success_count} сообщений")
    
    def _read_channel0(self):
        """Чтение для канала 0 (стандартный метод)"""
        try:
            msg_buffer = (CANMSG_T * 64)()
            result = self.chai.CiRead(0, msg_buffer, 64)
            
            if result > 0:
                for i in range(result):
                    can_message = CANMessage(msg_buffer[i])
                    self._process_message(can_message)
                return result
            return 0
        except:
            return 0
    
    def _read_channel1_optimized(self):
        """Оптимизированное чтение для канала 1"""
        # Определяем метод чтения при первом вызове
        if not hasattr(self, '_channel1_read_method'):
            self._channel1_read_method = self._find_best_channel1_method()
            print(f"🔧 Для канала 1 выбран метод: {self._channel1_read_method}")

        try:
            if self._channel1_read_method == "direct":
                return self._read_channel1_direct()
            elif self._channel1_read_method == "alternative":
                return self._read_channel1_alternative()
            elif self._channel1_read_method == "reset_after_read":
                return self._read_channel1_with_reset()
            else:
                return 0

        except Exception as e:
            print(f"❌ Ошибка чтения канала 1: {e}")
            return 0
    
    def _find_best_channel1_method(self):
        """Поиск лучшего метода чтения для канала 1"""
        print("🔍 Тестирование методов чтения для канала 1...")
        
        # Пробуем прямой метод
        if self._test_direct_method():
            print("   ✅ Прямой метод работает")
            return "direct"
        
        # Пробуем метод со сбросом
        if self._test_reset_method():
            print("   ✅ Метод со сбросом работает")
            return "reset_after_read"
        
        # Пробуем альтернативный метод
        if self._test_alternative_method():
            print("   ✅ Альтернативный метод работает")
            return "alternative"
        
        print("⚠️  Ни один метод не работает")
        return "direct"  # Возвращаем прямой метод по умолчанию
    
    def _test_direct_method(self):
        """Тестирование прямого метода чтения"""
        try:
            msg = CANMSG_T()
            result = self.chai.CiRead(1, ctypes.byref(msg), 1)
            
            if result == 1 or result == 0:
                return True
            return False
        except:
            return False
    
    def _test_reset_method(self):
        """Тестирование метода со сбросом"""
        try:
            msg = CANMSG_T()
            result = self.chai.CiRead(1, ctypes.byref(msg), 1)
            
            if result == 1:
                return True
            
            # Пробуем с параметром 0
            result = self.chai.CiRead(1, ctypes.byref(msg), 0)
            if result == 1 or result == 0:
                return True
            return False
        except:
            return False
    
    def _test_alternative_method(self):
        """Тестирование альтернативного метода"""
        try:
            # Пробуем разные параметры
            for param in [10, 50, 100, -1]:
                msg = CANMSG_T()
                result = self.chai.CiRead(1, ctypes.byref(msg), param)
                
                if result == 1 or result == 0:
                    return True
            return False
        except:
            return False
    
    def _read_channel1_direct(self):
        """Прямое чтение канала 1"""
        try:
            msg = CANMSG_T()
            result = self.chai.CiRead(1, ctypes.byref(msg), 1)
            
            if result == 1:
                can_message = CANMessage(msg)
                self._process_message(can_message)
                return 1
            elif result == 0:
                return 0
            elif result == ECIINVAL:
                # ECIINVAL - попробуем восстановить
                self.channel1_error_count += 1
                if self.channel1_error_count > 10:
                    print(f"⚠️  Канал 1: много ошибок ECIINVAL ({self.channel1_error_count})")
                return 0
            else:
                print(f"⚠️  Канал 1: ошибка чтения {result}")
                return 0
                
        except Exception as e:
            print(f"❌ Исключение при чтении канала 1: {e}")
            return 0
    
    def _read_channel1_alternative(self):
        """Альтернативное чтение канала 1"""
        try:
            # Пробуем разные параметры
            for param in [1, 0, 10, 50, 100, -1]:
                msg = CANMSG_T()
                result = self.chai.CiRead(1, ctypes.byref(msg), param)
                
                if result == 1:
                    can_message = CANMessage(msg)
                    self._process_message(can_message)
                    
                    # Сбрасываем счетчик ошибок при успехе
                    if self.channel1_error_count > 0:
                        self.channel1_error_count = 0
                    
                    return 1
                elif result == 0:
                    return 0
                elif result != ECIINVAL:
                    print(f"⚠️  Канал 1: альтернативный параметр {param}, результат {result}")
            
            # Если все параметры дали ECIINVAL
            self.channel1_error_count += 1
            return 0
            
        except Exception as e:
            print(f"❌ Исключение при альтернативном чтении канала 1: {e}")
            return 0
    
    def _read_channel1_with_reset(self):
        """Чтение канала 1 со сбросом состояния"""
        messages_read = 0

        # Пробуем прочитать несколько раз
        for attempt in range(3):
            try:
                msg = CANMSG_T()
                result = self.chai.CiRead(1, ctypes.byref(msg), 1)

                if result == 1:
                    can_message = CANMessage(msg)
                    self._process_message(can_message)
                    messages_read += 1

                    # После каждого успешного чтения сбрасываем состояние
                    self._soft_reset_channel1()

                    # Пробуем прочитать еще (возможно в буфере несколько сообщений)
                    continue
                else:
                    break

            except:
                break
            
        return messages_read

    def _soft_reset_channel1(self):
        """Мягкий сброс состояния канала 1"""
        try:
            # Пробуем разные комбинации для "очистки"
            for param in [0, -1]:
                dummy = CANMSG_T()
                try:
                    self.chai.CiRead(1, ctypes.byref(dummy), param)
                except:
                    pass
                
            # Короткая пауза
            time.sleep(0.0001)

        except:
            pass
    
    def _process_message(self, can_message):
        """Обработка полученного CAN сообщения"""
        self.message_count += 1
        
        # Добавляем информацию о канале в сообщение
        can_message.channel = self.channel
        
        # ВАЖНО: Добавляем сообщение в очередь для веб-интерфейса
        try:
            self.message_queue.put(can_message, timeout=0.01)
        except queue.Full:
            # Игнорируем если очередь полна - это нормально при быстром потоке сообщений
            pass
        
        # Форматируем вывод в консоль
        frame_type = "SFF" if not can_message.msg_iseff() else "EFF"
        id_str = can_message.get_id_string().upper()
        data_hex = can_message.get_data_hex()
        timestamp = can_message.timestamp
        
        print(f"RX CH{self.channel} {self.message_count:08d} {frame_type} {id_str} {can_message.length:1d} "
              f"HEX {data_hex:<23} {timestamp:010d} {datetime.now().strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]}")
    
    def get_message(self, timeout=0.1):
        """
        Получение сообщения из очереди.
        Этот метод используется веб-интерфейсом для получения сообщений.
        """
        try:
            return self.message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def disconnect(self):
        """Отключение от CAN канала"""
        print(f"\n🔴 Отключение канала {self.channel}...")
        
        self.is_connected = False
        self.stop_event.set()
        
        # Останавливаем поток чтения
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=2.0)
            print("✅ Поток чтения остановлен")
        
        # Закрываем канал
        if self.channel is not None and self.is_loaded:
            try:
                self.chai.CiStop(self.channel)
                self.chai.CiClose(self.channel)
                print(f"✅ Канал {self.channel} закрыт")
            except Exception as e:
                print(f"⚠️  Ошибка при отключении канала: {e}")
        
        # Очищаем очередь сообщений
        try:
            while not self.message_queue.empty():
                self.message_queue.get_nowait()
        except:
            pass
            
        self.channel = None
        print(f"📊 Всего получено сообщений: {self.message_count}")
        print("✅ Отключение завершено")

# Демо-режим для тестирования без оборудования
class DemoReceiver:
    def __init__(self):
        self.is_loaded = True
        self.is_connected = False
        self.message_queue = queue.Queue(maxsize=1000)
        self.message_count = 0
        self.demo_thread = None
        self.stop_event = threading.Event()
        self.channel = None
        print("✅ Демо-режим активирован (без реального CAN оборудования)")
    
    def scan_devices(self):
        print("🔍 Демо: Сканирование устройств CAN...")
        return [0, 1]  # Демо-каналы
    
    def connect(self, channel=0, baud_rate=500000):
        print(f"🚀 Демо: Подключение к каналу {channel}, скорость {baud_rate}")
        self.is_connected = True
        self.channel = channel
        self.stop_event.clear()
        self.message_count = 0
        self.start_demo_messages()
        return True
    
    def start_demo_messages(self):
        """Генерация демо-сообщений"""
        if self.demo_thread and self.demo_thread.is_alive():
            self.stop_event.set()
            self.demo_thread.join(timeout=1.0)
        
        self.demo_thread = threading.Thread(target=self._demo_loop)
        self.demo_thread.daemon = True
        self.demo_thread.start()
    
    def _demo_loop(self):
        """Цикл генерации демо-сообщений"""
        import random
        
        # Пример сообщений с реальными данными
        demo_messages = [
            # ID: 0x181 - сообщение 1 (как в вашем логе)
            (0x181, [0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00]),
            # ID: 0x182 - сообщение 2 (как в вашем логе)
            (0x182, [0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04]),
            # Дополнительные тестовые сообщения
            (0x123, [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]),
            (0x456, [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00, 0x99]),
        ]
        
        message_num = 0
        
        while not self.stop_event.is_set() and self.is_connected:
            try:
                msg_id, data = random.choice(demo_messages)
                message_num += 1
                
                canmsg = CANMSG_T()
                canmsg.id = msg_id
                canmsg.len = 8
                for i in range(8):
                    canmsg.data[i] = data[i]
                canmsg.flags = 0
                canmsg.ts = int(time.time() * 1000000)
                
                message = CANMessage(canmsg)
                message.channel = self.channel
                self._process_message(message, message_num)
                
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Демо ошибка: {e}")
                time.sleep(1)
    
    def _process_message(self, can_message, message_num):
        """Обработка демо-сообщения"""
        self.message_count += 1
        
        # Добавляем в очередь для веб-интерфейса
        try:
            self.message_queue.put(can_message, timeout=0.01)
        except queue.Full:
            pass
        
        # Выводим в консоль
        frame_type = "SFF" if not can_message.msg_iseff() else "EFF"
        id_str = can_message.get_id_string().upper()
        data_hex = can_message.get_data_hex()
        
        print(f"DEMO CH{self.channel} RX {message_num:08d} {frame_type} {id_str} {can_message.length:1d} "
              f"HEX {data_hex:<23} {datetime.now().strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]}")
    
    def disconnect(self):
        print("🔴 Демо: Отключение")
        self.is_connected = False
        self.stop_event.set()
        
        if self.demo_thread and self.demo_thread.is_alive():
            self.demo_thread.join(timeout=2.0)
        
        # Очищаем очередь
        try:
            while not self.message_queue.empty():
                self.message_queue.get_nowait()
        except:
            pass
    
    def get_message(self, timeout=0.1):
        """
        Получение сообщения из очереди.
        Этот метод используется веб-интерфейсом для получения сообщений.
        """
        try:
            return self.message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

# Автоматический выбор между реальным и демо-режимом
def create_receiver():
    """
    Фабрика для создания приемника.
    Автоматически выбирает между реальным CHAIReceiver и демо-режимом.
    """
    try:
        # Сначала пробуем создать реальный приемник
        receiver = CHAIReceiver()
        if receiver.is_loaded:
            print("✅ Использую реальный CHAI приемник")
            return receiver
        else:
            print("⚠️  CHAIReceiver не загрузился, активирую демо-режим")
            return DemoReceiver()
    except Exception as e:
        print(f"⚠️  Ошибка создания CHAIReceiver, активирую демо-режим: {e}")
        return DemoReceiver()