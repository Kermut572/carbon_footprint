/**
 * Basic panel for the Carbon Footprint integration. Most of the code is currently ugly and AI-generated
 * for testing purposes. We should rewrite it properly later.
 */

import { CarbonUtils } from './frontend/carbon-utils.js';
import { openFullForm } from './frontend/form-manager.js';

class CarbonFootprintPanel extends HTMLElement {

    constructor() {
        super();
        this._devices = [];
        this._setup = false
        this._histogramData = null;
        this._chart = null;
        this._roomChart = null;
        this._deviceChart = null;
        this._roomData = null;
        this._selectedRoom = null;
        this._currentPage = 'main'; // 'main' or 'settings'
        this._carbonView = 'total'; // 'total', 'embodied', or 'usage'
        this._groupBy = 'room'; // 'room' or 'type'

        this._chartGranularity = {
            HOUR: "hour",
            DAY: "day",
            MONTH: "month"
        };
        this._currentChartGranularity = this._chartGranularity.HOUR;

        this._timeFrame = {
            WEEK: "last-week",
            MONTH: "last-month",
            YEAR: "last-year"
        };
        this._currentTimeFrame = this._timeFrame.WEEK;
    }


    async connectedCallback() {
        const data = await this.getCarbonData();
        await this.render(data);
        this._setup = true
    }

    set hass(hass) {
        this._hass = hass;

        if (!this._setup && this.isConnected) {
            this.connectedCallback();
        }
    }

    get hass() {
        return this._hass;
    }

    async getCarbonData() {
        console.log('Getting carbon data from backend');
        return await CarbonUtils.getCarbonData(this);
    }

    async getAllDevicesEnergy() {
        return await CarbonUtils.getAllDevicesEnergy(this);
    }

    async updateDeviceEnergy() {
        return await CarbonUtils.updateDeviceEnergy(this);
    }

    async getEnergyHistogram() {
        try {
            let pastDays;
            switch (this._currentTimeFrame) {
                case this._timeFrame.WEEK:
                    pastDays = 7;
                    break;
                case this._timeFrame.MONTH:
                    pastDays = 30;
                    break;
                case this._timeFrame.YEAR:
                    pastDays = 365;
                    break;
                default:
                    pastDays = 7;
                    break;
            }

            console.log('Querying with ', pastDays, ' , timeframe was ', this._currentTimeFrame)

            const endTime = new Date();
            const startTime = new Date(endTime);
            startTime.setDate(endTime.getDate() - pastDays);

            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_energy_footprint_time_interval',
                start_time: startTime.toISOString(),
                end_time: endTime.toISOString(),
                granularity: this._currentChartGranularity
            });

            if (!result.energy_footprints || result.energy_footprints.length === 0) {
                return '<p>No historical data available</p>';
            }

            this._histogramData = result.energy_footprints;

