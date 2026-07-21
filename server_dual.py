from flask import Flask, Response, render_template, request, jsonify, send_file
import threading
import time
import queue
import json
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import ctypes
from collections import defaultdict, deque
import re
import struct
import os
import math
import plotly.graph_objects as go
import plotly.io as pio
# Добавьте этот импорт для работы с временем:
import plotly.express as px



app = Flask(__name__)

# ==================== ОТДЕЛЬНЫЕ ЭКЗЕМПЛЯРЫ ДЛЯ КАЖДОГО КАНАЛА ====================

# Отдельные экземпляры приемников для каждого канала
try:
    from can_receiver import CHAIReceiver, CANMessage, create_receiver
    # Создаем отдельные экземпляры для каждого канала
    receiver_channel0 = create_receiver()  # Отдельный экземпляр для канала 0
    receiver_channel1 = create_receiver()  # Отдельный экземпляр для канала 1
    
    print("=" * 60)
    print("🔧 Проверка инициализации CAN приемников...")
    if receiver_channel0 and receiver_channel0.is_loaded:
        print(f"✅ Приемник для канала 0 инициализирован")
    else:
        print(f"⚠️  Приемник для канала 0 НЕ инициализирован (демо-режим)")
    
    if receiver_channel1 and receiver_channel1.is_loaded:
        print(f"✅ Приемник для канала 1 инициализирован")
    else:
        print(f"⚠️  Приемник для канала 1 НЕ инициализирован (демо-режим)")
    print("=" * 60)
        
except Exception as e:
    print(f"❌ Ошибка инициализации CAN приемников: {e}")
    receiver_channel0 = None
    receiver_channel1 = None

# Инициализация CAN трансмиттера
try:
    from can_transmitter import CHAITransmitter
    can_transmitter = CHAITransmitter()
except Exception as e:
    print(f"❌ Ошибка инициализации CAN трансмиттера: {e}")
    can_transmitter = None

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ ДВУХ КАНАЛОВ ====================

# Храним сообщения отдельно для каждого канала
can_messages_ch0 = []  # Сообщения канала 0
can_messages_ch1 = []  # Сообщения канала 1

# Статусы подключения для каждого канала
is_connected_ch0 = False
is_connected_ch1 = False

# Потоки чтения для каждого канала
reading_thread_ch0 = None
reading_thread_ch1 = None

# Флаги остановки потоков
stop_thread_ch0 = False
stop_thread_ch1 = False

# Текущие настройки для каждого канала
current_settings = {
    'ch0': {'baud_rate': 500000},
    'ch1': {'baud_rate': 500000}
}

# Для графиков и парсинга - храним отдельно по каналам
signal_data_ch0 = defaultdict(lambda: deque(maxlen=1000))
signal_data_ch1 = defaultdict(lambda: deque(maxlen=1000))

# Выбранные сигналы с указанием канала
selected_signals = {}  # {signal_key: parser_config}

# ГЛАВНОЕ ИСПРАВЛЕНИЕ: Добавляем thread locks для безопасности потоков
messages_lock_ch0 = threading.Lock()
messages_lock_ch1 = threading.Lock()

# Сохранение всех сообщений вместе для совместимости со старым кодом
can_messages_all = []  # Все сообщения от обоих каналов (для совместимости)

def parse_float_from_data(can_message, start_byte=0, byte_order='little_endian'):
    """Парсинг float из данных сообщения"""
    if can_message.length < start_byte + 4:
        return None
    
    try:
        data_bytes = can_message.data[start_byte:start_byte + 4]
        
        # Проверка на FF FF FF FF
        if all(b == 0xFF for b in data_bytes):
            return 4294967295.0
        
        # Проверка на 00 00 00 00
        if all(b == 0x00 for b in data_bytes):
            return 0.0
        
        if byte_order == 'big_endian':
            float_value = struct.unpack('>f', data_bytes)[0]
        else:
            float_value = struct.unpack('<f', data_bytes)[0]
        
        # Проверяем на NaN, Inf и т.д.
        if math.isnan(float_value) or math.isinf(float_value):
            # Пробуем парсить как uint32
            if byte_order == 'big_endian':
                uint_value = struct.unpack('>I', data_bytes)[0]
            else:
                uint_value = struct.unpack('<I', data_bytes)[0]
            return float(uint_value)
        
        return float_value
    except Exception as e:
        print(f"❌ Ошибка парсинга float: {e}, данные: {can_message.get_data_hex()}")
        return None

def get_message_signature(can_message, first_bytes_count=4):
    """Получение сигнатуры сообщения по первым N байтам"""
    if can_message.length < first_bytes_count:
        return "unknown"
    
    signature_bytes = can_message.data[:first_bytes_count]
    signature_hex = ''.join(f'{b:02X}' for b in signature_bytes)
    return signature_hex

