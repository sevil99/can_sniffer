import ctypes
import time
from ctypes import c_ubyte, c_ushort, c_uint, c_int, c_void_p, Structure, POINTER, CFUNCTYPE
from datetime import datetime

# Структура CAN сообщения (аналогична can_receiver.py)
class CANMessage:
    def __init__(self, can_id, data, extended=False, rtr=False, timestamp=None):
        self.id = can_id
        self.data = data
        self.length = len(data)
        self.extended = extended
        self.rtr = rtr
        self.timestamp = timestamp or time.time()
        self.receive_time = datetime.now()
    
    def get_id_string(self):
        return f"{self.id:03X}"
    
    def get_data_hex(self):
        return ' '.join(f'{b:02X}' for b in self.data)
    
    def get_frame_type(self):
        return "EXT" if self.extended else "STD"
    
    def get_rtr_status(self):
        return "RTR" if self.rtr else "DATA"

class CHAITransmitter:
    def __init__(self):
        self.initialized = False
        self.channel = 0
        self.baud_rate = 500000
        self.init_chai_library()
    
    def init_chai_library(self):
        """Инициализация CHAI библиотеки"""
        try:
            # Загрузка библиотеки CHAI
            self.chai_lib = ctypes.CDLL("chai.dll")  # Для Windows
            # self.chai_lib = ctypes.CDLL("libchai.so")  # Для Linux
            
            # Определение структур
            class CANMsg(Structure):
                _fields_ = [
                    ("id", c_uint),
                    ("data", c_ubyte * 8),
                    ("len", c_ubyte),
                    ("flags", c_ushort),
                    ("ts", c_uint)
                ]
            
            self.CANMsg = CANMsg
            
            # Определение функций
            self.chai_lib.Clinit.restype = c_int
            self.chai_lib.Clinit.argtypes = []
            
            self.chai_lib.CiOpen.restype = c_int
            self.chai_lib.CiOpen.argtypes = [c_ubyte, c_ubyte]
            
            self.chai_lib.CiClose.restype = c_int
            self.chai_lib.CiClose.argtypes = [c_ubyte]
            
            self.chai_lib.CiStart.restype = c_int
            self.chai_lib.CiStart.argtypes = [c_ubyte]
            
            self.chai_lib.CiSetBaud.restype = c_int
            self.chai_lib.CiSetBaud.argtypes = [c_ubyte, c_ubyte, c_ubyte]
            
            self.chai_lib.CiTransmit.restype = c_int
            self.chai_lib.CiTransmit.argtypes = [c_ubyte, POINTER(CANMsg)]
            
            self.initialized = True
            print("✅ CHAI трансмиттер инициализирован")
            
        except Exception as e:
            print(f"❌ Ошибка инициализации CHAI трансмиттера: {e}")
            self.initialized = False
    
    def connect(self, channel=0, baud_rate=500000):
        """Подключение к CAN устройству"""
        if not self.initialized:
            return False
        
        try:
            self.channel = channel
            self.baud_rate = baud_rate
            
            # Инициализация библиотеки
            result = self.chai_lib.Clinit()
            if result != 0:
                print(f"❌ Ошибка инициализации CHAI: {result}")
                return False
            
            # Открытие канала
            flags = 0
            if baud_rate > 1000000:  # Для расширенных форматов
                flags |= 2  # CIO_CAN29
            
            result = self.chai_lib.CiOpen(channel, flags)
            if result != 0:
                print(f"❌ Ошибка открытия канала {channel}: {result}")
                return False
            
            # Установка скорости
            baud_code = self.get_baud_code(baud_rate)
            result = self.chai_lib.CiSetBaud(channel, baud_code, 0)
            if result != 0:
                print(f"❌ Ошибка установки скорости: {result}")
                return False
            
            # Запуск канала
            result = self.chai_lib.CiStart(channel)
            if result != 0:
                print(f"❌ Ошибка запуска канала: {result}")
                return False
            
            print(f"✅ CAN трансмиттер подключен: канал {channel}, скорость {baud_rate}")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка подключения трансмиттера: {e}")
            return False
    
    def disconnect(self):
        """Отключение от CAN устройства"""
        if not self.initialized:
            return
        
        try:
            self.chai_lib.CiClose(self.channel)
            print("✅ CAN трансмиттер отключен")
        except Exception as e:
            print(f"❌ Ошибка отключения трансмиттера: {e}")
    
    def get_baud_code(self, baud_rate):
        """Получение кода скорости для CHAI"""
        baud_rates = {
            10000: 0x31,    # BCI_10K
            20000: 0x18,    # BCI_20K  
            50000: 0x09,    # BCI_50K
            100000: 0x04,   # BCI_100K
            125000: 0x03,   # BCI_125K
            250000: 0x01,   # BCI_250K
            500000: 0x00,   # BCI_500K
            800000: 0x80,   # BCI_800K
            1000000: 0x81   # BCI_1M
        }
        return baud_rates.get(baud_rate, 0x00)
    
    def send_message(self, can_id, data, extended=False, rtr=False):
        """Отправка CAN сообщения"""
        if not self.initialized:
            return False
        
        try:
            # Подготовка структуры сообщения
            msg = self.CANMsg()
            msg.id = can_id
            msg.len = len(data)
            
            # Заполнение данных
            for i in range(min(len(data), 8)):
                msg.data[i] = data[i]
            
            # Установка флагов
            msg.flags = 0
            if extended:
                msg.flags |= 0x04  # EFF flag
            if rtr:
                msg.flags |= 0x01  # RTR flag
            
            # Отправка сообщения
            result = self.chai_lib.CiTransmit(self.channel, ctypes.byref(msg))
            
            if result == 0:
                print(f"✅ CAN сообщение отправлено: ID={can_id:03X}, данные={self.bytes_to_hex(data)}")
                return True
            else:
                print(f"❌ Ошибка отправки CAN сообщения: код {result}")
                return False
                
        except Exception as e:
            print(f"❌ Исключение при отправке CAN сообщения: {e}")
            return False
    
    def bytes_to_hex(self, data):
        """Конвертация байтов в hex строку"""
        return ' '.join(f'{b:02X}' for b in data)
    
    def send_test_message(self):
        """Отправка тестового сообщения"""
        test_data = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]
        return self.send_message(0x123, test_data)