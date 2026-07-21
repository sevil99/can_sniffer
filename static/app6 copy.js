class CANMonitor {
    constructor() {
        this.isConnected = false;
        this.messageCount = 0;
        this.charts = new Map();
        this.selectedSignals = new Map();
        this.updateInterval = null;
        this.useRealTime = true;

        this.initializeEventListeners();
        this.updateStatus();
        this.loadAvailableIDs();
        this.loadSelectedSignals();

        console.log('✅ CAN Monitor v6 инициализирован');
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
            console.log('📊 Изменен тип времени:', this.useRealTime ? 'реальное' : 'относительное');
            this.updateCharts();
        });

        // Модальное окно
        $('#saveSignalBtn').click(() => this.addSignal());
        $('#cancelSignalBtn').click(() => this.hideAddSignalModal());
        $('#refreshIdsModalBtn').click(() => this.loadAvailableIDs());

        // Обновление списка ID при изменении
        $('#refreshIdsBtn').click(() => this.loadAvailableIDs());

        // Автообновление
        this.startAutoUpdate();

        console.log('✅ Обработчики событий инициализированы');
    }

    async scanDevices() {
        try {
            console.log('🔍 Сканирование устройств...');
            const response = await fetch('/api/scan_devices');
            const data = await response.json();

            if (data.status === 'success') {
                alert(`Найдено устройств: ${data.available_channels.length}`);
                console.log('📡 Найдены каналы:', data.available_channels);
            } else {
                alert('Ошибка сканирования: ' + data.error);
                console.error('❌ Ошибка сканирования:', data.error);
            }
        } catch (error) {
            alert('Ошибка сканирования: ' + error);
            console.error('❌ Ошибка сканирования:', error);
        }
    }

    async connect() {
        const channel = $('#channelSelect').val();
        const baudRate = $('#baudRateSelect').val();

        try {
            console.log('🔌 Подключение...', { channel, baudRate });
            const response = await fetch('/api/connect', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    channel: parseInt(channel),
                    baud_rate: parseInt(baudRate)
                })
            });

            const data = await response.json();
            console.log('📡 Ответ подключения:', data);

            if (data.status === 'connected') {
                this.isConnected = true;
                this.updateStatus();
                alert('Успешно подключено!');

                // После подключения загружаем доступные ID
                setTimeout(() => this.loadAvailableIDs(), 1000);
                console.log('✅ Подключено к каналу', channel);
            } else {
                alert('Ошибка подключения: ' + data.message);
                console.error('❌ Ошибка подключения:', data.message);
            }
        } catch (error) {
            console.error('❌ Ошибка подключения:', error);
            alert('Ошибка подключения: ' + error);
        }
    }

    async disconnect() {
        try {
            console.log('🔴 Отключение...');
            const response = await fetch('/api/disconnect', {
                method: 'POST'
            });

            const data = await response.json();

            if (data.status === 'disconnected') {
                this.isConnected = false;
                this.updateStatus();
                alert('Успешно отключено! Сообщения сохранены в файл.');
                console.log('✅ Отключено');
            }
        } catch (error) {
            alert('Ошибка отключения: ' + error);
            console.error('❌ Ошибка отключения:', error);
        }
    }

    async saveLogs() {
        try {
            console.log('💾 Сохранение логов...');
            const response = await fetch('/api/save_logs', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('Логи сохранены в файл');
                console.log('✅ Логи сохранены');
            } else {
                alert('Ошибка сохранения логов: ' + data.message);
                console.error('❌ Ошибка сохранения:', data.message);
            }
        } catch (error) {
            alert('Ошибка сохранения логов: ' + error);
            console.error('❌ Ошибка сохранения:', error);
        }
    }

    async clearMessages() {
        try {
            console.log('🗑️ Очистка сообщений...');
            await fetch('/api/messages/clear', {
                method: 'POST'
            });
            this.updateMessages();
            console.log('✅ Сообщения очищены');
        } catch (error) {
            console.error('❌ Ошибка очистки:', error);
        }
    }

    async sendCustomMessage() {
        const canId = $('#sendIdInput').val();
        const dataHex = $('#sendDataInput').val();
        const isExtended = $('#extendedFrameCheck').is(':checked');
        const isRtr = $('#rtrFrameCheck').is(':checked');

        if (!canId) {
            alert('Введите CAN ID');
            return;
        }

        // Парсинг hex данных
        let dataBytes = [];
        if (dataHex.trim()) {
            try {
                dataBytes = dataHex.trim().split(/\s+/).map(byte => parseInt(byte, 16));
                console.log('📤 Отправка данных:', { canId, dataBytes, isExtended, isRtr });
            } catch (e) {
                alert('Ошибка в формате данных. Используйте hex байты через пробел.');
                return;
            }
        }

        // Отправка сообщения
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
                    rtr: isRtr
                })
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('✅ Сообщение отправлено');
                console.log('📤 Сообщение отправлено');
            } else {
                alert('❌ ' + data.message);
                console.error('❌ Ошибка отправки:', data.message);
            }
        } catch (error) {
            alert('❌ Ошибка отправки: ' + error);
            console.error('❌ Ошибка отправки:', error);
        }
    }

    async sendTestMessage() {
        // Автозаполнение тестовыми данными
        $('#sendIdInput').val('123');
        $('#sendDataInput').val('01 02 03 04 05 06 07 08');
        $('#extendedFrameCheck').prop('checked', false);
        $('#rtrFrameCheck').prop('checked', false);

        try {
            console.log('🧪 Отправка тестового сообщения...');
            const response = await fetch('/api/send_test_message', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('✅ Тестовое сообщение отправлено');
                console.log('✅ Тестовое сообщение отправлено');
            } else {
                alert('❌ ' + data.message);
                console.error('❌ Ошибка теста:', data.message);
            }
        } catch (error) {
            alert('❌ Ошибка отправки: ' + error);
            console.error('❌ Ошибка отправки теста:', error);
        }
    }

    async updateStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();

            console.log('📊 Статус сервера:', data);

            this.isConnected = data.connected;
            this.messageCount = data.message_count;

            // Обновляем UI
            const indicator = $('#statusIndicator');
            const statusText = $('#statusText');
            const messageCount = $('#messageCount');
            const connectBtn = $('#connectBtn');
            const disconnectBtn = $('#disconnectBtn');

            if (this.isConnected) {
                indicator.removeClass('status-disconnected').addClass('status-connected');
                statusText.text(`Подключено (CH${data.channel})`);
                connectBtn.prop('disabled', true);
                disconnectBtn.prop('disabled', false);
                console.log('🟢 Статус: Подключено');
            } else {
                indicator.removeClass('status-connected').addClass('status-disconnected');
                statusText.text('Отключено');
                connectBtn.prop('disabled', false);
                disconnectBtn.prop('disabled', true);
                console.log('🔴 Статус: Отключено');
            }

            messageCount.text(`Сообщений: ${this.messageCount}`);

        } catch (error) {
            console.error('❌ Ошибка обновления статуса:', error);
        }
    }

    async updateMessages() {
        try {
            console.log('📨 Обновление сообщений...');
            const response = await fetch('/api/messages?limit=100');
            const messages = await response.json();

            console.log(`📡 Получено ${messages.length} сообщений с сервера`);

            const container = $('#messagesContainer');

            if (messages.length > 0) {
                console.log('📋 Первое сообщение:', messages[0]);

                // Очищаем таблицу
                container.empty();

                // Показываем сообщения в прямом порядке (новые снизу)
                messages.forEach(msg => {
                    const messageElement = this.createMessageElement(msg);
                    container.append(messageElement);
                });
            } else {
                // Показываем сообщение об отсутствии данных
                container.html(`
                    <tr>
                        <td colspan="7" style="text-align: center; padding: 20px; color: #7f8c8d;">
                            Нет сообщений
                        </td>
                    </tr>
                `);
            }
        } catch (error) {
            console.error('❌ Ошибка обновления сообщений:', error);
            $('#messagesContainer').html(`
                <tr>
                    <td colspan="7" style="text-align: center; padding: 20px; color: #e74c3c;">
                        Ошибка загрузки: ${error.message}
                    </td>
                </tr>
            `);
        }
    }

    createMessageElement(message) {
        // Улучшенная функция создания элемента сообщения
        const channel = message.channel || 'N/A';
        const idHex = message.id_hex || `0x${message.id.toString(16).toUpperCase()}`;
        const dataHex = message.data_hex || (message.data ? message.data.map(b => b.toString(16).padStart(2, '0')).join(' ') : '');
        const timestamp = message.timestamp_str || new Date().toLocaleTimeString();

        // Создаем сигналы для отображения
        let signalsHtml = '';
        if (message.signals) {
            signalsHtml = Object.entries(message.signals)
                .map(([key, value]) => {
                    let displayValue = value;
                    if (typeof value === 'number') {
                        displayValue = value.toFixed(6);
                    } else if (value === null || value === undefined) {
                        displayValue = '—';
                    }
                    return `<span class="signal-item" title="${key}">${key}: ${displayValue}</span>`;
                }).join('');
        }

        return `
            <tr class="message-row">
                <td class="channel-cell">CH${channel}</td>
                <td class="id-cell"><strong>${idHex}</strong></td>
                <td class="type-cell">${message.frame_type || 'STD'}</td>
                <td class="length-cell">${message.length || 0}</td>
                <td class="data-cell"><code>${dataHex}</code></td>
                <td class="time-cell">${timestamp}</td>
                <td class="signals-cell">${signalsHtml || '—'}</td>
            </tr>
        `;
    }

    async loadAvailableIDs() {
        try {
            console.log('🆔 Загрузка доступных ID...');
            const response = await fetch('/api/available_ids');
            const ids = await response.json();

            console.log(`📊 Доступно ID: ${ids.length}`, ids);

            const select = $('#messageIdSelect');
            const currentValue = select.val(); // Сохраняем текущее значение

            select.empty();
            select.append('<option value="">Выберите CAN ID</option>');

            ids.sort().forEach(id => {
                select.append(`<option value="${id}">${id}</option>`);
            });

            // Восстанавливаем выбранное значение если оно есть в новом списке
            if (currentValue && ids.includes(currentValue)) {
                select.val(currentValue);
            }

            // Обновляем статус
            $('#idsStatus').text(`Доступно ID: ${ids.length}`);

        } catch (error) {
            console.error('❌ Ошибка загрузки ID:', error);
            $('#idsStatus').text('Ошибка загрузки ID');
        }
    }

    async loadSelectedSignals() {
        try {
            console.log('📊 Загрузка выбранных сигналов...');
            const response = await fetch('/api/selected_signals');
            const signals = await response.json();

            console.log(`📈 Загружено сигналов: ${Object.keys(signals).length}`, signals);

            this.selectedSignals = new Map(Object.entries(signals));
            this.renderSelectedSignalsList();

            // Автоматически создаем графики для всех загруженных сигналов
            this.selectedSignals.forEach((config, signalKey) => {
                this.createChartContainer(signalKey);
            });

            this.updateCharts();
        } catch (error) {
            console.error('❌ Ошибка загрузки выбранных сигналов:', error);
        }
    }

    showAddSignalModal() {
        console.log('📊 Показ модального окна добавления сигнала');
        $('#addSignalModal').show();
    }

    hideAddSignalModal() {
        console.log('📊 Скрытие модального окна');
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

        if (!messageId || !signalName) {
            alert('Заполните CAN ID и название сигнала');
            return;
        }

        // Валидация первых байтов
        if (firstBytes && !/^[0-9A-Fa-f]{8}$/.test(firstBytes)) {
            alert('Первые 4 байта должны быть 8 шестнадцатеричных символов (например: 03000200)');
            return;
        }

        const parserConfig = {
            type: dataType,
            byte_order: byteOrder,
            start_byte: startByte,
            length: dataLength,
            scale: scale,
            offset: offset
        };

        if (firstBytes) {
            parserConfig.first_bytes = firstBytes.toUpperCase();
        }

        console.log('➕ Добавление сигнала:', { messageId, signalName, parserConfig });

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

                // Автоматически создаем график для нового сигнала
                this.createChartContainer(data.signal_key);
                this.updateCharts();

                // Сбрасываем форму
                $('#signalNameInput').val('');
                $('#firstBytesInput').val('');
                $('#scaleInput').val('1');
                $('#offsetInput').val('0');
                $('#startByteInput').val('0');
                $('#dataLengthInput').val('4');

                console.log('✅ Сигнал добавлен:', data.signal_key);
                alert('✅ Сигнал добавлен: ' + data.signal_key);
            }
        } catch (error) {
            console.error('❌ Ошибка добавления сигнала:', error);
            alert('❌ Ошибка добавления сигнала: ' + error);
        }
    }

    async removeSignal(signalKey) {
        try {
            console.log('🗑️ Удаление сигнала:', signalKey);
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

            // Удаляем соответствующий график
            this.removeChart(signalKey);
            console.log('✅ Сигнал удален:', signalKey);
        } catch (error) {
            console.error('❌ Ошибка удаления сигнала:', error);
        }
    }

    removeChart(signalKey) {
        if (this.charts.has(signalKey)) {
            this.charts.get(signalKey).destroy();
            this.charts.delete(signalKey);

            // Удаляем контейнер графика
            $(`#chart-${signalKey}`).remove();
            console.log('🗑️ График удален:', signalKey);
        }
    }

    renderSelectedSignalsList() {
        const container = $('#selectedSignalsList');
        container.empty();

        if (this.selectedSignals.size === 0) {
            container.append('<div class="no-signals">Нет выбранных сигналов</div>');
            return;
        }

        console.log('📋 Рендеринг списка сигналов:', this.selectedSignals.size);

        this.selectedSignals.forEach((config, signalKey) => {
            // Разбираем signalKey: формат "ID_SignalName_CHX"
            const parts = signalKey.split('_');
            let messageId = parts[0];
            let signalName = '';
            let channel = '1';

            // Находим часть с CH
            for (let i = 1; i < parts.length; i++) {
                if (parts[i].startsWith('CH')) {
                    channel = parts[i].replace('CH', '');
                    // Все части до CH - это имя сигнала
                    signalName = parts.slice(1, i).join('_');
                    break;
                }
            }

            // Если не нашли CH, берем все кроме первой части как имя сигнала
            if (!signalName) {
                signalName = parts.slice(1).join('_') || 'signal';
            }

            const firstBytes = config.first_bytes || 'все';
            const dataType = config.type || 'custom_float';
            const isChartVisible = $(`#chart-${signalKey}`).length > 0;

            const signalElement = $(`
                <div class="selected-signal-item">
                    <div class="signal-info">
                        <strong>CH${channel}: ${messageId}</strong> - ${signalName}
                        <br><small>Тип: ${dataType}, Первые байты: ${firstBytes}, 
                        Масштаб: ${config.scale}, Смещение: ${config.offset},
                        Старт: ${config.start_byte}, Длина: ${config.length}</small>
                    </div>
                    <div>
                        <button class="btn-${isChartVisible ? 'warning' : 'success'} btn-small toggle-chart" 
                                data-signal="${signalKey}" 
                                title="${isChartVisible ? 'Скрыть график' : 'Показать график'}">
                            ${isChartVisible ? '📊' : '📈'}
                        </button>
                        <button class="btn-danger btn-small remove-signal" 
                                data-signal="${signalKey}" 
                                title="Удалить сигнал">✕</button>
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
            // График уже отображается - скрываем
            chartContainer.remove();
            this.removeChart(signalKey);
            console.log('📊 График скрыт:', signalKey);
        } else {
            // График не отображается - создаем
            this.createChartContainer(signalKey);
            this.updateCharts();
            console.log('📊 График создан:', signalKey);
        }

        // Обновляем список сигналов чтобы обновить иконки кнопок
        this.renderSelectedSignalsList();
    }

    createChartContainer(signalKey) {
        // Проверяем, не создан ли уже контейнер
        if ($(`#chart-${signalKey}`).length) {
            return;
        }

        // Разбираем signalKey
        const parts = signalKey.split('_');
        let messageId = parts[0];
        let signalName = '';
        let channel = '1';

        // Находим часть с CH
        for (let i = 1; i < parts.length; i++) {
            if (parts[i].startsWith('CH')) {
                channel = parts[i].replace('CH', '');
                // Все части до CH - это имя сигнала
                signalName = parts.slice(1, i).join('_');
                break;
            }
        }

        if (!signalName) {
            signalName = parts.slice(1).join('_') || 'signal';
        }

        const config = this.selectedSignals.get(signalKey);
        const firstBytes = config?.first_bytes || 'все';
        const dataType = config?.type || 'custom_float';

        const chartHtml = `
            <div class="chart-card" id="chart-${signalKey}">
                <div class="chart-header">
                    <h4>CH${channel}: ${messageId} - ${signalName} [${firstBytes}]</h4>
                    <button class="btn-danger btn-small close-chart" 
                            data-signal="${signalKey}" 
                            title="Закрыть график">✕</button>
                </div>
                <div class="chart-container">
                    <canvas id="chartCanvas-${signalKey}"></canvas>
                </div>
            </div>
        `;

        $('#chartsContainer').append(chartHtml);
        console.log('📊 Контейнер графика создан:', signalKey);

        // Добавляем обработчик закрытия
        $(`#chart-${signalKey} .close-chart`).click(() => {
            this.removeChart(signalKey);
            $(`#chart-${signalKey}`).remove();
            this.renderSelectedSignalsList();
        });
    }

    async saveSignalConfig() {
        try {
            console.log('💾 Сохранение конфигурации сигналов...');
            const response = await fetch('/api/save_signal_config', {
                method: 'POST'
            });

            const data = await response.json();
            if (data.status === 'success') {
                alert('✅ Конфигурация сигналов сохранена в файл');
                console.log('✅ Конфигурация сохранена');
            } else {
                alert('❌ ' + data.message);
                console.error('❌ Ошибка сохранения:', data.message);
            }
        } catch (error) {
            console.error('❌ Ошибка сохранения конфигурации:', error);
            alert('❌ Ошибка сохранения конфигурации: ' + error);
        }
    }

    async loadSignalConfig() {
        try {
            console.log('📂 Загрузка конфигурации сигналов...');
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
                console.log('✅ Конфигурация загружена:', Object.keys(data.signals).length, 'сигналов');
            } else {
                alert('❌ ' + data.message);
                console.error('❌ Ошибка загрузки:', data.message);
            }
        } catch (error) {
            console.error('❌ Ошибка загрузки конфигурации:', error);
            alert('❌ Ошибка загрузки конфигурации: ' + error);
        }
    }

    async exportSignalConfig() {
        try {
            console.log('📤 Экспорт конфигурации...');
            const response = await fetch('/api/export_signal_config');
            const blob = await response.blob();

            this.downloadFile(blob, 'can_signals_config.json', 'application/json');
            alert('✅ Конфигурация сигналов экспортирована в файл');
            console.log('✅ Конфигурация экспортирована');
        } catch (error) {
            console.error('❌ Ошибка экспорта конфигурации:', error);
            alert('❌ Ошибка экспорта конфигурации: ' + error);
        }
    }

    async updateCharts() {
        try {
            const timeWindow = $('#timeWindowSelect').val();
            const realTimeParam = this.useRealTime ? 'true' : 'false';

            console.log('📈 Обновление графиков...', { timeWindow, realTimeParam });

            const response = await fetch(`/api/chart_data?time_window=${timeWindow}&real_time=${realTimeParam}`);
            const chartData = await response.json();

            console.log(`📊 Получено данных для ${Object.keys(chartData).length} графиков`, chartData);

            // Если нет данных для графиков, покажем сообщение
            if (Object.keys(chartData).length === 0) {
                console.log('⚠️ Нет данных для графиков. Проверьте:');
                console.log('1. Подключен ли CAN канал?');
                console.log('2. Есть ли сообщения на вкладке "Сообщения"?');
                console.log('3. Правильно ли настроены сигналы?');

                // Создаем тестовые данные для отладки
                if (this.selectedSignals.size > 0) {
                    console.log('🧪 Создаю тестовые данные для отладки...');
                    this.createTestChartData();
                }
            } else {
                this.renderCharts(chartData);
            }
        } catch (error) {
            console.error('❌ Ошибка обновления графиков:', error);
            console.error('Детали ошибки:', error.message);
        }
    }

    createTestChartData() {
        // Создаем тестовые данные для отладки
        this.selectedSignals.forEach((config, signalKey) => {
            if ($(`#chart-${signalKey}`).length) {
                const testData = {
                    timestamps: [],
                    values: [],
                    label: `TEST: ${signalKey}`,
                    id: signalKey.split('_')[0],
                    signal: 'test',
                    first_bytes: 'TEST',
                    channel: '1',
                    real_time: this.useRealTime,
                    config: config
                };

                const now = Date.now() / 1000;
                for (let i = 0; i < 20; i++) {
                    testData.timestamps.push(now - (20 - i));
                    testData.values.push(Math.sin(i * 0.3) * 10 + Math.random() * 2);
                }

                console.log(`🧪 Тестовые данные для ${signalKey}:`, testData);
                this.renderSingleChart(signalKey, testData);
            }
        });
    }

    renderCharts(chartData) {
        console.log('🎨 Рендеринг графиков...');

        let chartsRendered = 0;

        // Обновляем каждый отдельный график
        this.selectedSignals.forEach((config, signalKey) => {
            if (chartData[signalKey] && $(`#chart-${signalKey}`).length) {
                console.log(`📊 Рендерим график ${signalKey}:`, chartData[signalKey]);
                this.renderSingleChart(signalKey, chartData[signalKey]);
                chartsRendered++;
            } else if ($(`#chart-${signalKey}`).length) {
                console.log(`⚠️ Нет данных для графика: ${signalKey}`);
                // Показываем сообщение об отсутствии данных
                $(`#chart-${signalKey} .chart-container`).html(`
                    <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #7f8c8d;">
                        <div style="text-align: center;">
                            <div>⏳ Ожидание данных...</div>
                            <small>Проверьте соответствие ID и первых байт</small>
                        </div>
                    </div>
                `);
            }
        });

        console.log(`✅ Отрендерено графиков: ${chartsRendered} из ${this.selectedSignals.size}`);
    }

    renderSingleChart(signalKey, data) {
        const canvasId = `chartCanvas-${signalKey}`;
        const canvasElement = document.getElementById(canvasId);

        if (!canvasElement) {
            console.warn(`❌ Canvas элемент не найден: ${canvasId}`);
            return;
        }

        const ctx = canvasElement.getContext('2d');

        // Уничтожаем предыдущий график если есть
        if (this.charts.has(signalKey)) {
            this.charts.get(signalKey).destroy();
        }

        // Проверяем данные
        if (!data || !data.values || !data.timestamps ||
            data.values.length === 0 || data.timestamps.length === 0) {
            console.warn(`⚠️ Нет данных для графика ${signalKey}`);
            return;
        }

        // Создаем точки данных для графика
        const chartDataPoints = [];
        for (let i = 0; i < data.values.length; i++) {
            const value = data.values[i];
            const timestamp = data.timestamps[i];

            // Пропускаем NaN и undefined
            if (value === null || value === undefined || isNaN(value)) {
                continue;
            }

            chartDataPoints.push({
                x: timestamp,
                y: value
            });
        }

        console.log(`📊 Создание графика ${signalKey}: ${chartDataPoints.length} точек`);

        if (chartDataPoints.length === 0) {
            console.warn(`⚠️ Нет валидных точек данных для графика ${signalKey}`);
            return;
        }

        try {
            const chart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: data.label || signalKey,
                        data: chartDataPoints,
                        borderColor: this.getRandomColor(),
                        backgroundColor: this.getRandomColor(0.1),
                        borderWidth: 2,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                        pointBackgroundColor: this.getRandomColor(),
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 1
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
                                        // Форматируем Unix timestamp в читаемое время
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
                            grace: '5%' // Добавляем немного места сверху и снизу
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                label: (context) => {
                                    const label = context.dataset.label || '';
                                    const value = context.parsed.y;
                                    return `${label}: ${value.toFixed(6)}`;
                                },
                                title: (context) => {
                                    if (this.useRealTime) {
                                        const date = new Date(context[0].parsed.x * 1000);
                                        return date.toLocaleString();
                                    } else {
                                        return `Время: ${context[0].parsed.x.toFixed(1)}с`;
                                    }
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    },
                    animation: {
                        duration: 300,
                        easing: 'easeOutQuart'
                    }
                }
            });

            this.charts.set(signalKey, chart);
            console.log(`✅ График создан: ${signalKey}`);

        } catch (error) {
            console.error(`❌ Ошибка создания графика ${signalKey}:`, error);
        }
    }

    getRandomColor(alpha = 1) {
        const colors = [
            '#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6',
            '#1abc9c', '#d35400', '#c0392b', '#16a085', '#8e44ad',
            '#27ae60', '#2980b9', '#8e44ad', '#2c3e50', '#f1c40f'
        ];

        // Генерируем индекс на основе signalKey для постоянства цвета
        let hash = 0;
        const signalKey = this.currentSignalKey || '';
        for (let i = 0; i < signalKey.length; i++) {
            hash = signalKey.charCodeAt(i) + ((hash << 5) - hash);
        }

        const index = Math.abs(hash) % colors.length;
        const color = colors[index];

        if (alpha < 1) {
            // Добавляем прозрачность
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        }

        return color;
    }

    clearCharts() {
        console.log('🗑️ Очистка всех графиков...');

        // Удаляем все графики
        this.charts.forEach((chart, signalKey) => {
            chart.destroy();
        });
        this.charts.clear();

        // Удаляем контейнеры графиков
        $('#chartsContainer').empty();

        // Удаляем все сигналы
        this.selectedSignals.forEach((config, signalKey) => {
            this.removeSignal(signalKey);
        });

        console.log('✅ Все графики очищены');
    }

    async updateStatistics() {
        try {
            console.log('📊 Обновление статистики...');
            const response = await fetch('/api/statistics');
            const stats = await response.json();

            console.log('📈 Статистика:', stats);
            this.renderStatistics(stats);
        } catch (error) {
            console.error('❌ Ошибка обновления статистики:', error);
        }
    }

    renderStatistics(stats) {
        console.log('🎨 Рендеринг статистики...');

        // Основная статистика
        const statsGrid = $('#statisticsGrid');
        statsGrid.empty();

        const mainStats = [
            { label: 'Всего сообщений', value: stats.total_messages || 0 },
            { label: 'STD фреймы', value: stats.by_type?.STD || 0 },
            { label: 'EXT фреймы', value: stats.by_type?.EXT || 0 },
            { label: 'DATA фреймы', value: stats.by_rtr?.DATA || 0 },
            { label: 'RTR фреймы', value: stats.by_rtr?.RTR || 0 },
            { label: 'Текущий канал', value: stats.current_channel !== undefined ? `CH${stats.current_channel}` : '—' }
        ];

        mainStats.forEach(stat => {
            statsGrid.append(`
                <div class="stat-item">
                    <div class="stat-value">${stat.value}</div>
                    <div class="stat-label">${stat.label}</div>
                </div>
            `);
        });

        // Статистика по ID
        const idStats = $('#idStatistics');
        idStats.empty();

        if (stats.by_id && Object.keys(stats.by_id).length > 0) {
            idStats.append('<h4 style="margin: 15px 0 10px 0;">Статистика по ID:</h4>');
            for (const [msgId, data] of Object.entries(stats.by_id)) {
                idStats.append(`
                    <div style="margin: 8px 0; padding: 10px; background: #f8f9fa; border-radius: 5px; border-left: 4px solid var(--secondary-color);">
                        <strong>${msgId}</strong>: ${data.count} сообщений 
                        (${data.frequency?.toFixed(1) || '0.0'}/сек)
                        <br><small>Последнее: ${data.last_seen || '—'}</small>
                    </div>
                `);
            }
        } else {
            idStats.append('<div style="color: #7f8c8d; text-align: center; padding: 20px;">Нет статистики по ID</div>');
        }
    }

    async exportData(format) {
        try {
            console.log(`📤 Экспорт данных в формате ${format}...`);
            const response = await fetch(`/api/export/messages?format=${format}`);

            if (format === 'json') {
                const data = await response.json();
                this.downloadFile(JSON.stringify(data, null, 2), 'can_messages.json', 'application/json');
            } else if (format === 'csv') {
                const blob = await response.blob();
                this.downloadFile(blob, 'can_messages.csv', 'text/csv');
            }

            alert(`✅ Данные успешно экспортированы в ${format.toUpperCase()}`);
            console.log(`✅ Данные экспортированы в ${format}`);
        } catch (error) {
            console.error('❌ Ошибка экспорта:', error);
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
        console.log('📑 Переключение таба:', tabElement);

        // Убираем активный класс у всех табов
        $('.tab').removeClass('active');
        $('.tab-content').removeClass('active');

        // Добавляем активный класс к выбранному табу
        $(tabElement).addClass('active');
        const tabId = $(tabElement).data('tab');
        $(`#${tabId}-tab`).addClass('active');

        // Обновляем контент таба
        if (tabId === 'messages') {
            console.log('📨 Переход на вкладку сообщений');
            this.updateMessages();
        } else if (tabId === 'statistics') {
            console.log('📊 Переход на вкладку статистики');
            this.updateStatistics();
        } else if (tabId === 'charts') {
            console.log('📈 Переход на вкладку графиков');
            this.updateCharts();
            // Автоматически загружаем ID при переходе на вкладку графиков
            if (this.isConnected) {
                this.loadAvailableIDs();
            }
        } else if (tabId === 'export') {
            console.log('💾 Переход на вкладку экспорта');
        }
    }

    startAutoUpdate() {
        console.log('🔄 Запуск автообновления...');

        // Обновляем статус каждую секунду
        setInterval(() => {
            this.updateStatus();
        }, 1000);

        // Обновляем активный таб каждые 2 секунды
        setInterval(() => {
            const activeTab = $('.tab.active').data('tab');

            if (!activeTab) return;

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

// Инициализация при загрузке страницы
$(document).ready(() => {
    window.canMonitor = new CANMonitor();
    console.log('🚀 CAN Monitor v6 запущен и готов к работе!');

    // Добавляем глобальную функцию для отладки
    window.debugChartData = function () {
        console.log('=== ОТЛАДКА ГРАФИКОВ ===');
        console.log('Выбранные сигналы:', window.canMonitor.selectedSignals);
        console.log('Активные графики:', window.canMonitor.charts);

        // Проверим API endpoint
        fetch('/api/chart_data?time_window=60&real_time=true')
            .then(response => {
                console.log('API Response Status:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('Данные с сервера:', data);
                console.log('Количество графиков:', Object.keys(data).length);

                // Проверим каждый график
                Object.keys(data).forEach(key => {
                    console.log(`График ${key}:`, {
                        точек: data[key].timestamps?.length,
                        значений: data[key].values?.length,
                        метка: data[key].label
                    });
                });
            })
            .catch(error => {
                console.error('Ошибка проверки API:', error);
            });
    };

    window.testChart = function () {
        // Создаем тестовый график
        const testCanvas = document.createElement('canvas');
        document.body.appendChild(testCanvas);
        const ctx = testCanvas.getContext('2d');

        const testChart = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Тестовый график',
                    data: [{ x: 1, y: 2 }, { x: 2, y: 3 }, { x: 3, y: 1 }],
                    borderColor: '#3498db'
                }]
            }
        });

        console.log('✅ Тестовый график создан');
    };
});