def parse_can_message_with_config(can_message, signal_config):
    """Парсинг CAN сообщения по конфигурации сигнала"""
    message_id = can_message.get_id_string()
    signals = {}
    
    for signal_name, config in signal_config.items():
        parser_type = config.get('type', 'float32')
        byte_order = config.get('byte_order', 'little_endian')
        start_byte = config.get('start_byte', 0)
        length = config.get('length', 4)
        
        # Проверяем соответствие первым байтам если указано
        first_bytes_pattern = config.get('first_bytes', '')
        if first_bytes_pattern:
            current_first_bytes = get_message_signature(can_message, len(first_bytes_pattern) // 2)
            if first_bytes_pattern.upper() != current_first_bytes:
                signals[signal_name] = 0.0
                continue
        
        try:
            # Извлекаем нужные байты для парсинга
            if start_byte + length > can_message.length:
                signals[signal_name] = 0.0
                continue
                
            data_bytes = can_message.data[start_byte:start_byte + length]
            
            # ПРОВЕРКА: Если данные FF FF FF FF
            if all(b == 0xFF for b in data_bytes):
                # Это специальное значение - возвращаем максимальное
                if parser_type in ['uint32', 'int32', 'float32']:
                    signals[signal_name] = 4294967295.0  # Max uint32
                    continue
                elif parser_type in ['uint16', 'int16']:
                    signals[signal_name] = 65535.0  # Max uint16
                    continue
                elif parser_type in ['uint8', 'int8']:
                    signals[signal_name] = 255.0  # Max uint8
                    continue
            
            if parser_type == 'float32':
                # Парсинг float32
                if byte_order == 'big_endian':
                    float_value = struct.unpack('>f', data_bytes)[0]
                else:
                    float_value = struct.unpack('<f', data_bytes)[0]
                    
                # Проверяем на NaN/Inf
                if math.isnan(float_value) or math.isinf(float_value):
                    # Если NaN, пробуем парсить как uint32
                    if byte_order == 'big_endian':
                        uint_value = struct.unpack('>I', data_bytes)[0]
                    else:
                        uint_value = struct.unpack('<I', data_bytes)[0]
                    float_value = float(uint_value)
                    
            elif parser_type == 'int32':
                # Парсинг 32-битного целого
                if byte_order == 'big_endian':
                    int_value = struct.unpack('>i', data_bytes)[0]
                else:
                    int_value = struct.unpack('<i', data_bytes)[0]
                float_value = float(int_value)
                
            elif parser_type == 'uint32':
                # Парсинг 32-битного беззнакового целого
                if byte_order == 'big_endian':
                    uint_value = struct.unpack('>I', data_bytes)[0]
                else:
                    uint_value = struct.unpack('<I', data_bytes)[0]
                float_value = float(uint_value)
                
            elif parser_type == 'int16':
                # Парсинг 16-битного целого
                if len(data_bytes) >= 2:
                    if byte_order == 'big_endian':
                        int_value = struct.unpack('>h', data_bytes[:2])[0]
                    else:
                        int_value = struct.unpack('<h', data_bytes[:2])[0]
                    float_value = float(int_value)
                else:
                    float_value = 0.0
                    
            elif parser_type == 'uint16':
                # Парсинг 16-битного беззнакового целого
                if len(data_bytes) >= 2:
                    if byte_order == 'big_endian':
                        uint_value = struct.unpack('>H', data_bytes[:2])[0]
                    else:
                        uint_value = struct.unpack('<H', data_bytes[:2])[0]
                    float_value = float(uint_value)
                else:
                    float_value = 0.0
                    
            elif parser_type == 'int8':
                # Парсинг 8-битного целого
                float_value = float(struct.unpack('b', bytes([data_bytes[0]]))[0])
                
            elif parser_type == 'uint8':
                # Парсинг 8-битного беззнакового целого
                float_value = float(data_bytes[0])
            
            else:  # По умолчанию float32
                float_value = parse_float_from_data(can_message, start_byte, byte_order)
                if float_value is None or math.isnan(float_value):
                    # Пробуем парсить как uint32
                    if byte_order == 'big_endian':
                        uint_value = struct.unpack('>I', data_bytes)[0]
                    else:
                        uint_value = struct.unpack('<I', data_bytes)[0]
                    float_value = float(uint_value)
            
            # Применяем масштаб и смещение
            scale = config.get('scale', 1.0)
            offset = config.get('offset', 0.0)
            signals[signal_name] = float_value * scale + offset
            
        except Exception as e:
            print(f"❌ Ошибка парсинга {parser_type}: {e}")
            signals[signal_name] = 0.0
    
    return signals

def save_messages_to_file():
    """Сохранение сообщений в файл при отключении"""
    try:
        # Сохраняем сообщения обоих каналов
        all_messages = []
        with messages_lock_ch0:
            all_messages.extend([{'message': item['message'], 'channel': 0, 'timestamp': item['timestamp']} 
                               for item in can_messages_ch0])
        with messages_lock_ch1:
            all_messages.extend([{'message': item['message'], 'channel': 1, 'timestamp': item['timestamp']} 
                               for item in can_messages_ch1])
        
        if not all_messages:
            print("📝 Нет сообщений для сохранения")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"can_messages_{timestamp}.json"
        
        messages_data = []
        for item in all_messages:
            msg = item['message']
            channel = item['channel']
            
            # Базовый парсинг для отображения
            signals = {}
            for i in range(min(msg.length, 8)):
                signals[f'Byte_{i}'] = msg.data[i]
            
            # Парсим float из первых 4 байтов для отображения
            float_value = parse_float_from_data(msg, 0)
            if float_value is not None:
                signals['Float_First_4_Bytes'] = float_value
            
            # Добавляем сигнатуру первых 4 байтов
            signature = get_message_signature(msg, 4)
            signals['First_4_Bytes'] = signature
            
            messages_data.append({
                'id': msg.get_id_string(),
                'data': msg.get_data_hex(),
                'data_bytes': list(msg.data),
                'length': msg.length,
                'type': msg.get_frame_type(),
                'rtr': msg.get_rtr_status(),
                'timestamp': msg.receive_time.isoformat(),
                'timestamp_raw': msg.timestamp,
                'first_bytes_signature': signature,
                'float_value': float_value,
                'channel': channel,
                'signals': signals
            })
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'export_time': datetime.now().isoformat(),
                'total_messages': len(messages_data),
                'messages_ch0': len(can_messages_ch0),
                'messages_ch1': len(can_messages_ch1),
                'messages': messages_data
            }, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Сообщения сохранены в файл: {filename}")
        print(f"📊 Всего сообщений: {len(messages_data)}")
        print(f"📡 Канал 0: {len(can_messages_ch0)} сообщений")
        print(f"📡 Канал 1: {len(can_messages_ch1)} сообщений")
        
    except Exception as e:
        print(f"❌ Ошибка сохранения в файл: {e}")

