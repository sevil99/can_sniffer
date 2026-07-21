class CANMonitor {
    constructor() {
        this.isConnected = false;
        this.messageCount = 0;
        this.charts = new Map();
        this.selectedSignals = new Map();
        this.updateInterval = null;
        this.useRealTime = true;
        this.selectedChannels = [1];  // Фиксированный канал 1

        this.availableIDs = new Set();
        this.discoveredIDs = new Map();
        this.autoRefreshInterval = null;

        this.initializeEventListeners();
        this.updateStatus();
        this.loadAvailableIDs();
        this.loadSelectedSignals();

        console.log('CAN Monitor v6 - Чтение всех сообщений с канала 1');
    }

    initializeEventListeners() {
        // Кнопки управления
        $('#scanBtn').click(() => this.scanDevices());
        $('#connectBtn').click(() => this.connect());
        $('#disconnectBtn').click(() => this.disconnect());
        $('#clearBtn').click(() => this.clearMessages());
        $('#updateChartsBtn').click(() => this.updateCharts());
        $('#clearChartsBtn').click(() => this.clearCharts());
        $('#addSignalBtn').click(() => this.showAddSignalModal());
        $('#saveLogsBtn').click(() => this.saveLogs());

        // Кнопки отправки сообщений
        $('#sendMessageBtn').click(() => this.sendCustomMessage());
        $('#sendTestBtn').click(() => this.sendTestMessage());

        // Табы
        $('.tab').click((e) => this.switchTab(e.target));

        // Экспорт
        $('#exportJsonBtn').click(() => this.exportData('json'));
        $('#exportCsvBtn').click(() => this.exportData('csv'));

        // Управление конфигурацией
        $('#saveConfigBtn').click(() => this.saveSignalConfig());
        $('#loadConfigBtn').click(() => this.loadSignalConfig());
        $('#exportConfigBtn').click(() => this.exportSignalConfig());

        // Изменение временного окна и типа времени
        $('#timeWindowSelect').change(() => this.updateCharts());
        $('#timeTypeSelect').change(() => {
            this.useRealTime = $('#timeTypeSelect').val() === 'real';
            this.updateCharts();
        });

        // Выбор каналов
        $('#channelSelect0').change(() => this.updateSelectedChannels());
        $('#channelSelect1').change(() => this.updateSelectedChannels());

        // Модальное окно
        $('#saveSignalBtn').click(() => this.addSignal());
        $('#cancelSignalBtn').click(() => this.hideAddSignalModal());
        $('#refreshIdsModalBtn').click(() => this.loadAvailableIDs());

        // Обновление списка ID
        $('#refreshIdsBtn').click(() => this.loadAvailableIDs());

        // Автоматически выбираем канал 1
        $(document).ready(() => {
            $('#channelSelect0').prop('checked', false);
            $('#channelSelect1').prop('checked', true);
            this.updateSelectedChannels();
        });

        // Автообновление
        this.startAutoUpdate();
    }

    updateSelectedChannels() {
        const channels = [];
        if ($('#channelSelect0').is(':checked')) channels.push(0);
        if ($('#channelSelect1').is(':checked')) channels.push(1);
        this.selectedChannels = channels;
        console.log('Выбранные каналы:', this.selectedChannels);
    }

    async scanDevices() {
        try {
            const response = await fetch('/api/scan_devices');
            const data = await response.json();

            if (data.status === 'success') {
                this.showNotification(`Найдено устройств: ${data.available_channels.length}`, 'success');
            } else {
                this.showNotification('Ошибка сканирования: ' + data.error, 'error');
            }
        } catch (error) {
            this.showNotification('Ошибка сканирования: ' + error, 'error');
        }
    }

    async connect() {
        const baudRate = $('#baudRateSelect').val();

        // Определяем выбранный канал
        let channel = 0; // По умолчанию канал 1

        // Проверяем чекбоксы
        if ($('#channelSelect0').is(':checked')) {
            channel = 0;
        } else if ($('#channelSelect1').is(':checked')) {
            channel = 1;
        }

        console.log(`Подключение к каналу ${channel}...`);

        try {
            const response = await fetch('/api/connect', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    channel: channel,  // Единственное число!
                    baud_rate: parseInt(baudRate)
                })
            });

            const data = await response.json();
            console.log('Ответ подключения:', data);

            if (data.status === 'connected') {
                this.isConnected = true;
                this.updateStatus();

                // Используем showNotification если есть, иначе alert
                if (typeof showNotification === 'function') {
                    showNotification(`✅ Успешно подключено к каналу ${channel}!`, 'success');
                } else {
                    alert(`✅ Успешно подключено к каналу ${channel}!`);
                }

                // Начинаем мониторинг
                this.startIDDiscovery();
            } else {
                const errorMsg = data.message || 'Неизвестная ошибка';
                if (typeof showNotification === 'function') {
                    showNotification('❌ ' + errorMsg, 'error');
                } else {
                    alert('❌ ' + errorMsg);
                }
            }
        } catch (error) {
            console.error('Ошибка подключения:', error);
            if (typeof showNotification === 'function') {
                showNotification('❌ Ошибка подключения: ' + error, 'error');
            } else {
                alert('❌ Ошибка подключения: ' + error);
            }
        }
    }

    async disconnect() {
        try {
            const response = await fetch('/api/disconnect', {
                method: 'POST'
            });

            const data = await response.json();

            if (data.status === 'disconnected') {
                this.isConnected = false;
                this.updateStatus();
                this.showNotification('✅ Успешно отключено! Сообщения сохранены в файл.', 'success');

                // Останавливаем автообновление
                if (this.autoRefreshInterval) {
                    clearInterval(this.autoRefreshInterval);
                }
            }
        } catch (error) {
            this.showNotification('❌ Ошибка отключения: ' + error, 'error');
        }
    }

    async saveLogs() {
        try {
            const response = await fetch('/api/save_logs', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                this.showNotification('✅ Логи сохранены в файл', 'success');
            } else {
                this.showNotification('❌ Ошибка сохранения логов: ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('❌ Ошибка сохранения логов: ' + error, 'error');
        }
    }

    async clearMessages() {
        try {
            await fetch('/api/messages/clear', {
                method: 'POST'
            });
            this.updateMessages();
            this.showNotification('Сообщения очищены', 'success');
        } catch (error) {
            console.error('Ошибка очистки:', error);
            this.showNotification('Ошибка очистки сообщений', 'error');
        }
    }

    async sendCustomMessage() {
        const canId = $('#sendIdInput').val();
        const dataHex = $('#sendDataInput').val();
        const isExtended = $('#extendedFrameCheck').is(':checked');
        const isRtr = $('#rtrFrameCheck').is(':checked');
        const channel = $('#sendChannelSelect').val();

        if (!canId) {
            this.showNotification('❌ Введите CAN ID', 'error');
            return;
        }

        if (!channel) {
            this.showNotification('❌ Выберите канал для отправки', 'error');
            return;
        }

        let dataBytes = [];
        if (dataHex.trim()) {
            try {
                dataBytes = dataHex.trim().split(/\s+/).map(byte => parseInt(byte, 16));
            } catch (e) {
                this.showNotification('❌ Ошибка в формате данных. Используйте hex байты через пробел.', 'error');
                return;
            }
        }

        try {
            const response = await fetch('/api/send_message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    id: parseInt(canId, 16),
                    data: dataBytes,
                    extended: isExtended,
                    rtr: isRtr,
                    channel: parseInt(channel)
                })
            });

            const data = await response.json();
            if (data.status === 'success') {
                this.showNotification('✅ Сообщение отправлено', 'success');
            } else {
                this.showNotification('❌ ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('❌ Ошибка отправки: ' + error, 'error');
        }
    }

    async sendTestMessage() {
        const channel = $('#sendChannelSelect').val();

        if (!channel) {
            this.showNotification('❌ Выберите канал для отправки', 'error');
            return;
        }

        $('#sendIdInput').val('123');
        $('#sendDataInput').val('01 02 03 04 05 06 07 08');
        $('#extendedFrameCheck').prop('checked', false);
        $('#rtrFrameCheck').prop('checked', false);

        try {
            const response = await fetch('/api/send_test_message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    channel: parseInt(channel)
                })
            });

            const data = await response.json();
            if (data.status === 'success') {
                this.showNotification('✅ Тестовое сообщение отправлено', 'success');
            } else {
                this.showNotification('❌ ' + data.message, 'error');
            }
        } catch (error) {
            this.showNotification('❌ Ошибка отправки: ' + error, 'error');
        }
    }

    showNotification(message, type = 'info') {
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else {
            console.log(`${type}: ${message}`);
        }
    }

    async updateStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();

            this.isConnected = data.connected;
            this.messageCount = data.message_count;

            const indicator = $('#statusIndicator');
            const statusText = $('#statusText');
            const messageCount = $('#messageCount');
            const connectBtn = $('#connectBtn');
            const disconnectBtn = $('#disconnectBtn');

            if (this.isConnected) {
                indicator.removeClass('status-disconnected').addClass('status-connected');
                statusText.text('Подключено (CH1)');
                connectBtn.prop('disabled', true);
                disconnectBtn.prop('disabled', false);
            } else {
                indicator.removeClass('status-connected').addClass('status-disconnected');
                statusText.text('Отключено');
                connectBtn.prop('disabled', false);
                disconnectBtn.prop('disabled', true);
            }

            messageCount.text(`Сообщений: ${this.messageCount}`);

        } catch (error) {
            console.error('Ошибка обновления статуса:', error);
        }
    }

    async updateMessages() {
        try {
            const response = await fetch('/api/messages?limit=50');
            const messages = await response.json();

            const container = $('#messagesContainer');

            // Очищаем только если есть сообщения
            if (messages.length > 0) {
                container.empty();
            }

            // Добавляем сообщения в конец таблицы
            messages.reverse().forEach(msg => {
                const messageElement = this.createMessageElement(msg);
                container.append(messageElement);

                // Сохраняем информацию об ID
                if (msg.id_hex) {
                    const now = new Date();
                    this.discoveredIDs.set(msg.id_hex, {
                        id: msg.id_hex,
                        channel: msg.channel || 1,
                        lastSeen: now,
                        frameType: msg.frame_type,
                        dataLength: msg.length,
                        dataSample: msg.data_hex,
                        count: (this.discoveredIDs.get(msg.id_hex)?.count || 0) + 1
                    });
                }
            });

            // Обновляем список ID если есть новые
            if (messages.length > 0) {
                this.updateIDSelect();
            }

        } catch (error) {
            console.error('Ошибка обновления сообщений:', error);
        }
    }

    createMessageElement(message) {
        const channel = message.channel || 0;
        const channelClass = channel === 0 ? 'channel-0' : 'channel-1';
        const channelText = `CH${channel}`;

        // Парсим байты данных
        const dataBytes = message.data || [];
        let dataHex = message.data_hex || '';

        // Формируем подробное представление байтов
        let byteDetails = '';
        for (let i = 0; i < dataBytes.length; i++) {
            const hex = dataBytes[i].toString(16).padStart(2, '0').toUpperCase();
            const dec = dataBytes[i];
            byteDetails += `<span class="byte-item" title="Byte ${i}: 0x${hex} (${dec})">${hex}</span>`;
            if (i < dataBytes.length - 1) {
                byteDetails += ' ';
            }
        }

        // Парсим float значения из всех возможных комбинаций
        let floatValues = '';
        if (dataBytes.length >= 4) {
            // Пробуем парсить float из разных позиций
            for (let start = 0; start <= dataBytes.length - 4; start++) {
                try {
                    const bytes = new Uint8Array(dataBytes.slice(start, start + 4));
                    const dataView = new DataView(bytes.buffer);
                    const floatValue = dataView.getFloat32(0, true); // little endian

                    if (!isNaN(floatValue) && isFinite(floatValue)) {
                        floatValues += `
                            <div class="float-item">
                                <span class="float-label">Float[${start}-${start + 3}]:</span>
                                <span class="float-value">${floatValue.toFixed(6)}</span>
                            </div>
                        `;
                    }
                } catch (e) {
                    // Игнорируем ошибки парсинга
                }
            }
        }

        // Основные сигналы
        let signalsHtml = '';
        if (message.signals) {
            for (const [key, value] of Object.entries(message.signals)) {
                if (value !== null && value !== undefined) {
                    let displayValue = value;
                    if (typeof value === 'number') {
                        displayValue = value.toFixed(6);
                    }
                    signalsHtml += `<span class="signal-item">${key}: ${displayValue}</span>`;
                }
            }
        }

        return `
            <tr class="message-row">
                <td class="channel-cell ${channelClass}">${channelText}</td>
                <td class="id-cell">${message.id_hex}</td>
                <td class="type-cell">${message.frame_type}</td>
                <td class="length-cell">${message.length}</td>
                <td class="data-cell">
                    <div class="data-hex">${byteDetails}</div>
                    ${floatValues ? `<div class="float-values">${floatValues}</div>` : ''}
                </td>
                <td class="time-cell">${message.timestamp_str}</td>
                <td class="signals-cell">${signalsHtml}</td>
            </tr>
        `;
    }

    startIDDiscovery() {
        // Обновляем ID каждые 3 секунды
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }

        this.autoRefreshInterval = setInterval(() => {
            if (this.isConnected) {
                this.loadAvailableIDs();
                this.renderDiscoveredIDs();
            }
        }, 3000);
    }

    async loadAvailableIDs() {
        try {
            const response = await fetch('/api/available_ids');
            const ids = await response.json();

            // Обновляем список ID
            ids.forEach(id => {
                this.availableIDs.add(id);
            });

            // Обновляем выпадающий список
            this.updateIDSelect();

            // Обновляем статус
            $('#idsStatus').text(`Обнаружено ID: ${this.availableIDs.size}`);

        } catch (error) {
            console.error('Ошибка загрузки ID:', error);
            $('#idsStatus').text('Ошибка загрузки ID');
        }
    }

    updateIDSelect() {
        const select = $('#messageIdSelect');
        const currentValue = select.val();

        select.empty();
        select.append('<option value="">Выберите CAN ID</option>');

        // Сортируем ID
        const sortedIDs = Array.from(this.availableIDs).sort((a, b) => {
            try {
                const aNum = parseInt(a.replace('0x', ''), 16);
                const bNum = parseInt(b.replace('0x', ''), 16);
                return aNum - bNum;
            } catch {
                return a.localeCompare(b);
            }
        });

        sortedIDs.forEach(id => {
            const info = this.discoveredIDs.get(id);
            let displayText = id;

            if (info) {
                const sample = info.dataSample ? info.dataSample.substring(0, 20) + '...' : '';
                displayText = `${id} (${info.frameType}, ${info.dataLength}б, ${info.count || 0} сообщ.)`;
            }

            select.append(`<option value="${id}">${displayText}</option>`);
        });

        if (currentValue && this.availableIDs.has(currentValue)) {
            select.val(currentValue);
        }
    }

    renderDiscoveredIDs() {
        if (this.availableIDs.size === 0) return;

        if ($('#discoveryPanel').length === 0 && this.isConnected) {
            const discoveryPanel = $(`
                <div id="discoveryPanel" class="card" style="margin-top: 20px; border: 2px solid var(--secondary-color);">
                    <h4>🎯 Обнаруженные ID на канале 1</h4>
                    <div style="color: #666; font-size: 13px; margin-bottom: 10px;">
                        Кликните на ID чтобы добавить в графики
                    </div>
                    <div id="discoveredIDsList" style="max-height: 200px; overflow-y: auto;">
                        <!-- ID будут здесь -->
                    </div>
                </div>
            `);

            $('#messages-tab .card').after(discoveryPanel);
        }

        const container = $('#discoveredIDsList');
        if (!container.length) return;

        container.empty();

        const sortedIDs = Array.from(this.availableIDs).sort((a, b) => {
            try {
                const aNum = parseInt(a.replace('0x', ''), 16);
                const bNum = parseInt(b.replace('0x', ''), 16);
                return aNum - bNum;
            } catch {
                return a.localeCompare(b);
            }
        });

        sortedIDs.forEach(id => {
            const info = this.discoveredIDs.get(id);
            const isSelected = Array.from(this.selectedSignals.keys())
                .some(key => key.startsWith(`${id}_`));

            const timeAgo = info?.lastSeen ?
                Math.round((new Date() - new Date(info.lastSeen)) / 1000) : '?';

            const idElement = $(`
                <div class="discovered-id-item" 
                     style="margin: 5px 0; padding: 8px; background: ${isSelected ? '#e8f5e9' : '#f5f5f5'}; 
                            border-radius: 5px; display: flex; justify-content: space-between; 
                            align-items: center; border-left: 4px solid ${isSelected ? '#27ae60' : '#3498db'};
                            cursor: pointer;" 
                     data-id="${id}"
                     title="Кликните чтобы добавить в графики">
                    <div>
                        <strong style="color: ${isSelected ? '#27ae60' : '#2c3e50'}">${id}</strong>
                        <small style="color: #666; margin-left: 10px;">
                            ${info?.frameType || '?'}, ${info?.dataLength || '?'} байт
                            ${info?.count ? `, ${info.count} сообщ.` : ''}
                            ${timeAgo !== '?' ? `, ${timeAgo}с назад` : ''}
                        </small>
                    </div>
                    <div>
                        <button class="btn-small btn-${isSelected ? 'warning' : 'success'}" 
                                data-id="${id}" 
                                style="margin-right: 5px;">
                            ${isSelected ? '✏️' : '➕'}
                        </button>
                    </div>
                </div>
            `);

            idElement.click((e) => {
                if (!$(e.target).is('button')) {
                    this.addSignalForID(id);
                }
            });

            idElement.find('button').click((e) => {
                e.stopPropagation();
                this.addSignalForID(id);
            });

            container.append(idElement);
        });
    }

    addSignalForID(id) {
        $('#messageIdSelect').val(id);
        $('#signalChannelSelect').val('1');

        // Автопредложение имени
        const idNum = parseInt(id.replace('0x', ''), 16);
        const suggestedNames = {
            0x181: 'Temperature', 0x182: 'Pressure', 0x183: 'Voltage',
            0x184: 'Current', 0x185: 'RPM', 0x186: 'Speed',
            0x187: 'Torque', 0x188: 'Position', 0x189: 'Acceleration',
            0x18A: 'Angle', 0x18B: 'Flow', 0x18C: 'Level',
            0x100: 'EngineTemp', 0x101: 'OilPressure', 0x102: 'FuelLevel'
        };

        const suggestedName = suggestedNames[idNum] || 'Value';
        $('#signalNameInput').val(suggestedName);

        // Автонастройка для первых 4 байт как float
        $('#dataTypeSelect').val('float32');
        $('#byteOrderSelect').val('little_endian');
        $('#startByteInput').val('0');
        $('#dataLengthInput').val('4');

        this.showAddSignalModal();
    }

    showAddSignalModal() {
        $('#addSignalModal').show();
    }

    hideAddSignalModal() {
        $('#addSignalModal').hide();
    }

    async addSignal() {
        const messageId = $('#messageIdSelect').val();
        const signalName = $('#signalNameInput').val();
        const firstBytes = $('#firstBytesInput').val() || '';
        const dataType = $('#dataTypeSelect').val();
        const byteOrder = $('#byteOrderSelect').val();
        const startByte = parseInt($('#startByteInput').val());
        const dataLength = parseInt($('#dataLengthInput').val());
        const scale = parseFloat($('#scaleInput').val());
        const offset = parseFloat($('#offsetInput').val());
        const channel = $('#signalChannelSelect').val();

        if (!messageId || !signalName) {
            this.showNotification('❌ Заполните CAN ID и название сигнала', 'error');
            return;
        }

        if (!channel) {
            this.showNotification('❌ Выберите канал для сигнала', 'error');
            return;
        }

        if (firstBytes && !/^[0-9A-Fa-f]{8}$/.test(firstBytes)) {
            this.showNotification('❌ Первые 4 байта должны быть 8 шестнадцатеричных символов', 'error');
            return;
        }

        const parserConfig = {
            type: dataType,
            byte_order: byteOrder,
            start_byte: startByte,
            length: dataLength,
            scale: scale,
            offset: offset,
            channel: channel
        };

        if (firstBytes) {
            parserConfig.first_bytes = firstBytes.toUpperCase();
        }

        try {
            const response = await fetch('/api/select_signal', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message_id: messageId,
                    signal_name: signalName,
                    parser_config: parserConfig
                })
            });

            const data = await response.json();

            if (data.status === 'success') {
                this.selectedSignals.set(data.signal_key, parserConfig);
                this.renderSelectedSignalsList();
                this.hideAddSignalModal();

                // Автоматически создаем график
                this.createChartContainer(data.signal_key);
                this.updateCharts();

                // Сбрасываем форму
                $('#signalNameInput').val('');
                $('#firstBytesInput').val('');
                $('#scaleInput').val('1');
                $('#offsetInput').val('0');
                $('#startByteInput').val('0');
                $('#dataLengthInput').val('4');

                this.showNotification(`✅ Сигнал добавлен: ${messageId} - ${signalName}`);
            }
        } catch (error) {
            console.error('Ошибка добавления сигнала:', error);
            this.showNotification('❌ Ошибка добавления сигнала: ' + error, 'error');
        }
    }

    async removeSignal(signalKey) {
        try {
            await fetch('/api/remove_signal', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    signal_key: signalKey
                })
            });

            this.selectedSignals.delete(signalKey);
            this.renderSelectedSignalsList();

            this.removeChart(signalKey);
        } catch (error) {
            console.error('Ошибка удаления сигнала:', error);
        }
    }

    removeChart(signalKey) {
        if (this.charts.has(signalKey)) {
            this.charts.get(signalKey).destroy();
            this.charts.delete(signalKey);
            $(`#chart-${signalKey}`).remove();
        }
    }

    renderSelectedSignalsList() {
        const container = $('#selectedSignalsList');
        container.empty();

        if (this.selectedSignals.size === 0) {
            container.append('<div class="no-signals">Нет выбранных сигналов</div>');
            return;
        }

        this.selectedSignals.forEach((config, signalKey) => {
            const parts = signalKey.split('_');
            const messageId = parts[0];

            // Извлекаем имя сигнала
            let signalName = '';
            for (let i = 1; i < parts.length; i++) {
                if (parts[i].startsWith('CH')) {
                    break;
                }
                if (signalName) signalName += '_';
                signalName += parts[i];
            }

            const channel = signalKey.includes('_CH') ?
                signalKey.split('_CH')[1] : (config.channel || '1');

            const firstBytes = config.first_bytes || 'все';
            const dataType = config.type || 'float32';
            const isChartVisible = $(`#chart-${signalKey}`).length > 0;
            const channelColor = channel === '0' ? 'blue' : 'orange';

            const signalElement = $(`
                <div class="selected-signal-item">
                    <div class="signal-info">
                        <div style="display: flex; align-items: center; margin-bottom: 5px;">
                            <span style="color: ${channelColor}; font-weight: bold; margin-right: 8px;">
                                CH${channel}
                            </span>
                            <strong>${messageId}</strong> - ${signalName}
                            <div style="margin-left: auto; display: flex; gap: 5px;">
                                <button class="btn-small btn-info export-plotly" data-signal="${signalKey}" title="Экспорт в Plotly HTML">
                                    📊 Plotly
                                </button>
                                <button class="btn-small btn-success open-chart" data-signal="${signalKey}" title="Открыть отдельно">
                                    ↗️ Открыть
                                </button>
                            </div>
                        </div>
                        <small>
                            Тип: ${dataType}, Байты: ${firstBytes}, 
                            Масштаб: ${config.scale || 1.0}, Смещение: ${config.offset || 0.0}
                        </small>
                    </div>
                    <div>
                        <button class="btn-${isChartVisible ? 'warning' : 'success'} btn-small toggle-chart" data-signal="${signalKey}">
                            ${isChartVisible ? '📊' : '📈'}
                        </button>
                        <button class="btn-danger btn-small remove-signal" data-signal="${signalKey}">✕</button>
                    </div>
                </div>
            `);

            signalElement.find('.remove-signal').click(() => this.removeSignal(signalKey));
            signalElement.find('.toggle-chart').click(() => this.toggleChart(signalKey));
            signalElement.find('.export-plotly').click(() => this.exportToPlotly(signalKey));
            signalElement.find('.open-chart').click(() => this.openChartInNewWindow(signalKey));
            container.append(signalElement);
        });
    }

    toggleChart(signalKey) {
        const chartContainer = $(`#chart-${signalKey}`);
        if (chartContainer.length) {
            chartContainer.remove();
            this.removeChart(signalKey);
        } else {
            this.createChartContainer(signalKey);
        }
        this.renderSelectedSignalsList();
        this.updateCharts();
    }

    async exportToPlotly(signalKey) {
        try {
            const timeWindow = $('#timeWindowSelect').val();
            const realTimeParam = this.useRealTime ? 'true' : 'false';
            const response = await fetch(`/api/chart_data?time_window=${timeWindow}&real_time=${realTimeParam}`);
            const chartData = await response.json();

            if (chartData[signalKey]) {
                const data = chartData[signalKey];
                const config = this.selectedSignals.get(signalKey);

                // Создаем HTML с Plotly графиком
                const plotlyHtml = this.generatePlotlyHtml(signalKey, data, config);

                // Создаем и скачиваем файл
                const blob = new Blob([plotlyHtml], { type: 'text/html' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `can_plotly_${signalKey}_${Date.now()}.html`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this.showNotification('✅ Plotly HTML экспортирован', 'success');
            } else {
                this.showNotification('❌ Нет данных для экспорта', 'error');
            }
        } catch (error) {
            console.error('Ошибка экспорта в Plotly:', error);
            this.showNotification('❌ Ошибка экспорта: ' + error, 'error');
        }
    }

    generatePlotlyHtml(signalKey, data, config) {
        const parts = signalKey.split('_');
        const messageId = parts[0];

        let signalName = '';
        for (let i = 1; i < parts.length; i++) {
            if (parts[i].startsWith('CH')) break;
            if (signalName) signalName += '_';
            signalName += parts[i];
        }

        const channel = signalKey.includes('_CH') ?
            signalKey.split('_CH')[1] : (config.channel || '1');

        // Подготавливаем данные для Plotly
        const xValues = this.useRealTime ?
            data.timestamps.map(t => new Date(t * 1000).toISOString()) :
            data.timestamps;
        const yValues = data.values;

        return `
<!DOCTYPE html>
<html>
<head>
    <title>CAN Monitor - ${messageId} - ${signalName}</title>
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #3498db; }
        .chart-container { width: 100%; height: 600px; }
        .info-panel { background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px; }
        .info-item { margin: 5px 0; }
        .timestamp { color: #666; font-size: 12px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 CAN Monitor - График сигнала</h1>
            <h2>${messageId} - ${signalName} (Канал ${channel})</h2>
        </div>
        
        <div class="info-panel">
            <div class="info-item"><strong>CAN ID:</strong> ${messageId}</div>
            <div class="info-item"><strong>Сигнал:</strong> ${signalName}</div>
            <div class="info-item"><strong>Канал:</strong> ${channel}</div>
            <div class="info-item"><strong>Тип данных:</strong> ${config.type || 'float32'}</div>
            <div class="info-item"><strong>Первые байты:</strong> ${config.first_bytes || 'все'}</div>
            <div class="info-item"><strong>Масштаб:</strong> ${config.scale || 1.0}</div>
            <div class="info-item"><strong>Смещение:</strong> ${config.offset || 0.0}</div>
            <div class="info-item"><strong>Точек данных:</strong> ${yValues.length}</div>
            <div class="info-item"><strong>Временное окно:</strong> ${$('#timeWindowSelect').val()} сек</div>
        </div>
        
        <div id="plotly-chart" class="chart-container"></div>
        
        <div class="timestamp">
            Создано: ${new Date().toLocaleString()}<br>
            Режим времени: ${this.useRealTime ? 'Реальное время' : 'Относительное время'}
        </div>
    </div>
    
    <script>
        // Данные для графика
        const trace = {
            x: ${JSON.stringify(xValues)},
            y: ${JSON.stringify(yValues)},
            type: 'scatter',
            mode: 'lines',
            name: '${signalName}',
            line: {
                color: ${channel === '0' ? "'#3498db'" : "'#e74c3c'"},
                width: 2
            },
            fill: 'tozeroy',
            fillcolor: ${channel === '0' ? "'rgba(52, 152, 219, 0.2)'" : "'rgba(231, 76, 60, 0.2)'"}
        };
        
        const layout = {
            title: '${messageId} - ${signalName} (Канал ${channel})',
            xaxis: {
                title: ${this.useRealTime ? "'Время'" : "'Время (секунды)'"},
                gridcolor: '#f0f0f0'
            },
            yaxis: {
                title: 'Значение',
                gridcolor: '#f0f0f0'
            },
            plot_bgcolor: 'white',
            paper_bgcolor: 'white',
            hovermode: 'x unified',
            showlegend: true,
            legend: {
                x: 0.01,
                y: 0.99,
                bgcolor: 'rgba(255, 255, 255, 0.8)'
            }
        };
        
        const config = {
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
            modeBarButtonsToAdd: ['drawline', 'drawopenpath', 'eraseshape'],
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
            scrollZoom: true
        };
        
        Plotly.newPlot('plotly-chart', [trace], layout, config);
        
        // Добавляем обновление данных в реальном времени
        let autoUpdate = true;
        
        function updateData() {
            if (!autoUpdate) return;
            
            fetch('/api/chart_data_single?signal_key=${signalKey}&time_window=${$('#timeWindowSelect').val()}&real_time=${this.useRealTime ? 'true' : 'false'}')
                .then(response => response.json())
                .then(newData => {
                    if (newData.values && newData.values.length > 0) {
                        const update = {
                            x: [${this.useRealTime ?
                'newData.timestamps.map(t => new Date(t * 1000).toISOString())' :
                'newData.timestamps'}],
                            y: [newData.values]
                        };
                        Plotly.react('plotly-chart', [trace], layout, config);
                    }
                })
                .catch(error => console.error('Ошибка обновления:', error));
        }
        
        // Обновляем каждые 2 секунды
        setInterval(updateData, 2000);
        
        // Кнопки управления
        document.addEventListener('keydown', (e) => {
            if (e.key === ' ') {
                autoUpdate = !autoUpdate;
                console.log('Автообновление:', autoUpdate ? 'включено' : 'выключено');
            }
        });
        
        console.log('График загружен. Нажмите пробел для паузы/продолжения.');
    </script>
</body>
</html>`;
    }

    async openChartInNewWindow(signalKey) {
        try {
            const timeWindow = $('#timeWindowSelect').val();
            const realTimeParam = this.useRealTime ? 'true' : 'false';

            // Получаем данные для графика
            const response = await fetch(`/api/chart_data_single?signal_key=${signalKey}&time_window=${timeWindow}&real_time=${realTimeParam}`);
            const chartData = await response.json();

            if (chartData) {
                const config = this.selectedSignals.get(signalKey);
                const parts = signalKey.split('_');
                const messageId = parts[0];

                let signalName = '';
                for (let i = 1; i < parts.length; i++) {
                    if (parts[i].startsWith('CH')) break;
                    if (signalName) signalName += '_';
                    signalName += parts[i];
                }

                // Создаем простой HTML с графиком
                const simpleHtml = `
<!DOCTYPE html>
<html>
<head>
    <title>CAN Chart - ${messageId}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial; margin: 0; padding: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .chart-wrapper { width: 100%; height: 500px; }
        .info { background: #f8f9fa; padding: 15px; margin-bottom: 20px; border-radius: 5px; border-left: 4px solid #3498db; }
        .controls { margin: 20px 0; display: flex; gap: 10px; }
        button { padding: 10px 20px; background: #3498db; color: white; border: none; border-radius: 5px; cursor: pointer; }
        button:hover { background: #2980b9; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 ${messageId} - ${signalName}</h1>
        <div class="info">
            <p><strong>CAN ID:</strong> ${messageId}</p>
            <p><strong>Сигнал:</strong> ${signalName}</p>
            <p><strong>Канал:</strong> ${config.channel || '1'}</p>
            <p><strong>Точек данных:</strong> ${chartData.values ? chartData.values.length : 0}</p>
            <p><strong>Создано:</strong> ${new Date().toLocaleString()}</p>
        </div>
        <div class="chart-wrapper">
            <canvas id="mainChart"></canvas>
        </div>
        <div class="controls">
            <button onclick="updateData()">🔄 Обновить</button>
            <button onclick="window.close()">✕ Закрыть</button>
            <button onclick="exportChart()">💾 Сохранить</button>
        </div>
    </div>
    <script>
        let chart;
        let autoUpdate = true;
        
        function initChart(data) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            
            if (chart) {
                chart.destroy();
            }
            
            const timestamps = data.timestamps || [];
            const values = data.values || [];
            
            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: timestamps.map(t => {
                        const date = new Date(t * 1000);
                        return date.toLocaleTimeString();
                    }),
                    datasets: [{
                        label: '${signalName}',
                        data: values,
                        borderColor: 'rgb(52, 152, 219)',
                        backgroundColor: 'rgba(52, 152, 219, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Время'
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Значение'
                            },
                            beginAtZero: false
                        }
                    }
                }
            });
        }
        
        async function loadData() {
            try {
                const response = await fetch('/api/chart_data_single?signal_key=${signalKey}&time_window=${timeWindow}&real_time=${realTimeParam}');
                const data = await response.json();
                initChart(data);
            } catch (error) {
                console.error('Ошибка загрузки:', error);
            }
        }
        
        function updateData() {
            loadData();
        }
        
        function exportChart() {
            const canvas = document.getElementById('mainChart');
            const link = document.createElement('a');
            link.download = 'can_chart_${messageId}_${Date.now()}.png';
            link.href = canvas.toDataURL('image/png');
            link.click();
        }
        
        // Инициализация при загрузке
        initChart(${JSON.stringify(chartData)});
        
        // Автообновление каждые 5 секунд
        setInterval(() => {
            if (autoUpdate) {
                loadData();
            }
        }, 5000);
        
        // Остановка автообновления при неактивном окне
        document.addEventListener('visibilitychange', () => {
            autoUpdate = !document.hidden;
        });
    </script>
</body>
</html>`;

                const newWindow = window.open('', '_blank', 'width=1200,height=800,menubar=no,toolbar=no,location=no');
                newWindow.document.write(simpleHtml);
                newWindow.document.close();

                this.showNotification('✅ График открыт в новом окне', 'success');
            } else {
                this.showNotification('❌ Нет данных для графика', 'error');
            }
        } catch (error) {
            console.error('Ошибка открытия графика:', error);
            this.showNotification('❌ Ошибка открытия графика', 'error');
        }
    }

    createChartContainer(signalKey) {
        if ($(`#chart-${signalKey}`).length) {
            return;
        }

        const parts = signalKey.split('_');
        const messageId = parts[0];

        // Извлекаем имя сигнала
        let signalName = '';
        for (let i = 1; i < parts.length; i++) {
            if (parts[i].startsWith('CH')) {
                break;
            }
            if (signalName) signalName += '_';
            signalName += parts[i];
        }

        const channel = signalKey.includes('_CH') ?
            signalKey.split('_CH')[1] : '1';

        const config = this.selectedSignals.get(signalKey);
        const firstBytes = config.first_bytes || 'все';
        const dataType = config.type || 'float32';
        const channelColor = channel === '0' ? 'blue' : 'orange';

        const chartHtml = `
            <div class="chart-card" id="chart-${signalKey}">
                <div class="chart-header">
                    <h4 style="display: flex; align-items: center;">
                        <span style="color: ${channelColor}; margin-right: 8px; font-weight: bold;">CH${channel}</span>
                        ${messageId} - ${signalName} [${firstBytes}]
                    </h4>
                    <div>
                        <button class="btn-small btn-info export-plotly-inline" data-signal="${signalKey}" title="Экспорт в Plotly HTML">
                            📊 Plotly
                        </button>
                        <button class="btn-small btn-success open-chart-inline" data-signal="${signalKey}" title="Открыть отдельно">
                            ↗️ Открыть
                        </button>
                        <button class="btn-danger btn-small close-chart" data-signal="${signalKey}">✕</button>
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="chartCanvas-${signalKey}"></canvas>
                </div>
                <div class="chart-footer">
                    <small>
                        Канал: ${channel} | Тип: ${dataType} | 
                        Масштаб: ${config.scale || 1.0} | Смещение: ${config.offset || 0.0} | 
                        Байты: ${config.start_byte || 0}-${(parseInt(config.start_byte || 0) + parseInt(config.length || 4) - 1)}
                    </small>
                </div>
            </div>
        `;

        $('#chartsContainer').append(chartHtml);

        $(`#chart-${signalKey} .close-chart`).click(() => {
            this.removeChart(signalKey);
            $(`#chart-${signalKey}`).remove();
            this.renderSelectedSignalsList();
        });

        $(`#chart-${signalKey} .export-plotly-inline`).click(() => this.exportToPlotly(signalKey));
        $(`#chart-${signalKey} .open-chart-inline`).click(() => this.openChartInNewWindow(signalKey));
    }

    async saveSignalConfig() {
        try {
            const response = await fetch('/api/save_signal_config', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                this.showNotification('✅ Конфигурация сигналов сохранена в файл', 'success');
            } else {
                this.showNotification('❌ Ошибка сохранения: ' + data.message, 'error');
            }
        } catch (error) {
            console.error('Ошибка сохранения конфигурации:', error);
            this.showNotification('❌ Ошибка сохранения конфигурации: ' + error, 'error');
        }
    }

    async loadSignalConfig() {
        try {
            const response = await fetch('/api/load_signal_config', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                this.selectedSignals = new Map(Object.entries(data.signals));
                this.renderSelectedSignalsList();

                // Удаляем все старые графики
                this.charts.forEach((chart, signalKey) => {
                    chart.destroy();
                });
                this.charts.clear();
                $('#chartsContainer').empty();

                // Создаем графики для всех загруженных сигналов
                this.selectedSignals.forEach((config, signalKey) => {
                    this.createChartContainer(signalKey);
                });

                this.updateCharts();
                this.showNotification('✅ Конфигурация сигналов загружена из файла', 'success');
            } else {
                this.showNotification('❌ Ошибка загрузки: ' + data.message, 'error');
            }
        } catch (error) {
            console.error('Ошибка загрузки конфигурации:', error);
            this.showNotification('❌ Ошибка загрузки конфигурации: ' + error, 'error');
        }
    }

    async exportSignalConfig() {
        try {
            const response = await fetch('/api/export_signal_config');
            const blob = await response.blob();

            this.downloadFile(blob, 'can_signals_config.json', 'application/json');
            this.showNotification('✅ Конфигурация сигналов экспортирована в файл', 'success');
        } catch (error) {
            console.error('Ошибка экспорта конфигурации:', error);
            this.showNotification('❌ Ошибка экспорта конфигурации: ' + error, 'error');
        }
    }

    async updateCharts() {
        try {
            const timeWindow = $('#timeWindowSelect').val();
            const realTimeParam = this.useRealTime ? 'true' : 'false';
            const response = await fetch(`/api/chart_data?time_window=${timeWindow}&real_time=${realTimeParam}`);
            const chartData = await response.json();

            this.renderCharts(chartData);
        } catch (error) {
            console.error('Ошибка обновления графиков:', error);
        }
    }

    renderCharts(chartData) {
        this.selectedSignals.forEach((config, signalKey) => {
            if (chartData && chartData[signalKey] && $(`#chart-${signalKey}`).length) {
                this.renderSingleChart(signalKey, chartData[signalKey], config);
            }
        });
    }

    renderSingleChart(signalKey, data, config) {
        const canvasId = `chartCanvas-${signalKey}`;
        const canvasElement = document.getElementById(canvasId);

        if (!canvasElement) {
            console.warn(`Canvas element not found: ${canvasId}`);
            return;
        }

        const ctx = canvasElement.getContext('2d');

        if (this.charts.has(signalKey)) {
            this.charts.get(signalKey).destroy();
        }

        const channel = config.channel || '1';
        const channelColor = channel === '0' ? 'rgba(54, 162, 235, 0.8)' : 'rgba(255, 159, 64, 0.8)';
        const backgroundColor = channel === '0' ? 'rgba(54, 162, 235, 0.2)' : 'rgba(255, 159, 64, 0.2)';

        if (!data || !data.values || !data.timestamps) {
            console.warn(`Нет данных для сигнала ${signalKey}`);
            return;
        }

        const chartDataPoints = data.values.map((value, idx) => ({
            x: data.timestamps[idx],
            y: value
        }));

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: data.label || signalKey,
                    data: chartDataPoints,
                    borderColor: channelColor,
                    backgroundColor: backgroundColor,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.1,
                    pointRadius: 2,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'linear',
                        title: {
                            display: true,
                            text: this.useRealTime ? 'Время' : 'Время (секунды)'
                        },
                        ticks: {
                            callback: (value) => {
                                if (this.useRealTime) {
                                    const date = new Date(value * 1000);
                                    return date.toLocaleTimeString();
                                } else {
                                    return value.toFixed(1) + 'с';
                                }
                            }
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'Значение'
                        },
                        beginAtZero: false,
                        grace: '5%'
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'nearest',
                        intersect: false,
                        callbacks: {
                            label: (context) => {
                                return `${context.dataset.label}: ${context.parsed.y.toFixed(6)}`;
                            },
                            title: (context) => {
                                if (this.useRealTime) {
                                    const date = new Date(context[0].parsed.x * 1000);
                                    return date.toLocaleString();
                                } else {
                                    return `Время: ${context[0].parsed.x.toFixed(2)}с`;
                                }
                            }
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'nearest'
                }
            }
        });

        this.charts.set(signalKey, chart);
    }

    clearCharts() {
        this.charts.forEach((chart, signalKey) => {
            chart.destroy();
        });
        this.charts.clear();
        $('#chartsContainer').empty();

        this.selectedSignals.forEach((config, signalKey) => {
            this.removeSignal(signalKey);
        });
    }

    async updateStatistics() {
        try {
            const response = await fetch('/api/statistics');
            const stats = await response.json();

            this.renderStatistics(stats);
        } catch (error) {
            console.error('Ошибка обновления статистики:', error);
        }
    }

    renderStatistics(stats) {
        const statsGrid = $('#statisticsGrid');
        statsGrid.empty();

        const mainStats = [
            { label: 'Всего сообщений', value: stats.total_messages },
            { label: 'Сообщений CH0', value: stats.by_channel?.['0'] || 0 },
            { label: 'Сообщений CH1', value: stats.by_channel?.['1'] || 0 },
            { label: 'STD фреймы', value: stats.by_type?.STD || 0 },
            { label: 'EXT фреймы', value: stats.by_type?.EXT || 0 },
            { label: 'DATA фреймы', value: stats.by_rtr?.DATA || 0 },
            { label: 'RTR фреймы', value: stats.by_rtr?.RTR || 0 }
        ];

        mainStats.forEach(stat => {
            statsGrid.append(`
                <div class="stat-item">
                    <div class="stat-value">${stat.value}</div>
                    <div class="stat-label">${stat.label}</div>
                </div>
            `);
        });

        const idStats = $('#idStatistics');
        idStats.empty();

        if (stats.by_id && Object.keys(stats.by_id).length > 0) {
            idStats.append('<h4 style="margin: 15px 0 10px 0;">Статистика по ID:</h4>');
            for (const [msgId, data] of Object.entries(stats.by_id)) {
                idStats.append(`
                    <div style="margin: 8px 0; padding: 10px; background: #f8f9fa; border-radius: 5px; border-left: 4px solid var(--secondary-color);">
                        <strong>${msgId}</strong>: ${data.count} сообщений 
                        (${data.frequency?.toFixed(1) || 0}/сек)
                        <br><small>Канал: ${data.channel || 'неизвестен'}, Последнее: ${data.last_seen}</small>
                    </div>
                `);
            }
        }
    }

    async exportData(format) {
        try {
            const response = await fetch(`/api/export/messages?format=${format}`);

            if (format === 'json') {
                const data = await response.json();
                this.downloadFile(JSON.stringify(data, null, 2), 'can_messages.json', 'application/json');
            } else if (format === 'csv') {
                const blob = await response.blob();
                this.downloadFile(blob, 'can_messages.csv', 'text/csv');
            }

            this.showNotification(`✅ Данные успешно экспортированы в ${format.toUpperCase()}`, 'success');
        } catch (error) {
            console.error('Ошибка экспорта:', error);
            this.showNotification('❌ Ошибка экспорта данных: ' + error, 'error');
        }
    }

    downloadFile(content, filename, mimeType) {
        const blob = content instanceof Blob ? content : new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    switchTab(tabElement) {
        $('.tab').removeClass('active');
        $('.tab-content').removeClass('active');

        $(tabElement).addClass('active');
        const tabId = $(tabElement).data('tab');
        $(`#${tabId}-tab`).addClass('active');

        if (tabId === 'messages') {
            this.updateMessages();
        } else if (tabId === 'statistics') {
            this.updateStatistics();
        } else if (tabId === 'charts') {
            this.updateCharts();
            if (this.isConnected) {
                this.loadAvailableIDs();
            }
        }
    }

    startAutoUpdate() {
        setInterval(() => {
            this.updateStatus();
        }, 1000);

        setInterval(() => {
            const activeTab = $('.tab.active').data('tab');

            if (activeTab === 'messages') {
                this.updateMessages();
            } else if (activeTab === 'statistics') {
                this.updateStatistics();
            } else if (activeTab === 'charts' && this.selectedSignals.size > 0) {
                this.updateCharts();
            }
        }, 2000);
    }
}

// Инициализация
$(document).ready(() => {
    window.canMonitor = new CANMonitor();
    console.log('CAN Monitor v6 с поддержкой каналов инициализирован');
});