from flask import Flask, render_template, request, jsonify, send_file
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

app = Flask(__name__)

# Инициализация CAN приемника
try:
    from can_receiver import CHAIReceiver, CANMessage
    receiver = CHAIReceiver()
except Exception as e:
    print(f"❌ Ошибка инициализации CAN приемника: {e}")
    receiver = None
can_transmitter = None

# Инициализация CAN трансмиттера
try:
    from can_transmitter import CHAITransmitter
    can_transmitter = CHAITransmitter()
except Exception as e:
    print(f"❌ Ошибка инициализации CAN трансмиттера: {e}")
    can_transmitter = None

# Глобальные переменные
can_messages = []
message_queue = queue.Queue()
is_connected = False
connection_thread = None
stop_thread = False
current_channels = []  # Список активных каналов

# Для графиков и парсинга
signal_data = defaultdict(lambda: deque(maxlen=1000))
selected_signals = {}  # {signal_key: parser_config}

def parse_float_from_data(can_message, start_byte=0, byte_order='little_endian'):
    """Парсинг float из данных сообщения"""
    if can_message.length < start_byte + 4:
        return None
    
    try:
        data_bytes = can_message.data[start_byte:start_byte + 4]
        
        if byte_order == 'big_endian':
            float_value = struct.unpack('>f', data_bytes)[0]
        else:
            float_value = struct.unpack('<f', data_bytes)[0]
        
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
    """Парсинг CAN сообщения по конфигурации сигнала с поддержкой каналов"""
    message_id = can_message.get_id_string()
    signals = {}
    
    for signal_name, config in signal_config.items():
        parser_type = config.get('type', 'float32')
        byte_order = config.get('byte_order', 'little_endian')
        start_byte = config.get('start_byte', 0)
        length = config.get('length', 4)
        channel = config.get('channel', '0')  # Канал из конфигурации
        
        # Проверяем соответствие канала
        if hasattr(can_message, 'channel') and str(can_message.channel) != str(channel):
            signals[signal_name] = 0.0
            continue
        
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
            
            if parser_type == 'float32':
                # Парсинг float32
                if byte_order == 'big_endian':
                    float_value = struct.unpack('>f', data_bytes)[0]
                else:
                    float_value = struct.unpack('<f', data_bytes)[0]
                    
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
                if float_value is None:
                    float_value = 0.0
            
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
    if not can_messages:
        print("📝 Нет сообщений для сохранения")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"can_messages_{timestamp}.json"
    
    try:
        messages_data = []
        for msg in can_messages:
            # Базовый парсинг для отображения
            signals = {}
            for i in range(min(msg.length, 8)):
                signals[f'Byte_{i}'] = msg.data[i]
            
            # Добавляем информацию о канале
            channel = getattr(msg, 'channel', None)
            
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
                'channels': current_channels,
                'messages': messages_data
            }, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Сообщения сохранены в файл: {filename}")
        print(f"📊 Всего сообщений: {len(messages_data)}")
        print(f"📡 Каналы: {current_channels}")
        
    except Exception as e:
        print(f"❌ Ошибка сохранения в файл: {e}")

# В функции can_reading_thread добавьте больше логов:
def can_reading_thread():
    """Поток чтения CAN сообщений"""
    global is_connected
    
    print("🎯 Запуск потока чтения CAN сообщений...")
    read_counts = {channel: 0 for channel in current_channels}
    
    while is_connected and not stop_thread:
        try:
            # Получаем сообщения со всех активных каналов
            for channel in current_channels:
                if channel in receiver.message_queues:
                    try:
                        message = receiver.get_message(channel, timeout=0.01)
                        if message:
                            read_counts[channel] += 1
                            if read_counts[channel] % 10 == 0:  # Логируем каждое 10-е сообщение
                                print(f"📥 Канал {channel}: получено {read_counts[channel]} сообщений")
                                print(f"   Последнее: ID={message.get_id_string()}, "
                                      f"Data={message.get_data_hex()}")
                            
                            # Добавляем информацию о канале
                            message.channel = channel
                            # Обрабатываем сообщение
                            process_can_message(message)
                            
                    except queue.Empty:
                        pass
                    except Exception as e:
                        print(f"❌ Ошибка чтения с канала {channel}: {e}")
                
            time.sleep(0.001)  # Короткая пауза
                
        except Exception as e:
            print(f"❌ Общая ошибка в потоке чтения: {e}")
            time.sleep(0.1)
    
    print("🛑 Поток чтения CAN сообщений остановлен")
    print(f"📊 Итог по каналам: {read_counts}")