def can_reading_thread_ch0():
    """Поток чтения CAN сообщений для канала 0"""
    global is_connected_ch0, stop_thread_ch0
    
    print(f"🎯 Запуск потока чтения CAN сообщений для канала 0...")
    
    while is_connected_ch0 and not stop_thread_ch0 and receiver_channel0:
        try:
            message = None
            
            # Получаем сообщение из приемника канала 0
            if hasattr(receiver_channel0, 'get_message'):
                try:
                    message = receiver_channel0.get_message(timeout=0.1)
                except queue.Empty:
                    message = None
                except Exception as e:
                    print(f"⚠️  Ошибка get_message канал 0: {e}")
                    message = None
            
            if message:
                # Обрабатываем сообщение
                process_can_message(message, 0)
                    
        except Exception as e:
            print(f"❌ Ошибка в потоке чтения канала 0: {e}")
            time.sleep(0.1)
    
    print(f"🛑 Поток чтения CAN сообщений для канала 0 остановлен")

def can_reading_thread_ch1():
    """Поток чтения CAN сообщений для канала 1"""
    global is_connected_ch1, stop_thread_ch1
    
    print(f"🎯 Запуск потока чтения CAN сообщений для канала 1...")
    
    while is_connected_ch1 and not stop_thread_ch1 and receiver_channel1:
        try:
            message = None
            
            # Получаем сообщение из приемника канала 1
            if hasattr(receiver_channel1, 'get_message'):
                try:
                    message = receiver_channel1.get_message(timeout=0.1)
                except queue.Empty:
                    message = None
                except Exception as e:
                    print(f"⚠️  Ошибка get_message канал 1: {e}")
                    message = None
            
            if message:
                # Обрабатываем сообщение
                process_can_message(message, 1)
                    
        except Exception as e:
            print(f"❌ Ошибка в потоке чтения канала 1: {e}")
            time.sleep(0.1)
    
    print(f"🛑 Поток чтения CAN сообщений для канала 1 остановлен")

