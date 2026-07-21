class CANMonitor {
    constructor() {
        this.isConnected = false;
        this.messageCount = 0;
        this.charts = new Map();
        this.selectedSignals = new Map();
        this.updateInterval = null;
        this.useRealTime = true;
        this.selectedChannels = [1];  // Только канал 1

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
    }

    async scanDevices() {
        try {
            const response = await fetch('/api/scan_devices');
            const data = await response.json();

            if (data.status === 'success') {
                alert(`Найдено устройств: ${data.available_channels.length}`);
            } else {
                alert('Ошибка сканирования: ' + data.error);
            }
        } catch (error) {
            alert('Ошибка сканирования: ' + error);
        }
    }

    async connect() {
        const baudRate = $('#baudRateSelect').val();

        this.updateSelectedChannels();

        if (this.selectedChannels.length === 0) {
            alert('Выберите хотя бы один канал для подключения');
            return;
        }

        try {
            console.log('Подключение к каналу 1...');
            const response = await fetch('/api/connect', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    channels: [1],
                    baud_rate: parseInt(baudRate)
                })
            });

            const data = await response.json();
            console.log('Ответ подключения:', data);

            if (data.status === 'connected') {
                this.isConnected = true;
                this.updateStatus();
                alert('✅ Успешно подключено к каналу 1!\nЧтение ВСЕХ сообщений...');

                // Начинаем мониторинг
                this.startIDDiscovery();
            } else {
                alert('❌ Ошибка подключения: ' + data.message);
            }
        } catch (error) {
            console.error('Ошибка подключения:', error);
            alert('❌ Ошибка подключения: ' + error);
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
                alert('✅ Успешно отключено! Сообщения сохранены в файл.');

                // Останавливаем автообновление
                if (this.autoRefreshInterval) {
                    clearInterval(this.autoRefreshInterval);
                }
            }
        } catch (error) {
            alert('❌ Ошибка отключения: ' + error);
        }
    }

    async saveLogs() {
        try {
            const response = await fetch('/api/save_logs', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('✅ Логи сохранены в файл');
            } else {
                alert('❌ Ошибка сохранения логов: ' + data.message);
            }
        } catch (error) {
            alert('❌ Ошибка сохранения логов: ' + error);
        }
    }

    async clearMessages() {
        try {
            await fetch('/api/messages/clear', {
                method: 'POST'
            });
            this.updateMessages();
        } catch (error) {
            console.error('Ошибка очистки:', error);
        }
    }

    async sendCustomMessage() {
        const canId = $('#sendIdInput').val();
        const dataHex = $('#sendDataInput').val();
        const isExtended = $('#extendedFrameCheck').is(':checked');
        const isRtr = $('#rtrFrameCheck').is(':checked');
        const channel = $('#sendChannelSelect').val();

        if (!canId) {
            alert('❌ Введите CAN ID');
            return;
        }

        if (!channel) {
            alert('❌ Выберите канал для отправки');
            return;
        }

        let dataBytes = [];
        if (dataHex.trim()) {
            try {
                dataBytes = dataHex.trim().split(/\s+/).map(byte => parseInt(byte, 16));
            } catch (e) {
                alert('❌ Ошибка в формате данных. Используйте hex байты через пробел.');
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
            alert('❌ Выберите канал для отправки');
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
        alert(message);
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
            container.empty();

            messages.reverse().forEach(msg => {
                const messageElement = this.createMessageElement(msg);
                container.prepend(messageElement);

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
        } catch (error) {
            console.error('Ошибка обновления сообщений:', error);
        }
    }

    createMessageElement(message) {
        const signalsHtml = Object.entries(message.signals || {})
            .map(([key, value]) => {
                let displayValue = value;
                if (typeof value === 'number') {
                    displayValue = value.toFixed(6);
                }
                return `<span class="signal-item">${key}: ${displayValue}</span>`;
            }).join('');

        const channel = message.channel || 0;
        const channelClass = channel === 0 ? 'channel-0' : 'channel-1';
        const channelText = `CH${channel}`;

        return `
            <div class="message-item">
                <span class="message-channel ${channelClass}">${channelText}</span>
                <span class="message-id">${message.id_hex}</span>
                <span class="message-type">[${message.frame_type}]</span>
                <span class="message-data">${message.data_hex}</span>
                <span>(${message.length} bytes)</span>
                <span>${message.timestamp_str}</span>
                <div>${signalsHtml}</div>
            </div>
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
            alert('❌ Заполните CAN ID и название сигнала');
            return;
        }

        if (!channel) {
            alert('❌ Выберите канал для сигнала');
            return;
        }

        if (firstBytes && !/^[0-9A-Fa-f]{8}$/.test(firstBytes)) {
            alert('❌ Первые 4 байта должны быть 8 шестнадцатеричных символов');
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

                alert(`✅ Сигнал добавлен: ${messageId} - ${signalName}`);
            }
        } catch (error) {
            console.error('Ошибка добавления сигнала:', error);
            alert('❌ Ошибка добавления сигнала: ' + error);
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
            const signalName = '_'.join(parts.slice(1, -1));
            const channel = parts[parts.length - 1];

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
                        </div>
                        <small>
                            Тип: ${dataType}, Байты: ${firstBytes}, 
                            Масштаб: ${config.scale}, Смещение: ${config.offset}
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

    createChartContainer(signalKey) {
        if ($(`#chart-${signalKey}`).length) {
            return;
        }

        const parts = signalKey.split('_');
        const messageId = parts[0];
        const signalName = '_'.join(parts.slice(1, -1));
        const channel = parts[parts.length - 1];
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
                    <button class="btn-danger btn-small close-chart" data-signal="${signalKey}">✕</button>
                </div>
                <div class="chart-container">
                    <canvas id="chartCanvas-${signalKey}"></canvas>
                </div>
                <div class="chart-footer">
                    <small>
                        Канал: ${channel} | Тип: ${dataType} | 
                        Масштаб: ${config.scale} | Смещение: ${config.offset} | 
                        Байты: ${config.start_byte}-${parseInt(config.start_byte) + parseInt(config.length) - 1}
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
    }

    async saveSignalConfig() {
        try {
            const response = await fetch('/api/save_signal_config', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('✅ Конфигурация сигналов сохранена в файл');
            } else {
                alert('❌ Ошибка сохранения: ' + data.message);
            }
        } catch (error) {
            console.error('Ошибка сохранения конфигурации:', error);
            alert('❌ Ошибка сохранения конфигурации: ' + error);
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
                alert('✅ Конфигурация сигналов загружена из файла');
            } else {
                alert('❌ Ошибка загрузки: ' + data.message);
            }
        } catch (error) {
            console.error('Ошибка загрузки конфигурации:', error);
            alert('❌ Ошибка загрузки конфигурации: ' + error);
        }
    }

    async exportSignalConfig() {
        try {
            const response = await fetch('/api/export_signal_config');
            const blob = await response.blob();

            this.downloadFile(blob, 'can_signals_config.json', 'application/json');
            alert('✅ Конфигурация сигналов экспортирована в файл');
        } catch (error) {
            console.error('Ошибка экспорта конфигурации:', error);
            alert('❌ Ошибка экспорта конфигурации: ' + error);
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
            if (chartData[signalKey] && $(`#chart-${signalKey}`).length) {
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

        const channelColor = config.channel === '0' ? 'rgba(54, 162, 235, 0.8)' : 'rgba(255, 159, 64, 0.8)';
        const backgroundColor = config.channel === '0' ? 'rgba(54, 162, 235, 0.2)' : 'rgba(255, 159, 64, 0.2)';

        const chartDataPoints = data.values.map((value, idx) => ({
            x: data.timestamps[idx],
            y: value
        }));

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: data.label,
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
                    },
                    zoom: {
                        zoom: {
                            wheel: {
                                enabled: true,
                            },
                            pinch: {
                                enabled: true
                            },
                            mode: 'x',
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
            { label: 'Сообщений CH0', value: stats.by_channel['0'] || 0 },
            { label: 'Сообщений CH1', value: stats.by_channel['1'] || 0 },
            { label: 'STD фреймы', value: stats.by_type.STD },
            { label: 'EXT фреймы', value: stats.by_type.EXT },
            { label: 'DATA фреймы', value: stats.by_rtr.DATA },
            { label: 'RTR фреймы', value: stats.by_rtr.RTR }
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

        if (Object.keys(stats.by_id).length > 0) {
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

            alert(`✅ Данные успешно экспортированы в ${format.toUpperCase()}`);
        } catch (error) {
            console.error('Ошибка экспорта:', error);
            alert('❌ Ошибка экспорта данных: ' + error);
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