# В функции process_can_message добавьте фильтр:
def process_can_message(can_message):
    """Обработка ВСЕХ CAN сообщений с канала 1"""
    global can_messages
    
    channel = getattr(can_message, 'channel', None)
    
    # ФИЛЬТР: только канал 1
    if channel != 1:
        return  # Пропускаем другие каналы
    
    # Добавляем в историю сообщений
    can_messages.append(can_message)
    
    # Ограничиваем размер истории
    if len(can_messages) > 10000:
        can_messages = can_messages[-5000:]
    
    # Обрабатываем выбранные сигналы
    current_time = time.time()
    first_bytes_signature = get_message_signature(can_message, 4)
    message_id = can_message.get_id_string().upper()
    
    # Парсим сообщение для выбранных сигналов
    for signal_key, parser_config in selected_signals.items():
        # Проверяем что сигнал для этого ID и канала
        if signal_key.startswith(f"{message_id}_") and str(channel) == str(parser_config.get('channel', '1')):
            parts = signal_key.split('_')
            if len(parts) >= 2:
                signal_name = '_'.join(parts[1:])
                
                # Проверяем соответствие первым байтам если указано
                required_first_bytes = parser_config.get('first_bytes', '')
                if required_first_bytes:
                    current_first_bytes = get_message_signature(can_message, len(required_first_bytes) // 2)
                    if required_first_bytes.upper() != current_first_bytes:
                        continue
                
                signal_config = {signal_name: parser_config}
                signals = parse_can_message_with_config(can_message, signal_config)
                
                if signal_name in signals:
                    signal_data[signal_key].append({
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
    if not receiver:
        return jsonify({'error': 'CAN приемник не инициализирован'})
    
    try:
        available_channels = receiver.scan_devices()
        return jsonify({
            'available_channels': available_channels,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/connect', methods=['POST'])
def connect_device():
    """Подключение к CAN устройству"""
    global is_connected, connection_thread, stop_thread, current_channels
    
    if not receiver:
        return jsonify({'status': 'error', 'message': 'CAN приемник не инициализирован'})
    
    data = request.json
    channels = data.get('channels', [0])  # Теперь список каналов
    baud_rate = data.get('baud_rate', 500000)
    
    try:
        print(f"🚀 Подключение к CAN сети...")
        print(f"   Каналы: {channels}")
        print(f"   Скорость: {baud_rate} bit/s")
        
        # Сохраняем выбранные каналы
        current_channels = channels
        
        # Подключаемся
        success = receiver.connect(channels=channels, baud_rate=baud_rate)
        
        if success:
            is_connected = True
            stop_thread = False
            
            # Запускаем поток чтения
            if connection_thread is None or not connection_thread.is_alive():
                connection_thread = threading.Thread(target=can_reading_thread)
                connection_thread.daemon = True
                connection_thread.start()
                print("✅ Поток чтения CAN сообщений запущен")
            
            return jsonify({
                'status': 'connected',
                'channels': channels,
                'baud_rate': baud_rate,
                'message': f'Успешное подключение к каналам {channels}'
            })
        else:
            return jsonify({'status': 'error', 'message': 'Не удалось подключиться'})
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_device():
    """Отключение от CAN устройства"""
    global is_connected, stop_thread
    
    is_connected = False
    stop_thread = True
    
    # Сохраняем сообщения в файл перед отключением
    print("💾 Сохранение сообщений в файл...")
    save_messages_to_file()
    
    if receiver:
        receiver.disconnect()
    
    return jsonify({'status': 'disconnected', 'message': 'Устройство отключено, сообщения сохранены'})

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
    """Получение статуса подключения"""
    return jsonify({
        'connected': is_connected,
        'message_count': len(can_messages),
        'library_loaded': receiver is not None,
        'channels': current_channels,
        'selected_signals_count': len(selected_signals)
    })

@app.route('/api/messages')
def get_messages():
    """Получение списка сообщений"""
    limit = request.args.get('limit', 100, type=int)
    filtered_messages = can_messages[-limit:]
    
    messages_data = []
    for msg in filtered_messages:
        # Базовый парсинг для отображения
        signals = {}
        for i in range(min(msg.length, 8)):
            signals[f'Byte_{i}'] = msg.data[i]
        
        # Парсим float из первых 4 байтов
        float_value = parse_float_from_data(msg, 0)
        if float_value is not None:
            signals['Float_First_4_Bytes'] = float_value
        
        # Добавляем сигнатуру первых 4 байтов
        signature = get_message_signature(msg, 4)
        signals['First_4_Bytes'] = signature
        
        # Информация о канале
        channel = getattr(msg, 'channel', None)
        
        msg_data = {
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
        messages_data.append(msg_data)
    
    return jsonify(messages_data)

@app.route('/api/messages/clear', methods=['POST'])
def clear_messages():
    """Очистка списка сообщений"""
    global can_messages
    can_messages.clear()
    return jsonify({'status': 'cleared', 'message': 'Сообщения очищены'})

@app.route('/api/statistics')
def get_statistics():
    """Статистика по сообщениям"""
    statistics = {
        'total_messages': len(can_messages),
        'by_id': {},
        'by_type': {'STD': 0, 'EXT': 0},
        'by_rtr': {'DATA': 0, 'RTR': 0},
        'by_channel': {}
    }
    
    # Группируем по ID и каналу
    messages_by_id = {}
    for msg in can_messages:
        msg_id = msg.get_id_string()
        channel = getattr(msg, 'channel', 'unknown')
        
        # Создаем уникальный ключ с учетом канала
        msg_key = f"{msg_id}_CH{channel}"
        if msg_key not in messages_by_id:
            messages_by_id[msg_key] = []
        messages_by_id[msg_key].append(msg)
        
        # Считаем по типам
        statistics['by_type'][msg.get_frame_type()] += 1
        statistics['by_rtr'][msg.get_rtr_status()] += 1
        
        # Считаем по каналам
        if channel not in statistics['by_channel']:
            statistics['by_channel'][str(channel)] = 0
        statistics['by_channel'][str(channel)] += 1
    
    for msg_key, messages in messages_by_id.items():
        msg_id = msg_key.split('_CH')[0]
        channel = msg_key.split('_CH')[1] if '_CH' in msg_key else 'unknown'
        
        statistics['by_id'][msg_key] = {
            'count': len(messages),
            'frequency': len(messages) / 10.0 if len(messages) > 1 else 0,
            'last_seen': messages[-1].receive_time.strftime('%H:%M:%S.%f')[:-3],
            'channel': channel
        }
    
    return jsonify(statistics)

@app.route('/api/available_ids')
def get_available_ids():
    """Получение списка доступных CAN ID"""
    available_ids = set()
    
    for msg in can_messages:
        channel = getattr(msg, 'channel', '')
        available_ids.add(f"{msg.get_id_string()}_CH{channel}")
    
    return jsonify(list(available_ids))

@app.route('/api/select_signal', methods=['POST'])
def select_signal():
    """Выбор сигнала для построения графика"""
    global selected_signals
    
    data = request.json
    message_id = data.get('message_id')
    signal_name = data.get('signal_name')
    parser_config = data.get('parser_config', {})
    
    # Извлекаем канал из конфигурации
    channel = parser_config.get('channel', '0')
    
    # Создаем уникальный ключ с учетом канала
    signal_key = f"{message_id}_{signal_name}_{channel}"
    selected_signals[signal_key] = parser_config
    
    print(f"📊 Выбран сигнал для графика: {signal_key} с конфигурацией {parser_config}")
    
    return jsonify({'status': 'success', 'signal_key': signal_key})

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

@app.route('/api/selected_signals')
def get_selected_signals():
    """Получение списка выбранных сигналов"""
    return jsonify(selected_signals)

@app.route('/api/chart_data')
def get_chart_data():
    """Получение данных для графиков с поддержкой каналов"""
    time_window = request.args.get('time_window', 60, type=float)
    use_real_time = request.args.get('real_time', 'true').lower() == 'true'
    current_time = time.time()
    
    chart_data = {}
    
    for signal_key, parser_config in selected_signals.items():
        if signal_key in signal_data and signal_data[signal_key]:
            recent_data = [
                point for point in signal_data[signal_key] 
                if current_time - point['timestamp'] <= time_window
            ]
            
            if recent_data:
                timestamps = [point['timestamp'] for point in recent_data]
                values = [point['value'] for point in recent_data]
                
                if timestamps:
                    if use_real_time:
                        # Используем реальное время (секунды с начала эпохи)
                        normalized_times = timestamps
                    else:
                        # Относительное время (0 - самое старое значение)
                        min_time = min(timestamps)
                        normalized_times = [t - min_time for t in timestamps]
                    
                    # Извлекаем информацию о сигнале
                    channel = parser_config.get('channel', '0')
                    first_bytes = parser_config.get('first_bytes', '')
                    
                    # Создаем label с информацией о канале
                    parts = signal_key.split('_')
                    if len(parts) >= 3:
                        message_id = parts[0]
                        signal_name = '_'.join(parts[1:-1])
                        
                        label = f"CH{channel}: {message_id} {signal_name}"
                        if first_bytes:
                            label = f"{label} [{first_bytes}]"
                        
                        chart_data[signal_key] = {
                            'timestamps': normalized_times,
                            'values': values,
                            'id': message_id,
                            'signal': signal_name,
                            'first_bytes': first_bytes,
                            'channel': channel,
                            'label': label,
                            'real_time': use_real_time,
                            'config': parser_config
                        }
    
    return jsonify(chart_data)

@app.route('/api/export/messages')
def export_messages():
    """Экспорт сообщений в файл"""
    format_type = request.args.get('format', 'json')
    
    if format_type == 'json':
        messages_data = []
        for msg in can_messages:
            signals = {}
            for i in range(min(msg.length, 8)):
                signals[f'Byte_{i}'] = msg.data[i]
            
            # Парсим float из первых 4 байтов
            float_value = parse_float_from_data(msg, 0)
            if float_value is not None:
                signals['Float_First_4_Bytes'] = float_value
            
            # Добавляем сигнатуру первых байтов
            signature = get_message_signature(msg, 4)
            signals['First_4_Bytes'] = signature
            
            # Информация о канале
            channel = getattr(msg, 'channel', None)
            
            messages_data.append({
                'id': msg.get_id_string(),
                'data': msg.get_data_hex(),
                'length': msg.length,
                'type': msg.get_frame_type(),
                'rtr': msg.get_rtr_status(),
                'timestamp': msg.receive_time.isoformat(),
                'first_bytes_signature': signature,
                'float_value': float_value,
                'channel': channel,
                'signals': signals
            })
        
        return jsonify(messages_data)
    
    elif format_type == 'csv':
        # Создаем CSV
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Channel', 'ID', 'Type', 'RTR', 'Length', 'First_4_Bytes', 'Data', 'Float_Value', 'Timestamp'])
        
        for msg in can_messages:
            # Парсим float из первых 4 байтов
            float_value = parse_float_from_data(msg, 0)
            signature = get_message_signature(msg, 4)
            channel = getattr(msg, 'channel', '')
            
            writer.writerow([
                channel,
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
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'can_messages_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )

# Управление конфигурацией
CONFIG_FILE = 'can_signals_config.json'

def load_signal_config():
    """Загрузка конфигурации сигналов из файла"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Ошибка загрузки конфигурации: {e}")
            return {}
    return {}

def save_signal_config(config):
    """Сохранение конфигурации сигналов в файл"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения конфигурации: {e}")
        return False

@app.route('/api/save_signal_config', methods=['POST'])
def save_signal_config_route():
    """Сохранение конфигурации сигналов в файл"""
    global selected_signals
    try:
        if save_signal_config(selected_signals):
            return jsonify({'status': 'success', 'message': 'Конфигурация сохранена'})
        else:
            return jsonify({'status': 'error', 'message': 'Ошибка сохранения'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/load_signal_config', methods=['POST'])
def load_signal_config_route():
    """Загрузка конфигурации сигналов из файла"""
    global selected_signals
    try:
        loaded_config = load_signal_config()
        selected_signals = loaded_config
        return jsonify({'status': 'success', 'message': 'Конфигурация загружена', 'signals': selected_signals})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/export_signal_config')
def export_signal_config():
    """Экспорт конфигурации сигналов"""
    try:
        return send_file(
            CONFIG_FILE,
            as_attachment=True,
            download_name='can_signals_config.json'
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/send_message', methods=['POST'])
def send_can_message():
    """Отправка CAN сообщения"""
    if not can_transmitter or not is_connected:
        return jsonify({'status': 'error', 'message': 'CAN трансмиттер не инициализирован или нет подключения'})
    
    try:
        data = request.json
        can_id = data.get('id')
        can_data = data.get('data', [])
        is_extended = data.get('extended', False)
        is_rtr = data.get('rtr', False)
        channel = data.get('channel', 0)  # Добавлен параметр канала
        
        if not can_id:
            return jsonify({'status': 'error', 'message': 'ID сообщения обязателен'})
        
        if channel not in current_channels:
            return jsonify({'status': 'error', 'message': f'Канал {channel} не подключен'})
        
        # Преобразуем данные в байты
        data_bytes = bytes(can_data)
        
        # Отправляем сообщение
        success = can_transmitter.send_message(
            can_id=can_id,
            data=data_bytes,
            extended=is_extended,
            rtr=is_rtr,
            channel=channel  # Передаем канал
        )
        
        if success:
            return jsonify({'status': 'success', 'message': f'CAN сообщение отправлено на канал {channel}'})
        else:
            return jsonify({'status': 'error', 'message': 'Ошибка отправки CAN сообщения'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/send_test_message', methods=['POST'])
def send_test_message():
    """Отправка тестового CAN сообщения"""
    if not can_transmitter or not is_connected:
        return jsonify({'status': 'error', 'message': 'CAN трансмиттер не инициализирован или нет подключения'})
    
    try:
        data = request.json
        channel = data.get('channel', 0)  # Канал для отправки
        
        if channel not in current_channels:
            return jsonify({'status': 'error', 'message': f'Канал {channel} не подключен'})
        
        # Тестовое сообщение
        can_id = 0x123
        test_data = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])
        
        # Отправляем тестовое сообщение
        success = can_transmitter.send_message(
            can_id=can_id,
            data=test_data,
            extended=False,
            rtr=False,
            channel=channel
        )
        
        if success:
            return jsonify({'status': 'success', 'message': f'Тестовое CAN сообщение отправлено на канал {channel}'})
        else:
            return jsonify({'status': 'error', 'message': 'Ошибка отправки тестового CAN сообщения'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 CAN Monitor Web Interface - Multi-Channel Support")
    print("=" * 60)
    print("📊 Функциональность:")
    print("  • Поддержка нескольких CAN каналов")
    print("  • Отдельные графики для каждого сигнала и канала")
    print("  • Реальное время на осях X")
    print("  • Парсинг различных типов данных")
    print("  • Разделение по первым байтам")
    print("=" * 60)
    print("🌐 Доступно по адресу: http://localhost:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)