            return `
                <div style="position: relative; height: 300px; width: 100%;">
                    <canvas id="energy-histogram-chart"></canvas>
                </div>
            `;

        } catch (err) {
            console.error('Error loading histogram:', err);
            return '<p>Error loading histogram data</p>';
        }
    }

    async getCarbonByRoom() {
        try {
            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_carbon_by_room_with_usage'
            });

            this._roomData = result.rooms || [];
            return this._roomData;

        } catch (err) {
            console.error('Error loading room data:', err);
            return [];
        }
    }

    async getCarbonByType() {
        try {
            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_carbon_by_type_with_usage'
            });

            this._typeData = result.types || [];
            return this._typeData;

        } catch (err) {
            console.error('Error loading type data:', err);
            return [];
        }
    }

    async updateDeviceList() {
        return await CarbonUtils.updateDeviceList(this);
    }

    async render(data) {
        if (this._currentPage === 'settings') {
            this.renderSettingsPage(data);
            return;
        }

        const energyHistogram = await this.getEnergyHistogram();

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <h1>Carbon Footprint</h1>
                    <button id="settings-btn" style="position: absolute; right: 20px; top: 15px; padding: 8px 16px; background-color: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">Settings</button>
                </header>

                <div class="content" slot="content">
                    <ha-card header="Energy Footprint">
                        <div class="card-content">
                            <p>Current Energy CO₂ Intensity:
                            <span class="ci-value"><b>${data?.co2_intensity ?? 'N/A'}</b></span>
                            gCO₂eq/kWh
                            <span class="ci-indicator ${CarbonUtils.getCarbonColor(data?.co2_intensity)}"></span>
                            <span class="ci-label">${CarbonUtils.getCarbonLabel(data?.co2_intensity)}</span></p>
                            <p style="font-size: 12px; color: #666; margin-top: 8px; margin-bottom: 16px;">
                                <em>Grid carbon intensity over time (in grams CO₂ equivalent per kilowatt-hour)</em>
                            </p>
                            <div class="histogram-controls">
                                <label for="granularity-select">Granularity:</label>
                                <select id="granularity-select">
                                    <option value="hour">Hour</option>
                                    <option value="day">Day</option>
                                    <option value="month">Month</option>
                                </select>


                                <label for="time-frame-select">Time Frame:</label>
                                <select id="time-frame-select">
                                    <option value="last-week">Last Week</option>
                                    <option value="last-month">Last Month</option>
                                    <option value="last-year">Last Year</option>
                                </select>
                            </div>
                            <div id="energy-histogram-container">
                                ${energyHistogram}
                            </div>
                        </div>

                    </ha-card>

                    <ha-card header="Carbon Usage">
                        <div class="card-content">
                            <div class="histogram-controls">
                                <label for="group-by-select">Group by:</label>
                                <select id="group-by-select">
                                    <option value="room" ${this._groupBy === 'room' ? 'selected' : ''}>Room</option>
                                    <option value="type" ${this._groupBy === 'type' ? 'selected' : ''}>Type</option>
                                </select>
                            </div>

                            <!-- Carbon view toggle with unit explanation -->
                            <div style="margin-bottom: 12px;">
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="total" checked style="margin-right: 6px;">
                                        <span>Total (Stacked)</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="embodied" style="margin-right: 6px;">
                                        <span>Embodied Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="usage" style="margin-right: 6px;">
                                        <span>Usage Only</span>
                                    </label>
                                </div>
                            </div>

                            <!-- Room-level pie chart view -->
                            <div id="room-chart-view" style="display: block;">
                                <div style="position: relative; height: 400px; width: 100%;">
                                    <canvas id="room-pie-chart"></canvas>
                                </div>
                            </div>

                            <!-- Device detail view (hidden by default) -->
                            <div id="device-detail-view" style="display: none;">
                                <button id="back-to-rooms-btn" style="margin-bottom: 16px; padding: 8px 16px; background-color: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;">← Back to Rooms</button>
                                <h3 id="selected-room-title"></h3>

                                <!-- Legend explaining embodied vs usage -->
                                <div style="margin-bottom: 16px; padding: 12px; background-color: #f9f9f9; border-radius: 4px; border: 1px solid #ddd; font-size: 13px;">
                                    <div style="margin-bottom: 8px;"><strong>Carbon Types (kgCO₂eq):</strong></div>
                                    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <div style="width: 16px; height: 16px; background-color: rgba(76, 175, 80, 0.7); border: 1px solid rgb(76, 175, 80);"></div>
                                            <span><strong>Embodied:</strong> Manufacturing, transport, disposal</span>
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <div style="width: 16px; height: 16px; background-color: rgba(33, 150, 243, 0.7); border: 1px solid rgb(33, 150, 243);"></div>
                                            <span><strong>Usage:</strong> Operational energy consumption</span>
                                        </div>
                                    </div>
                                </div>

                                <p id="device-breakdown-text" style="margin-bottom: 12px; font-size: 13px; color: #666;"></p>
                                <div style="position: relative; height: 300px; width: 100%;">
                                    <canvas id="device-bar-chart"></canvas>
                                </div>
                            </div>
                        </div>
                    </ha-card>
                </div>
            </ha-app-layout>
        `;

        if (typeof Chart === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
            script.onload = async () => {
                this.renderHistogram();
                await this.renderRoomChart();
            };
            document.head.appendChild(script);
        } else {
            this.renderHistogram();
            await this.renderRoomChart();
        }

        const granSelect = this.querySelector('#granularity-select');
        if (granSelect) {
            granSelect.value = this._currentChartGranularity;
            granSelect.addEventListener('change', async (e) => {
                this._currentChartGranularity = e.target.value;
                await this.refreshHistogram();
            });
        }

        const timeFrameSelect = this.querySelector('#time-frame-select');
        if (timeFrameSelect) {
            timeFrameSelect.value = this._currentTimeFrame;
            timeFrameSelect.addEventListener('change', async (e) => {
                this._currentTimeFrame = e.target.value;
                await this.refreshHistogram();
            });
        }

        // Add settings button click handler
        const settingsBtn = this.querySelector('#settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => {
                this._currentPage = 'settings';
                this.render(data);
            });
        }

        const groupBySelect = this.querySelector('#group-by-select');
        if (groupBySelect) {
            groupBySelect.addEventListener('change', async (e) => {
                this._groupBy = e.target.value;
                await this.renderRoomChart();
            });
        }

        // Add back to rooms button handler
        const backBtn = this.querySelector('#back-to-rooms-btn');
        if (backBtn) {
            backBtn.addEventListener('click', () => {
                this.showRoomChart();
            });
        }

        // Add carbon view radio buttons event listeners
        const carbonViewRadios = this.querySelectorAll('input[name="carbon-view"]');
        for (const radio of carbonViewRadios) {
            radio.addEventListener('change', async (e) => {
                this._carbonView = e.target.value;
                await this.renderRoomChart();

                // If device detail view is visible, also re-render device chart
                const deviceDetailView = this.querySelector('#device-detail-view');
                if (deviceDetailView && deviceDetailView.style.display !== 'none') {
                    // Re-fetch room data to get updated values for the selected view
                    const data = this._groupBy === 'type'
                        ? await this.getCarbonByType()
                        : await this.getCarbonByRoom();

                    if (data && this._selectedRoom) {
                        const updatedItem = data.find(item =>
                            item.room === this._selectedRoom.room ||
                            item.type === this._selectedRoom.type
                        );
                        if (updatedItem) {
                            this._selectedRoom = updatedItem;
                            this.renderDeviceChart();
                        }
                    }
                }
            });
        }

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.12'; // :skull:
        this.appendChild(link);
    }

    renderForm(devices) {
        return `
            <form id="add-device-form">
                <div>
                    <label for="device_name">Entity</label>
                    <select id="device_name" name="device_name" required>
                        <option value="">Select an entity...</option>
                        ${devices.map(deviceName => `
                            <option value="${deviceName}">${deviceName}</option>
                        `).join('')}
                    </select>
                </div>
                <div>
                    <label for="device_type">Device Type</label>
                    <input type="text" id="device_type" name="device_type" required>
                </div>
                <div>
                    <label for="carbon_footprint">Carbon Footprint (kgCO₂eq)</label>
                    <input type="number" id="carbon_footprint" name="carbon_footprint" step="0.01" required>
                </div>
                <div class="button-group">
                    <button type="button" id="compute-footprint-btn">Compute Footprint</button>
                    <button type="submit">Add Device</button>
                    <button type="button" id="detect-devices-btn"><div class="loader" id="loader"></div>Automatic Setup</button>
                    <button type="button" id="export-json-btn">Export to JSON</button>
                </div>
            </form>
        `;
    }

    renderEnergyTable(devices) {
        if (!devices.length) {
            return `<p>No devices with measurable energy consumption found.</p>`;
        }

        return `
            <table class="energy-table">
            <thead>
                <tr>
                <th>Device</th>
                <th>Total Energy (kWh)</th>
                </tr>
            </thead>
            <tbody>
                ${devices.map(device => `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.total_energy_kwh?.toFixed(2) ?? 'N/A'}</td>
                </tr>
                `).join('')}
            </tbody>
            </table>
        `;
    }

    async renderSettingsPage(data) {
        const devicesResp = await this._hass.callWS({ type: 'carbon_footprint/get_devices_to_add' });
        const devicesArray = devicesResp.device_names || [];
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

        const allDevicesEnergyResp = await this.getAllDevicesEnergy();
        const energyDevices = allDevicesEnergyResp.devices_energy || [];
        energyDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <h1>Carbon Footprint</h1>
                    <button id="back-btn" style="position: absolute; right: 20px; top: 15px; padding: 8px 16px; background-color: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">← Back</button>
                </header>

                <div class="content" slot="content">
                    <ha-card header="Add New Device">
                        <div class="card-content">
                            ${this.renderForm(devicesArray)}
                        </div>
                    </ha-card>

                    <ha-card header="Configured Devices">
                        <div class="card-content device-list-container">
                            ${hasDevices ? `
                                <ul>
                                    ${Object.entries(data.devices).map(([device_id, info]) => `
                                        <li>
                                            <div class="device-info">
                                                <div class="device-header">
                                                    <h2><b>${info.metadata?.display_name || device_id}</b></h2><br>
                                                    <div class="device-extended">
                                                        Type: ${info.type || 'Unknown'}<br>
                                                        Area: ${info.metadata?.area_id || 'N/A'} <br>
                                                        Carbon: ${info.carbon_footprint || 0} kgCO₂eq <br>
                                                        Manfucturer: ${info.metadata?.manufacturer || 'N/A'}<br>
                                                        Model: ${info.metadata?.model || 'N/A'}<br>
                                                        Model ID: ${info.metadata?.model_id || 'N/A'}<br>
                                                        Class: ${info.metadata?.device_classes || 'N/A'}<br>
                                                        HA ID: ${device_id || 'UNKNOWN'} <br>
                                                        Total Energy Consumed: ${info.metadata?.total_energy || 'N/A'}<br>
                                                    </div>
                                                </div>
                                                <button
                                                    type="button"
                                                    class="extend-btn"
                                                    title="More information">
                                                    ▼
                                                </button>
                                                <button
                                                    type="button"
                                                    class="delete-btn"
                                                    data-entity-id="${device_id}"
                                                    title="Remove device">
                                                    ✕
                                                </button>
                                            </div>
                                        </li>
                                    `).join('')}
                                </ul>
                            ` : `<p>No devices configured yet.</p>`}
                        </div>
                    </ha-card>
                </div>
            </ha-app-layout>
        `;

        const backBtn = this.querySelector('#back-btn');
        if (backBtn) {
            backBtn.addEventListener('click', async () => {
                this._currentPage = 'main';
                const newData = await this.getCarbonData();
                await this.render(newData);
            });
        }

        const sortSelect = this.querySelector('#sort-mode');
        const tableContainer = this.querySelector('#energy-table-container');

        if (sortSelect && tableContainer) {
            sortSelect.addEventListener('change', () => {
                let sortedDevices = [...energyDevices];
                if (sortSelect.value === 'energy') {
                    sortedDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);
                } else if (sortSelect.value === 'name') {
                    sortedDevices.sort((a, b) => a.device_name.localeCompare(b.device_name));
                }
                tableContainer.innerHTML = this.renderEnergyTable(sortedDevices);
            });
        }

        this.attachFormHandler();

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.18'; // :skull:
        this.appendChild(link);
    }

    async refreshHistogram() {
        const newHtml = await this.getEnergyHistogram();
        const container = this.querySelector('#energy-histogram-container');
        if (container) {
            container.innerHTML = newHtml;
        }

        if (typeof Chart === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
            script.onload = () => this.renderHistogram();
            document.head.appendChild(script);
        } else {
            this.renderHistogram();
        }
    }

    showLoadingOverlay(message = 'Loading...') {
        this.hideLoadingOverlay();

        const overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-content">
                <div class="spinner"></div>
                <p>${message}</p>
            </div>
        `;

        this.appendChild(overlay);
    }

    hideLoadingOverlay() {
        const overlay = this.querySelector('#loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    async detectDevicesType(detectBtn, loaderAnim) {
        const devicesResp = await this._hass.callWS({ type: 'carbon_footprint/get_devices_to_add' });
        let deviceIds = devicesResp.device_ids || [];
        let deviceNames = devicesResp.device_names || [];
        let deviceModels = devicesResp.device_models || [];
        let deviceManufacturers = devicesResp.device_manufacturers || [];

        let devicesDict = {};
        for (let i = 0; i < deviceNames.length; i++) {
            let infoDict = {};
            infoDict['model'] = deviceModels[i];
            infoDict['manufacturer'] = deviceManufacturers[i];
            devicesDict[deviceNames[i]] = infoDict;
        }

        try {
            this.showLoadingOverlay('Detecting device types...');
            const llmResp = await this._hass.callWS({
                type: 'carbon_footprint/llm_detection',
                devices: devicesDict
            });
            let deviceTypes = JSON.parse(llmResp.device_types);
            console.log('Device Types Detection successful, continuing...');

            let i = 0;
            for(const key in devicesDict) {
                devicesDict[key]['device_type'] = deviceTypes[key];
                devicesDict[key]['device_id'] = deviceIds[i];
                i++;
            }

            this.showLoadingOverlay('Matching devices with database...');

            console.log(`Sending ${JSON.stringify(devicesDict)}`)
            const dbMatchingResp = await this._hass.callWS({
                type: 'carbon_footprint/db_matching',
                device_types: devicesDict,
            });
            let devicesMatched = dbMatchingResp.devices_matched;
            console.log(`${devicesMatched}`)


            //flow: Once we got the device types: pull the db and match carbon values, this will automatically setup everything where possible.
            //idea: pass the device_types json as argument for another websocket, which will return another json in the following format:
            //{
            //  "<device_name>" : {
            //      "device_type": "<type>"
            //      "carbon_footprint": "<value>"
            //  }
            //}
            //then use this for set_device

            this.showLoadingOverlay('Adding devices to Carbon Footprint Integration...');
            for (const [deviceName, deviceInfo] of Object.entries(devicesMatched)) {
                console.log(`Processing ${deviceName}: `, deviceInfo)
                await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        device_name: deviceName,
                        device_type: deviceInfo.device_type,
                        carbon_footprint: deviceInfo.carbon_footprint,
                        metadata: {}
                    });
            }
        } catch (error) {
            console.error('LLM detection failed:', error);
            alert(`Device type detection failed: ${error.message || error.code}`);
        }
        finally {
            this.hideLoadingOverlay();
            detectBtn.disabled = false;
            loaderAnim.style.display = 'none';
            const updatedData = await this.getCarbonData();
            await this.renderSettingsPage(updatedData);
        }
    }

    renderHistogram() {
        const canvas = this.querySelector('#energy-histogram-chart');
        if (!canvas || !this._histogramData) {
            return;
        }

        const labels = this._histogramData.map(point => {
            const date = new Date(point.timestamp);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    return date.toLocaleDateString('fr-FR', {
                        day: '2-digit',
                        month: '2-digit',
                        hour: '2-digit'
                    });
                case this._chartGranularity.DAY:
                    return date.toLocaleDateString('fr-FR', {
                        day: '2-digit',
                        month: '2-digit',
                    });
                case this._chartGranularity.MONTH:
                    return date.toLocaleDateString('fr-FR', {
                        month: '2-digit',
                        year: 'numeric'
                    });
            }
        });

        const values = this._histogramData.map(point => point.energy_footprint);
        if (this._chart) {
            this._chart.destroy();
        }
        this._chart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'CO₂ intensity (gCO₂eq/kWh)',
                    data: values,
                    backgroundColor: 'rgba(3, 169, 244, 0.5)',
                    borderColor: 'rgb(3, 169, 244)',
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.parsed.y.toFixed(1)} gCO₂eq/kWh`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'gCO₂eq/kWh'
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45
                        }
                    }
                }
            }
        });
    }

    async renderRoomChart() {
        const canvas = this.querySelector('#room-pie-chart');
        if (!canvas) {
            return;
        }

        // Fetch room data
        let data;
        if (this._groupBy === 'type') {
            data = await this.getCarbonByType();
        } else {
            data = await this.getCarbonByRoom();
        }

        if (!data || data.length === 0) {
            const container = this.querySelector('#room-chart-view');
            if (container) {
                container.innerHTML = '<p>No room data available</p>';
            }
            return;
        }

        // Prepare data for pie chart based on selected view
        const labels = data.map(item => item.room || item.type);
        let values;
        let datasetLabel;

        switch (this._carbonView) {
            case 'embodied':
                values = data.map(item => item.embodied_carbon);
                datasetLabel = 'Embodied Carbon';
                break;
            case 'usage':
                values = data.map(item => item.usage_carbon);
                datasetLabel = 'Usage Carbon';
                break;
            case 'total':
            default:
                values = data.map(item => item.total_carbon);
                datasetLabel = 'Total Carbon';
        }

        const colors = [
            'rgba(76, 175, 80, 0.6)',   // Green
            'rgba(33, 150, 243, 0.6)',  // Blue
            'rgba(255, 152, 0, 0.6)',   // Orange
            'rgba(244, 67, 54, 0.6)',   // Red
            'rgba(156, 39, 176, 0.6)',  // Purple
            'rgba(0, 150, 136, 0.6)',   // Teal
        ];

        if (this._roomChart) {
            this._roomChart.destroy();
        }

        this._roomChart = new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    label: datasetLabel,
                    data: values,
                    backgroundColor: colors.slice(0, data.length),
                    borderColor: colors.slice(0, data.length).map(c => c.replace('0.6', '1')),
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 }
                        }
                    },
                    title: {
                        display: true,
                        text: 'kgCO₂eq',
                        font: { size: 12, weight: 'normal' },
                        padding: { bottom: 10 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.label}: ${context.parsed.toFixed(2)} kgCO₂eq`
                        }
                    }
                }
            }
        });

        // Add click handler to pie chart
        this._addRoomChartClickHandler(data, canvas);
    }

    _addRoomChartClickHandler(rooms, canvas) {
        canvas.onclick = (event) => {
            const points = this._roomChart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
            if (points.length > 0) {
                const index = points[0].index;
                this._selectedRoom = rooms[index];
                this.showDeviceDetail();
                this.renderDeviceChart();
            }
        };
    }

    showDeviceDetail() {
        const roomChartView = this.querySelector('#room-chart-view');
        const deviceDetailView = this.querySelector('#device-detail-view');
        const roomTitle = this.querySelector('#selected-room-title');

        if (roomChartView && deviceDetailView) {
            roomChartView.style.display = 'none';
            deviceDetailView.style.display = 'block';
            roomTitle.textContent = `Devices in ${this._selectedRoom.room || this._selectedRoom.type}`;
        }
    }

    showRoomChart() {
        const roomChartView = this.querySelector('#room-chart-view');
        const deviceDetailView = this.querySelector('#device-detail-view');

        if (roomChartView && deviceDetailView) {
            roomChartView.style.display = 'block';
            deviceDetailView.style.display = 'none';
            this._selectedRoom = null;
        }
    }

    renderDeviceChart() {
        if (!this._selectedRoom) {
            return;
        }

        const canvas = this.querySelector('#device-bar-chart');
        if (!canvas) {
            return;
        }

        const devices = this._selectedRoom.devices;
        const labels = devices.map(d => d.name);

        const minHeight = 300;
        const heightPerDevice = 40;
        const newHeight = Math.max(minHeight, devices.length * heightPerDevice);

        const canvasContainer = canvas.parentElement;
        if (canvasContainer) {
            canvasContainer.style.height = `${newHeight}px`;
        }

        let values;
        let datasetLabel;
        let breakdown = '';

        // Calculate breakdown text
        const embodiedTotal = devices.reduce((sum, d) => sum + (d.embodied_carbon || 0), 0);
        const usageTotal = devices.reduce((sum, d) => sum + (d.usage_carbon || 0), 0);
        const totalSum = devices.reduce((sum, d) => sum + (d.total_carbon || 0), 0);

        breakdown = `Embodied: ${embodiedTotal.toFixed(2)} kgCO₂eq | Usage: ${usageTotal.toFixed(2)} kgCO₂eq | Total: ${totalSum.toFixed(2)} kgCO₂eq`;
        const breakdownText = this.querySelector('#device-breakdown-text');
        if (breakdownText) {
            breakdownText.textContent = breakdown;
        }

        if (this._deviceChart) {
            this._deviceChart.destroy();
        }

        // Build datasets based on view
        let datasets;
        let stacked = false;

        if (this._carbonView === 'total') {
            // Stacked bars showing embodied and usage
            const embodiedValues = devices.map(d => d.embodied_carbon);
            const usageValues = devices.map(d => d.usage_carbon);
            const predictedValues = devices.map(d => d.predicted_carbon);

            datasets = [
                {
                    label: 'Embodied Carbon',
                    data: embodiedValues,
                    backgroundColor: 'rgba(76, 175, 80, 0.7)',  // Green
                    borderColor: 'rgb(76, 175, 80)',
                    borderWidth: 1,
                },
                {
                    label: 'Usage Carbon',
                    data: usageValues,
                    backgroundColor: 'rgba(33, 150, 243, 0.7)',  // Blue
                    borderColor: 'rgb(33, 150, 243)',
                    borderWidth: 1,
                },
                {
                    label: 'Predicted Carbon (5 years)',
                    data: predictedValues,
                    backgroundColor: 'rgba(243, 33, 33, 0.7)',
                    borderColor: 'rgba(243, 33, 33, 1)',
                    borderWidth: 1,
                }
            ];
            stacked = true;
        } else if (this._carbonView === 'embodied') {
            // Single bars for embodied
            const embodiedValues = devices.map(d => d.embodied_carbon);
            datasets = [
                {
                    label: 'Embodied Carbon',
                    data: embodiedValues,
                    backgroundColor: 'rgba(76, 175, 80, 0.7)',  // Green
                    borderColor: 'rgb(76, 175, 80)',
                    borderWidth: 2,
                }
            ];
        } else {
            // Single bars for usage
            const usageValues = devices.map(d => d.usage_carbon);
            datasets = [
                {
                    label: 'Usage Carbon',
                    data: usageValues,
                    backgroundColor: 'rgba(33, 150, 243, 0.7)',  // Blue
                    borderColor: 'rgb(33, 150, 243)',
                    borderWidth: 2,
                }
            ];
        }

        this._deviceChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',  // Horizontal bar chart
                scales: {
                    x: {
                        stacked: stacked,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'kgCO₂eq',
                            font: { weight: 'bold', size: 12 }
                        },
                        ticks: {
                            callback: (value) => `${value}`
                        }
                    },
                    y: {
                        stacked: stacked,
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.dataset.label}: ${context.parsed.x.toFixed(2)} kgCO₂eq`
                        }
                    }
                },
            }
        });
    }

    attachFormHandler() {
        const form = this.querySelector('#add-device-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData(form);

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        device_name: formData.get('device_name'),
                        device_type: formData.get('device_type'),
                        carbon_footprint: parseFloat(formData.get('carbon_footprint')),
                        metadata: {}
                    });

                    const newData = await this.getCarbonData();
                    await this.render(newData);

                } catch (error) {
                    console.error('Failed to add device:', error);
                    alert(`Error adding device: ${error.message}`);
                }
            });
        }

        const detectBtn = this.querySelector('#detect-devices-btn');
        const loaderAnim = this.querySelector('#loader');
        if (detectBtn) {
            detectBtn.addEventListener('click', async () => {
                this.detectDevicesType(detectBtn, loaderAnim)
                detectBtn.disabled = true;
                loaderAnim.style.display = 'inline-block';
            });
        }

        const exportBtn = this.querySelector('#export-json-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', async () => {
                let jsonArray = await this._hass.callWS({ type: 'carbon_footprint/export_json' });

                const array = JSON.stringify(jsonArray.json_array);
                const uploaded = jsonArray.uploaded
                if (uploaded === 'yes') {
                    alert("Devices have been uploaded to the db interface!");
                }
                else {
                    navigator.clipboard.writeText(array);
                    alert("Devices have been copied to the clipboard! If you wanted to upload to the interface, please make sure db_ip and cfdb_token are set.");
                }
            })
        }

        const computeBtn = this.querySelector('#compute-footprint-btn');
        if (computeBtn) {
            computeBtn.addEventListener('click', () => this.showHardwareDialogAndCompute());
        }

        const extendButtons = this.querySelectorAll('.extend-btn');
        extendButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const deviceInfo = e.currentTarget.closest('.device-info');
                const extendedDiv = deviceInfo.querySelector('.device-extended');

                if (extendedDiv) {
                    const isHidden = extendedDiv.style.display === 'none' || !extendedDiv.style.display;
                    extendedDiv.style.display = isHidden ? 'block' : 'none';

                    e.currentTarget.textContent = isHidden ? '▲' : '▼';
                }
            })
        })

        const deleteButtons = this.querySelectorAll('.delete-btn');
        deleteButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const entityId = e.currentTarget.dataset.entityId;

                if (!confirm(`Remove ${entityId} from tracking?`)) {
                    return;
                }

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/remove_device',
                        device_name: entityId
                    });

                    const newData = await this.getCarbonData();
                    await this.render(newData);

                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }

    attachDeleteHandlers() {
        const deleteButtons = this.querySelectorAll('.delete-btn');
        deleteButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const entityId = e.currentTarget.dataset.entityId;

                if (!confirm(`Remove ${entityId} from tracking?`)) {
                    return;
                }

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/remove_device',
                        device_name: entityId
                    });

                    await this.updateDeviceList();

                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }

    async showHardwareDialogAndCompute(deviceMeta = {}) {
        const initialHsl = {};
        const inferred = null;
        openFullForm(this,initialHsl, null);
    }

}

if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');