def process_can_message(can_message, channel):
    """Обработка CAN сообщений с указанием канала"""
    global can_messages_all
    
    # Добавляем отладку
    if can_messages_all and len(can_messages_all) % 50 == 0:  # Выводим каждое 50-е сообщение
        print(f"📥 Канал {channel}: ID={can_message.get_id_string()}, "
              f"Data={can_message.get_data_hex()}")
    
    # Добавляем в соответствующий список сообщений
    if channel == 0:
        with messages_lock_ch0:
            can_messages_ch0.append({
                'message': can_message,
                'channel': channel,
                'timestamp': datetime.now()
            })
            # Ограничиваем размер истории
            if len(can_messages_ch0) > 10000:
                can_messages_ch0 = can_messages_ch0[-5000:]
    else:
        with messages_lock_ch1:
            can_messages_ch1.append({
                'message': can_message,
                'channel': channel,
                'timestamp': datetime.now()
            })
            # Ограничиваем размер истории
            if len(can_messages_ch1) > 10000:
                can_messages_ch1 = can_messages_ch1[-5000:]
    
    # Добавляем в общий список для совместимости
    can_messages_all.append({
        'message': can_message,
        'channel': channel,
        'timestamp': datetime.now()
    })
    if len(can_messages_all) > 20000:
        can_messages_all = can_messages_all[-10000:]
    
    # Обрабатываем выбранные сигналы
    current_time = time.time()
    first_bytes_signature = get_message_signature(can_message, 4)
    message_id = can_message.get_id_string().upper()
    
    # Получаем данные сигналов для соответствующего канала
    signal_data_dict = signal_data_ch0 if channel == 0 else signal_data_ch1
    
    for signal_key, parser_config in selected_signals.items():
        # Извлекаем канал из конфигурации сигнала
        config_channel = str(parser_config.get('channel', '0'))
        
        # Проверяем соответствие канала
        if str(channel) != config_channel:
            continue
        
        # Проверяем соответствие ID
        if '_CH' in signal_key:
            key_parts = signal_key.split('_')
            key_id = key_parts[0] if key_parts else ''
        else:
            key_id = signal_key.split('_')[0] if '_' in signal_key else signal_key
        
        # Нормализуем ID для сравнения
        if key_id and message_id:
            key_id_clean = key_id.replace('0X', '').replace('0x', '').upper()
            message_id_clean = message_id.replace('0X', '').replace('0x', '').upper()
            
            if key_id_clean != message_id_clean:
                continue
        
        # Извлекаем имя сигнала
        parts = signal_key.split('_')
        if len(parts) < 2:
            continue
            
        signal_name_parts = []
        for i in range(1, len(parts)):
            if parts[i].startswith('CH'):
                break
            signal_name_parts.append(parts[i])
        
        if not signal_name_parts:
            continue
            
        signal_name = '_'.join(signal_name_parts)
        
        # Проверяем соответствие первым байтам если указано
        required_first_bytes = parser_config.get('first_bytes', '')
        if required_first_bytes:
            current_first_bytes = get_message_signature(can_message, len(required_first_bytes) // 2)
            if required_first_bytes.upper() != current_first_bytes:
                continue
        
        # Парсим сигнал
        signal_config = {signal_name: parser_config}
        signals = parse_can_message_with_config(can_message, signal_config)
        
        if signal_name in signals:
            # Добавляем точку данных
            signal_data_dict[signal_key].append({
                'timestamp': current_time,
                'value': signals[signal_name],
                'id': message_id,
                'signal': signal_name,
                'first_bytes': first_bytes_signature,
                'channel': channel
            })

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    return render_template('index_v6.html')

@app.route('/api/scan_devices')
def scan_devices():
    """Сканирование доступных устройств"""
    print("📡 API вызов: /api/scan_devices")
    
    all_channels = []
    
    try:
        if receiver_channel0 and receiver_channel0.is_loaded:
            print("🔍 Сканирование через receiver_channel0...")
            channels0 = receiver_channel0.scan_devices()
            print(f"   Каналы от receiver_channel0: {channels0}")
            if channels0:
                all_channels.extend(channels0)
        
        if receiver_channel1 and receiver_channel1.is_loaded:
            print("🔍 Сканирование через receiver_channel1...")
            channels1 = receiver_channel1.scan_devices()
            print(f"   Каналы от receiver_channel1: {channels1}")
            if channels1:
                for ch in channels1:
                    if ch not in all_channels:
                        all_channels.append(ch)
        
        if not all_channels:
            print("⚠️  Ни один приемник не вернул каналы, возвращаю [0, 1] по умолчанию")
            all_channels = [0, 1]
        
        all_channels = list(set(all_channels))
        all_channels.sort()
        
        print(f"✅ Итоговые доступные каналы: {all_channels}")
        
        return jsonify({
            'available_channels': all_channels,
            'status': 'success'
        })
        
    except Exception as e:
        print(f"❌ Ошибка сканирования устройств: {e}")
        return jsonify({
            'available_channels': [0, 1],
            'status': 'warning',
            'message': f'Ошибка сканирования: {str(e)}. Возвращены каналы по умолчанию.'
        })

@app.route('/api/connect', methods=['POST'])
def connect_device():
    """Подключение к CAN устройству - Поддерживает два канала одновременно"""
    global is_connected_ch0, is_connected_ch1, stop_thread_ch0, stop_thread_ch1
    global reading_thread_ch0, reading_thread_ch1, current_settings
    
    print("🔌 API вызов: /api/connect")
    print(f"📦 Полученные данные: {request.json}")
    
    data = request.json
    channel = data.get('channel')
    baud_rate = data.get('baud_rate', 500000)
    
    if channel is None:
        print("❌ ОШИБКА: Параметр 'channel' не получен от клиента")
        return jsonify({
            'status': 'error', 
            'message': 'Выберите канал для подключения (0 или 1). Параметр channel не получен.'
        })
    
    try:
        print(f"🚀 Подключение к CAN сети...")
        print(f"   Канал: {channel}")
        print(f"   Скорость: {baud_rate} bit/s")
        
        # Выбираем правильный приемник для канала
        if channel == 0:
            current_receiver = receiver_channel0
            is_connected = is_connected_ch0
            stop_thread = stop_thread_ch0
            thread_var = reading_thread_ch0
        elif channel == 1:
            current_receiver = receiver_channel1
            is_connected = is_connected_ch1
            stop_thread = stop_thread_ch1
            thread_var = reading_thread_ch1
        else:
            print(f"❌ Неподдерживаемый канал: {channel}")
            return jsonify({
                'status': 'error', 
                'message': f'Неподдерживаемый канал: {channel}. Поддерживаются только каналы 0 и 1.'
            })
        
        if not current_receiver:
            print(f"❌ Приемник для канала {channel} не создан")
            return jsonify({
                'status': 'error', 
                'message': f'Приемник для канала {channel} не инициализирован'
            })
        
        # Останавливаем предыдущий поток для этого канала, если он активен
        if is_connected and thread_var and thread_var.is_alive():
            print(f"⚠️  Остановка предыдущего подключения для канала {channel}...")
            stop_thread = True
            thread_var.join(timeout=1.0)
            time.sleep(0.5)
        
        # Сбрасываем флаги для этого канала
        stop_thread = False
        
        # Очищаем старые данные для этого канала
        if channel == 0:
            with messages_lock_ch0:
                can_messages_ch0.clear()
            signal_data_ch0.clear()
            is_connected_ch0 = False
        else:
            with messages_lock_ch1:
                can_messages_ch1.clear()
            signal_data_ch1.clear()
            is_connected_ch1 = False
        
        # Сохраняем настройки
        current_settings[f'ch{channel}']['baud_rate'] = baud_rate
        
        print(f"🔌 Подключение канала {channel} через отдельный экземпляр приемника")
        
        try:
            success = current_receiver.connect(channel=channel, baud_rate=baud_rate)
        except Exception as connect_error:
            print(f"❌ Исключение при подключении канала {channel}: {connect_error}")
            return jsonify({
                'status': 'error', 
                'message': f'Ошибка подключения канала {channel}: {str(connect_error)}'
            })
        
        if success:
            if channel == 0:
                is_connected_ch0 = True
                stop_thread_ch0 = False
                # Запускаем поток чтения для канала 0
                reading_thread_ch0 = threading.Thread(target=can_reading_thread_ch0)
                reading_thread_ch0.daemon = True
                reading_thread_ch0.start()
            else:
                is_connected_ch1 = True
                stop_thread_ch1 = False
                # Запускаем поток чтения для канала 1
                reading_thread_ch1 = threading.Thread(target=can_reading_thread_ch1)
                reading_thread_ch1.daemon = True
                reading_thread_ch1.start()
            
            print(f"✅ Успешно подключено к каналу {channel}")
            print(f"✅ Поток чтения CAN сообщений запущен для канала {channel}")
            
            return jsonify({
                'status': 'connected',
                'channel': channel,
                'baud_rate': baud_rate,
                'message': f'Успешное подключение к каналу {channel}',
                'is_demo_mode': not current_receiver.is_loaded if hasattr(current_receiver, 'is_loaded') else True,
                'dual_channel_support': True,
                'other_channel_status': is_connected_ch1 if channel == 0 else is_connected_ch0
            })
        else:
            print(f"❌ Не удалось подключиться к каналу {channel}")
            return jsonify({
                'status': 'error', 
                'message': f'Не удалось подключиться к каналу {channel}'
            })
        
    except Exception as e:
        print(f"❌ Ошибка подключения канала {channel}: {e}")
        return jsonify({
            'status': 'error', 
            'message': str(e)
        })

@app.route('/api/disconnect', methods=['POST'])
def disconnect_device():
    """Отключение от CAN устройства"""
    data = request.json
    channel = data.get('channel')
    
    if channel is None:
        return jsonify({
            'status': 'error', 
            'message': 'Укажите канал для отключения (0 или 1)'
        })
    
    print(f"🔴 API вызов: /api/disconnect для канала {channel}")
    
    if channel == 0:
        global is_connected_ch0, stop_thread_ch0
        is_connected_ch0 = False
        stop_thread_ch0 = True
        
        if receiver_channel0:
            receiver_channel0.disconnect()
    elif channel == 1:
        global is_connected_ch1, stop_thread_ch1
        is_connected_ch1 = False
        stop_thread_ch1 = True
        
        if receiver_channel1:
            receiver_channel1.disconnect()
    else:
        return jsonify({
            'status': 'error', 
            'message': f'Неподдерживаемый канал: {channel}'
        })
    
    print(f"💾 Сохранение сообщений канала {channel} в файл...")
    save_messages_to_file()
    
    return jsonify({
        'status': 'disconnected', 
        'channel': channel,
        'message': f'Канал {channel} отключен'
    })

@app.route('/api/disconnect_all', methods=['POST'])
def disconnect_all():
    """Отключение от всех каналов"""
    global is_connected_ch0, is_connected_ch1, stop_thread_ch0, stop_thread_ch1
    
    print("🔴 API вызов: /api/disconnect_all - отключение всех каналов")
    
    # Отключаем оба канала
    is_connected_ch0 = False
    is_connected_ch1 = False
    stop_thread_ch0 = True
    stop_thread_ch1 = True
    
    if receiver_channel0:
        receiver_channel0.disconnect()
    
    if receiver_channel1:
        receiver_channel1.disconnect()
    
    print("💾 Сохранение всех сообщений в файл...")
    save_messages_to_file()
    
    return jsonify({
        'status': 'disconnected_all', 
        'message': 'Все каналы отключены, сообщения сохранены'
    })

@app.route('/api/save_logs', methods=['POST'])
def save_logs():
    """Ручное сохранение логов в файл"""
    try:
        save_messages_to_file()
        return jsonify({'status': 'success', 'message': 'Логи сохранены в файл'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/status')
def get_status():
    """Получение статуса подключения для обоих каналов"""
    channel0_connected = False
    channel0_loaded = False
    channel1_connected = False
    channel1_loaded = False
    
    if receiver_channel0:
        if hasattr(receiver_channel0, 'is_connected'):
            channel0_connected = receiver_channel0.is_connected
        if hasattr(receiver_channel0, 'is_loaded'):
            channel0_loaded = receiver_channel0.is_loaded
    
    if receiver_channel1:
        if hasattr(receiver_channel1, 'is_connected'):
            channel1_connected = receiver_channel1.is_connected
        if hasattr(receiver_channel1, 'is_loaded'):
            channel1_loaded = receiver_channel1.is_loaded
    
    return jsonify({
        'channel0': {
            'connected': is_connected_ch0 and channel0_connected,
            'loaded': channel0_loaded,
            'message_count': len(can_messages_ch0),
            'baud_rate': current_settings['ch0']['baud_rate']
        },
        'channel1': {
            'connected': is_connected_ch1 and channel1_connected,
            'loaded': channel1_loaded,
            'message_count': len(can_messages_ch1),
            'baud_rate': current_settings['ch1']['baud_rate']
        },
        'selected_signals_count': len(selected_signals),
        'dual_channel_mode': True,
        'messages_total': len(can_messages_ch0) + len(can_messages_ch1)
    })

@app.route('/api/messages')
def get_messages():
    """Получение списка сообщений - поддерживает фильтрацию по каналу"""
    channel = request.args.get('channel', type=int)  # Фильтр по каналу
    limit = request.args.get('limit', 100, type=int)
    
    # Определяем, какой канал запрашиваем
    if channel == 0:
        messages_list = can_messages_ch0
        messages_lock = messages_lock_ch0
    elif channel == 1:
        messages_list = can_messages_ch1
        messages_lock = messages_lock_ch1
    else:
        # По умолчанию возвращаем сообщения обоих каналов
        # Объединяем сообщения обоих каналов
        all_messages = []
        with messages_lock_ch0:
            all_messages.extend([{'message': item['message'], 'channel': 0} for item in can_messages_ch0[-limit//2:]])
        with messages_lock_ch1:
            all_messages.extend([{'message': item['message'], 'channel': 1} for item in can_messages_ch1[-limit//2:]])
        
        # Сортируем по времени
        all_messages.sort(key=lambda x: x['message'].receive_time, reverse=True)
        all_messages = all_messages[:limit]
        
        messages_data = []
        for item in all_messages:
            msg = item['message']
            channel = item['channel']
            messages_data.append(format_message_data(msg, channel))
        
        return jsonify(messages_data)
    
    # Получаем сообщения для конкретного канала
    with messages_lock:
        start_idx = max(0, len(messages_list) - limit)
        filtered_data = messages_list[start_idx:]
        
        messages_data = []
        for item in filtered_data:
            msg = item['message']
            channel = item['channel']
            messages_data.append(format_message_data(msg, channel))
    
    return jsonify(messages_data)

def format_message_data(msg, channel):
    """Форматирование данных сообщения"""
    signals = {}
    for i in range(min(msg.length, 8)):
        signals[f'Byte_{i}'] = msg.data[i]
    
    float_value = parse_float_from_data(msg, 0)
    signature = get_message_signature(msg, 4)
    
    if float_value is not None:
        import math
        if math.isnan(float_value) or math.isinf(float_value):
            signals['Float_First_4_Bytes'] = None
        else:
            signals['Float_First_4_Bytes'] = float_value
    else:
        signals['Float_First_4_Bytes'] = None
    
    signals['First_4_Bytes'] = signature
    
    return {
        'id': msg.id,
        'id_hex': msg.get_id_string(),
        'data': list(msg.data),
        'data_hex': msg.get_data_hex(),
        'length': msg.length,
        'frame_type': msg.get_frame_type(),
        'rtr_status': msg.get_rtr_status(),
        'timestamp': msg.timestamp,
        'timestamp_str': msg.receive_time.strftime('%H:%M:%S.%f')[:-3],
        'channel': channel,
        'signals': signals
    }

@app.route('/api/messages/clear', methods=['POST'])
def clear_messages():
    """Очистка списка сообщений - поддерживает очистку по каналу"""
    data = request.json
    channel = data.get('channel')
    
    if channel == 0:
        with messages_lock_ch0:
            can_messages_ch0.clear()
        signal_data_ch0.clear()
        return jsonify({'status': 'cleared', 'channel': 0, 'message': 'Сообщения канала 0 очищены'})
    elif channel == 1:
        with messages_lock_ch1:
            can_messages_ch1.clear()
        signal_data_ch1.clear()
        return jsonify({'status': 'cleared', 'channel': 1, 'message': 'Сообщения канала 1 очищены'})
    else:
        # Очистка всех каналов
        with messages_lock_ch0:
            can_messages_ch0.clear()
        with messages_lock_ch1:
            can_messages_ch1.clear()
        signal_data_ch0.clear()
        signal_data_ch1.clear()
        global can_messages_all
        can_messages_all.clear()
        return jsonify({'status': 'cleared_all', 'message': 'Все сообщения очищены'})

@app.route('/api/statistics')
def get_statistics():
    """Статистика по сообщениям для обоих каналов"""
    statistics = {
        'total_messages': len(can_messages_ch0) + len(can_messages_ch1),
        'channel0': {
            'total': len(can_messages_ch0),
            'by_id': {},
            'by_type': {'STD': 0, 'EXT': 0},
            'by_rtr': {'DATA': 0, 'RTR': 0}
        },
        'channel1': {
            'total': len(can_messages_ch1),
            'by_id': {},
            'by_type': {'STD': 0, 'EXT': 0},
            'by_rtr': {'DATA': 0, 'RTR': 0}
        },
        'dual_channel': True
    }
    
    # Обработка канала 0
    with messages_lock_ch0:
        messages_by_id_ch0 = {}
        for item in can_messages_ch0:
            msg = item['message']
            msg_id = msg.get_id_string()
            
            if msg_id not in messages_by_id_ch0:
                messages_by_id_ch0[msg_id] = []
            messages_by_id_ch0[msg_id].append(item)
            
            statistics['channel0']['by_type'][msg.get_frame_type()] += 1
            statistics['channel0']['by_rtr'][msg.get_rtr_status()] += 1
        
        for msg_id, messages in messages_by_id_ch0.items():
            last_msg = messages[-1]['message']
            statistics['channel0']['by_id'][msg_id] = {
                'count': len(messages),
                'frequency': len(messages) / 10.0 if len(messages) > 1 else 0,
                'last_seen': last_msg.receive_time.strftime('%H:%M:%S.%f')[:-3]
            }
    
    # Обработка канала 1
    with messages_lock_ch1:
        messages_by_id_ch1 = {}
        for item in can_messages_ch1:
            msg = item['message']
            msg_id = msg.get_id_string()
            
            if msg_id not in messages_by_id_ch1:
                messages_by_id_ch1[msg_id] = []
            messages_by_id_ch1[msg_id].append(item)
            
            statistics['channel1']['by_type'][msg.get_frame_type()] += 1
            statistics['channel1']['by_rtr'][msg.get_rtr_status()] += 1
        
        for msg_id, messages in messages_by_id_ch1.items():
            last_msg = messages[-1]['message']
            statistics['channel1']['by_id'][msg_id] = {
                'count': len(messages),
                'frequency': len(messages) / 10.0 if len(messages) > 1 else 0,
                'last_seen': last_msg.receive_time.strftime('%H:%M:%S.%f')[:-3]
            }
    
    return jsonify(statistics)

@app.route('/api/available_ids')
def get_available_ids():
    """Получение списка доступных CAN ID для обоих каналов"""
    available_ids = set()
    
    with messages_lock_ch0:
        for item in can_messages_ch0:
            msg = item['message']
            available_ids.add(f"{msg.get_id_string()}_CH0")
    
    with messages_lock_ch1:
        for item in can_messages_ch1:
            msg = item['message']
            available_ids.add(f"{msg.get_id_string()}_CH1")
    
    return jsonify(list(available_ids))

@app.route('/api/select_signal', methods=['POST'])
def select_signal():
    """Выбор сигнала для построения графика с указанием канала"""
    global selected_signals
    
    data = request.json
    message_id = data.get('message_id')
    signal_name = data.get('signal_name')
    parser_config = data.get('parser_config', {})
    
    # Извлекаем канал из конфигурации или из message_id
    channel = parser_config.get('channel')
    if not channel and '_CH' in message_id:
        # Пытаемся извлечь канал из message_id
        parts = message_id.split('_CH')
        if len(parts) > 1:
            message_id = parts[0]
            channel = parts[1]
    
    if not channel:
        channel = '0'  # По умолчанию канал 0
    
    # Обновляем конфигурацию
    parser_config['channel'] = str(channel)
    
    # Формируем signal_key
    signal_key = f"{message_id}_{signal_name}_CH{channel}"
    selected_signals[signal_key] = parser_config
    
    print(f"📊 Выбран сигнал для графика: {signal_key} с конфигурацией {parser_config}")
    
    return jsonify({'status': 'success', 'signal_key': signal_key, 'channel': channel})

@app.route('/api/remove_signal', methods=['POST'])
def remove_signal():
    """Удаление сигнала из графиков"""
    global selected_signals
    
    data = request.json
    signal_key = data.get('signal_key')
    
    if signal_key in selected_signals:
        del selected_signals[signal_key]
        print(f"🗑️ Удален сигнал из графиков: {signal_key}")
    
    return jsonify({'status': 'success'})

@app.route('/api/chart_data_single', methods=['GET'])
def chart_data_single():
    """Получение данных для одного графика"""
    signal_key = request.args.get('signal_key')
    time_window = request.args.get('time_window', 60, type=float)
    current_time = time.time()
    
    if not signal_key:
        return jsonify({})
    
    # Определяем, к какому каналу относится сигнал
    channel = '0'
    if '_CH' in signal_key:
        parts = signal_key.split('_CH')
        if len(parts) > 1:
            channel = parts[1]
    
    # Получаем данные из соответствующего канала
    signal_data_dict = signal_data_ch0 if channel == '0' else signal_data_ch1
    
    if signal_key in signal_data_dict and signal_data_dict[signal_key]:
        recent_data = [
            point for point in signal_data_dict[signal_key] 
            if current_time - point['timestamp'] <= time_window
        ]
        
        if recent_data:
            timestamps = [point['timestamp'] for point in recent_data]
            values = [point['value'] for point in recent_data]
            
            config = selected_signals.get(signal_key, {})
            
            parts = signal_key.split('_')
            if len(parts) >= 3:
                message_id = parts[0]
                signal_name_parts = []
                for i in range(1, len(parts)):
                    if parts[i].startswith('CH'):
                        break
                    signal_name_parts.append(parts[i])
                
                signal_name = '_'.join(signal_name_parts)
                
                first_bytes = config.get('first_bytes', '')
                label = f"CH{channel}: {message_id} {signal_name}"
                if first_bytes:
                    label = f"{label} [{first_bytes}]"
                
                return jsonify({
                    'timestamps': timestamps,
                    'values': values,
                    'id': message_id,
                    'signal': signal_name,
                    'first_bytes': first_bytes,
                    'channel': channel,
                    'label': label,
                    'config': config,
                    'count': len(recent_data),
                    'min_value': min(values) if values else 0,
                    'max_value': max(values) if values else 0,
                    'avg_value': sum(values)/len(values) if values else 0
                })
    
    return jsonify({
        'timestamps': [],
        'values': [],
        'label': signal_key,
        'count': 0,
        'channel': channel
    })

@app.route('/api/chart_data')
def get_chart_data():
    """Получение данных для графиков с поддержкой двух каналов"""
    time_window = request.args.get('time_window', 60, type=float)
    use_real_time = request.args.get('real_time', 'true').lower() == 'true'
    current_time = time.time()
    
    chart_data = {}
    
    for signal_key, parser_config in selected_signals.items():
        # Определяем канал сигнала
        channel = parser_config.get('channel', '0')
        
        # Получаем данные из соответствующего канала
        signal_data_dict = signal_data_ch0 if channel == '0' else signal_data_ch1
        
        if signal_key in signal_data_dict and signal_data_dict[signal_key]:
            recent_data = [
                point for point in signal_data_dict[signal_key] 
                if current_time - point['timestamp'] <= time_window
            ]
            
            if recent_data:
                timestamps = [point['timestamp'] for point in recent_data]
                values = [point['value'] for point in recent_data]
                
                if timestamps:
                    if use_real_time:
                        normalized_times = timestamps
                    else:
                        min_time = min(timestamps)
                        normalized_times = [t - min_time for t in timestamps]
                    
                    first_bytes = parser_config.get('first_bytes', '')
                    
                    parts = signal_key.split('_')
                    if len(parts) >= 3:
                        message_id = parts[0]
                        signal_name_parts = []
                        for i in range(1, len(parts)):
                            if parts[i].startswith('CH'):
                                break
                            signal_name_parts.append(parts[i])
                        
                        signal_name = '_'.join(signal_name_parts)
                        
                        label = f"CH{channel}: {message_id} {signal_name}"
                        if first_bytes:
                            label = f"{label} [{first_bytes}]"
                        
                        # Цвета для разных каналов
                        colors = {
                            '0': '#00dbde',  # Голубой для канала 0
                            '1': '#fc00ff'   # Розовый для канала 1
                        }
                        
                        chart_data[signal_key] = {
                            'timestamps': normalized_times,
                            'values': values,
                            'id': message_id,
                            'signal': signal_name,
                            'first_bytes': first_bytes,
                            'channel': channel,
                            'label': label,
                            'real_time': use_real_time,
                            'config': parser_config,
                            'color': colors.get(channel, '#3498db'),
                            'count': len(values),
                            'stats': {
                                'min': min(values) if values else 0,
                                'max': max(values) if values else 0,
                                'avg': sum(values)/len(values) if values else 0
                            }
                        }
    
    return jsonify(chart_data)

@app.route('/api/selected_signals')
def get_selected_signals():
    """Получение списка выбранных сигналов с группировкой по каналам"""
    signals_by_channel = {
        'channel0': {},
        'channel1': {}
    }
    
    for signal_key, config in selected_signals.items():
        channel = config.get('channel', '0')
        if channel == '0':
            signals_by_channel['channel0'][signal_key] = config
        else:
            signals_by_channel['channel1'][signal_key] = config
    
    return jsonify({
        'all_signals': selected_signals,
        'by_channel': signals_by_channel,
        'count_channel0': len(signals_by_channel['channel0']),
        'count_channel1': len(signals_by_channel['channel1']),
        'total_count': len(selected_signals)
    })

# Остальные функции (export_chart_html, export_chart_plotly, save_signal_config_route, и т.д.)
# остаются без изменений, так как они работают с selected_signals

@app.route('/api/export/messages')
def export_messages():
    """Экспорт сообщений в файл - поддерживает оба канала"""
    format_type = request.args.get('format', 'json')
    channel = request.args.get('channel', type=int)  # Опциональный фильтр по каналу
    
    if format_type == 'json':
        # Собираем сообщения из нужного канала или всех каналов
        messages_to_export = []
        
        if channel == 0 or channel is None:
            with messages_lock_ch0:
                for item in can_messages_ch0:
                    messages_to_export.append({
                        'channel': 0,
                        'message': item['message'],
                        'timestamp': item['timestamp']
                    })
        
        if channel == 1 or channel is None:
            with messages_lock_ch1:
                for item in can_messages_ch1:
                    messages_to_export.append({
                        'channel': 1,
                        'message': item['message'],
                        'timestamp': item['timestamp']
                    })
        
        # Сортируем по времени
        messages_to_export.sort(key=lambda x: x['timestamp'], reverse=True)
        
        messages_data = []
        for item in messages_to_export[:1000]:  # Ограничиваем экспорт
            msg = item['message']
            channel = item['channel']
            
            signals = {}
            for i in range(min(msg.length, 8)):
                signals[f'Byte_{i}'] = msg.data[i]
            
            float_value = parse_float_from_data(msg, 0)
            if float_value is not None:
                signals['Float_First_4_Bytes'] = float_value
            
            signature = get_message_signature(msg, 4)
            signals['First_4_Bytes'] = signature
            
            messages_data.append({
                'channel': channel,
                'id': msg.get_id_string(),
                'data': msg.get_data_hex(),
                'length': msg.length,
                'type': msg.get_frame_type(),
                'rtr': msg.get_rtr_status(),
                'timestamp': msg.receive_time.isoformat(),
                'first_bytes_signature': signature,
                'float_value': float_value,
                'signals': signals
            })
        
        return jsonify({
            'export_time': datetime.now().isoformat(),
            'total_messages': len(messages_data),
            'channel0_messages': len(can_messages_ch0),
            'channel1_messages': len(can_messages_ch1),
            'channel_filter': channel,
            'messages': messages_data
        })
    
    elif format_type == 'csv':
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Channel', 'ID', 'Type', 'RTR', 'Length', 'First_4_Bytes', 'Data', 'Float_Value', 'Timestamp'])
        
        # Собираем все сообщения
        all_messages = []
        
        if channel == 0 or channel is None:
            with messages_lock_ch0:
                for item in can_messages_ch0:
                    all_messages.append((0, item))
        
        if channel == 1 or channel is None:
            with messages_lock_ch1:
                for item in can_messages_ch1:
                    all_messages.append((1, item))
        
        # Сортируем по времени
        all_messages.sort(key=lambda x: x[1]['timestamp'], reverse=True)
        
        for channel_num, item in all_messages[:1000]:  # Ограничиваем экспорт
            msg = item['message']
            
            float_value = parse_float_from_data(msg, 0)
            signature = get_message_signature(msg, 4)
            
            writer.writerow([
                channel_num,
                msg.get_id_string(),
                msg.get_frame_type(),
                msg.get_rtr_status(),
                msg.length,
                signature,
                msg.get_data_hex(),
                f"{float_value:.6f}" if float_value is not None else '',
                msg.receive_time.isoformat()
            ])
        
        output.seek(0)
        filename = f'can_messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        if channel is not None:
            filename += f'_ch{channel}'
        filename += '.csv'
        
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

# Остальные функции (send_can_message, send_test_message) остаются без изменений

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 CAN Monitor Web Interface v6.0 - ДВУХКАНАЛЬНАЯ ВЕРСИЯ")
    print("=" * 60)
    print("📊 Функциональность:")
    print("  • ПАРАЛЛЕЛЬНАЯ РАБОТА ДВУХ КАНАЛОВ")
    print("  • Отдельные приемники для каждого канала")
    print("  • Раздельное хранение сообщений")
    print("  • Раздельные графики по каналам")
    print("  • Одновременное подключение/отключение каналов")
    print("  • Общая и раздельная статистика")
    print("=" * 60)
    print("🌐 Доступно по адресу: http://localhost:5000")
    print("=" * 60)
    print("💡 Советы по использованию:")
    print("  1. Можно подключить оба канала одновременно")
    print("  2. Каналы работают независимо друг от друга")
    print("  3. Фильтруйте сообщения по каналам")
    print("  4. Используйте разные цвета для разных каналов на графиках")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)