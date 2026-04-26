/**
 * Basic panel for the Carbon Footprint integration. Most of the code is currently ugly and AI-generated
 * for testing purposes. We should rewrite it properly later.
 */

import { CarbonUtils } from './frontend/carbon-utils.js';
import { openFullForm } from './frontend/form-manager.js';
import { Utils } from './utils.js';
import {
    getHighImpactAreaRecommendation,
    getCarbonIntensityRecommendation,
    getIoTShareRecommendation,
    getUsagePatternRecommendation,
} from './frontend/recommendation-manager.js';

class CarbonFootprintPanel extends HTMLElement {

    constructor() {
        super();
        this._devices = [];
        this._setup = false
        this._histogramData = null;
        this._chart = null;
        this._roomChart = null;
        this._deviceChart = null;
        this._consumptionChart = null;
        this._roomData = null;
        this._selectedRoom = null;
        this._currentPage = 'main'; // 'main' or 'settings'
        this._carbonView = 'total'; // 'total', 'embodied', or 'usage'
        this._ecView = 'total';
        this._groupBy = 'room'; // 'room' or 'type'
        this._currentDevice = null;
        this._currentType = null;
        this._currentCarbonValue = 0.0;

        this._hiddenDeviceIndices = new Set();

        this._chartGranularity = {
            HOUR: "hour",
            DAY: "day",
            MONTH: "month"
        };
        this._currentChartGranularity = this._chartGranularity.DAY;

        this._timeFrame = {
            WEEK: "last-week",
            MONTH: "last-month",
            YEAR: "last-year"
        };
        this._currentTimeFrame = this._timeFrame.MONTH;
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
        //console.log('Getting carbon data from backend');
        return await CarbonUtils.getCarbonData(this);
    }

    async getAllDevicesEnergy() {
        return await CarbonUtils.getAllDevicesEnergy(this);
    }

    async updateDeviceEnergy() {
        return await CarbonUtils.updateDeviceEnergy(this);
    }

    async getCarbonByRoom() {
        try {
            // Support test data toggle for recommendations testing
            if (this._useFakeRoomData) {
                const fakeData = this._getFakeRoomData();
                console.log('Using fake room data (test_data.py) for testing:', fakeData);
                this._roomData = fakeData || [];
                return this._roomData;
            }

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

        const yearlyConsCall = await this._hass.callWS({ type: 'carbon_footprint/get_yearly_contribution' });
        const yearlyCons = yearlyConsCall.yearly_contribution;
        console.log(`Found ${yearlyCons}kWh for this year.`)

        const emissionNowRaw = this._hass.states['sensor.carbon_emission_now']?.state;
        const carbonTodayRaw = this._hass.states['sensor.carbon_total_today']?.state;

        const emissionNow = emissionNowRaw && emissionNowRaw !== 'unknown' && emissionNowRaw !== 'unavailable'
            ? parseFloat(emissionNowRaw)
            : null;

        const carbonToday = carbonTodayRaw && carbonTodayRaw !== 'unknown' && carbonTodayRaw !== 'unavailable'
            ? parseFloat(carbonTodayRaw)
            : null;

        // Fetch room data and generate recommendation
        console.log('Fetching room data for recommendation...');
        const roomData = await this.getCarbonByRoom();
        const recommendation = getHighImpactAreaRecommendation(roomData);

        // Generate carbon intensity recommendation
        const intensityRec = getCarbonIntensityRecommendation(data?.co2_intensity);
        const iotShareRec = getIoTShareRecommendation(yearlyCons);

        // Fetch consumption data for usage vs intensity recommendation (last 30 days)
        const recEndTime = new Date();
        const recStartTime = new Date(recEndTime);
        recStartTime.setDate(recEndTime.getDate() - 30);
        const recResult = await this._hass.callWS({
            type: 'carbon_footprint/get_consumption_footprint_time_interval',
            start_time: recStartTime.toISOString(),
            end_time: recEndTime.toISOString(),
            granularity: 'day'
        });
        const energyData = recResult.devices_consumptions;
        const intensityData = data?.intensity_history || []; // TODO: implement intensity_history in backend if needed
        const usagePatternRec = getUsagePatternRecommendation(
            energyData,
            intensityData,
            data?.co2_intensity
        );

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <h1>Carbon Footprint</h1>
                    <button id="settings-btn" style="position: absolute; right: 20px; top: 15px; padding: 8px 16px; background-color: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">Settings</button>
                </header>

                <div class="content" slot="content">
                    <ha-card header="Energy Consumption Footprint">
                        <div class="card-content">
                            <p>Current Energy CO₂ Intensity:
                                <span class="ci-value">
                                    <b>${data?.co2_intensity_status === 'fallback'
                                        ? 'Unknown'
                                        : (data?.co2_intensity ?? 'N/A')}</b>
                                </span>
                                ${data?.co2_intensity_status === 'fallback' ? '' : 'gCO₂eq/kWh'}
                                <span class="ci-indicator ${CarbonUtils.getCarbonColor(
                                    data?.co2_intensity_status === 'fallback' ? null : data?.co2_intensity
                                )}"></span>
                                <span class="ci-label">${CarbonUtils.getCarbonLabel(
                                    data?.co2_intensity_status === 'fallback' ? null : data?.co2_intensity
                                )}</span>
                            </p>
                            <p style="font-size: 12px; color: #666; margin-top: 8px; margin-bottom: 16px;">
                                <em>Devices energy consumption footprint over time (in grams CO₂ equivalent)</em>
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

                            <div style="margin-bottom: 12px;">
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="total" checked style="margin-right: 6px;">
                                        <span>Total (Stacked)</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="embodied" style="margin-right: 6px;">
                                        <span>Embodied Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="usage" style="margin-right: 6px;">
                                        <span>Usage Only</span>
                                    </label>
                                </div>
                            </div>
                            <div style="position: relative; height: 400px; width: 100%;">
                                <canvas id="consumption-histogram-chart"></canvas>
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
                    <ha-card header="Recommendations">
                        <div class="card-content">
                            <div style="display: flex; flex-direction: column; gap: 8px;">


                                <!-- Current yearly cons -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: ${
                                            '#e8f5e9'
                                        }; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-0').style.display = this.parentElement.querySelector('.recommendation-content-0').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-0').textContent = this.parentElement.querySelector('.recommendation-content-0').style.display === 'none' ? '▼' : '▲';">
                                        <strong>IoT share of consumption</strong>
                                        <span class="toggle-icon-0" style="font-size: 12px;">▲</span>
                                    </div>

                                    <div class="recommendation-content-0"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${iotShareRec.message}
                                        </p>
                                    </div>
                                </div>

                                <!-- Carbon intensity usage -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: ${intensityRec.color}; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-2').style.display = this.parentElement.querySelector('.recommendation-content-2').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-2').textContent = this.parentElement.querySelector('.recommendation-content-2').style.display === 'none' ? '▼' : '▲';">
                                        <strong>${intensityRec.emoji} Optimize Usage Timing (${intensityRec.label})</strong>
                                        <span class="toggle-icon-2" style="font-size: 12px;">▲</span>
                                    </div>
                                    <div class="recommendation-content-2"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${intensityRec.message}
                                        </p>
                                    </div>
                                </div>

                                <!-- Usage Pattern Insight -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: ${usagePatternRec.color}; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-pattern').style.display = this.parentElement.querySelector('.recommendation-content-pattern').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-pattern').textContent = this.parentElement.querySelector('.recommendation-content-pattern').style.display === 'none' ? '▼' : '▲';">
                                        <strong>${usagePatternRec.emoji} ${usagePatternRec.title}</strong>
                                        <span class="toggle-icon-pattern" style="font-size: 12px;">▲</span>
                                    </div>
                                    <div class="recommendation-content-pattern"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${usagePatternRec.message}
                                        </p>
                                    </div>
                                </div>

                                <!-- High-Impact Area Recommendation -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: #fff8e1; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-high-impact').style.display = this.parentElement.querySelector('.recommendation-content-high-impact').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-high-impact').textContent = this.parentElement.querySelector('.recommendation-content-high-impact').style.display === 'none' ? '▼' : '▲';">
                                        <strong> ${recommendation.title}</strong>
                                        <span class="toggle-icon-high-impact" style="font-size: 12px;">▲</span>
                                    </div>
                                    <div class="recommendation-content-high-impact"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${recommendation.message}
                                        </p>
                                    </div>
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
                //this.renderHistogram();
                await this.renderRoomChart();
                await this.renderConsumptionHistogram();
            };
            document.head.appendChild(script);
        } else {
            //this.renderHistogram();
            await this.renderRoomChart();
            await this.renderConsumptionHistogram();
        }

        const energyConsumptionRadios = this.querySelectorAll('input[name="ec-view"]');
        for (const radio of energyConsumptionRadios) {
            radio.addEventListener('change', async (e) => {
                this._ecView = e.target.value;
                await this.renderConsumptionHistogram();
            });
        }

        const granSelect = this.querySelector('#granularity-select');
        if (granSelect) {
            granSelect.value = this._currentChartGranularity;
            granSelect.addEventListener('change', async (e) => {
                this._currentChartGranularity = e.target.value;
                await this.renderConsumptionHistogram();
            });
        }

        const timeFrameSelect = this.querySelector('#time-frame-select');
        if (timeFrameSelect) {
            timeFrameSelect.value = this._currentTimeFrame;
            timeFrameSelect.addEventListener('change', async (e) => {
                this._currentTimeFrame = e.target.value;
                await this.renderConsumptionHistogram();
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


    setCarbonValue(value) {
        this._currentCarbonValue = value;
        const carbonSelector = this.querySelector('#device_carbon_footprint');
        carbonSelector.value = this._currentCarbonValue;
    }

    renderForm(devices) {

        return `

            <form id="add-device-form">
                <div>
                    <label for="device_name">Device</label>
                    <ha-selector id="device_selector"></ha-selector>
                </div>
                <div>
                    <label for="device_type">Device Type</label>
                    <ha-selector id="device_type_selector"></ha-selector>
                </div>
                <div>
                    <label for="carbon_footprint">Carbon Footprint (kgCO₂eq)</label>
                    <ha-selector id="device_carbon_footprint"></ha-selector>
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

    showLoadingOverlay(message = 'Loading...') {
        this.hideLoadingOverlay();

        const overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-content">
                <div class="spinner"></div>
                <p>${message}</p>
                <div class="progress-cont">
                    <div class="progress-bar"></div>
                </div>
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

        let nbDevices = deviceNames.length;
        let chunkSize = Math.round(nbDevices / 10);
        let successfulBatches = 0;

        const totalRuns = Math.max(1, Math.ceil(nbDevices / chunkSize));
        const percentIncrement = Math.round(100 / totalRuns);

        try {
            this.showLoadingOverlay('Detecting device types...');
            const progressBar = this.querySelector(".progress-bar");

            progressBar.style.width = '0%';
            console.log(`Chunked data dictionary into chunks of ${chunkSize} devices`)

            for (let i = 0; i < nbDevices; i += chunkSize) {
                const chunkDevicesDict = Object.fromEntries(Object.entries(devicesDict).slice(i, i + chunkSize));
                const chunkDeviceIds = deviceIds.slice(i, i + chunkSize);
                console.log(`Running device type detection, run ${i/chunkSize}. Sent devices are: ${JSON.stringify(chunkDevicesDict, null, '\t')}`);
                try {
                    const llmResp = await this._hass.callWS({
                        type: 'carbon_footprint/llm_detection',
                        devices: chunkDevicesDict
                    });
                    let deviceTypes = JSON.parse(llmResp.device_types || "{}");
                    Object.keys(chunkDevicesDict).forEach((key, idx) => {
                        devicesDict[key].device_type = deviceTypes[key] ?? "unknown";
                        devicesDict[key].device_id = chunkDeviceIds[idx] ?? null;
                    });
                    console.log(`Batch ${i / chunkSize} successfully detected, continuing`);
                    successfulBatches++;
                } catch (error) {
                    console.error(`Failed detection for batch ${i/chunkSize} with error: ${error.message || error.code}`);
                    let j = 0;
                    Object.keys(chunkDevicesDict).forEach((key, idx) => {
                        devicesDict[key].device_type = "error";
                        devicesDict[key].device_id = chunkDeviceIds[idx] ?? null;
                    });
                } finally {
                    const current = parseFloat(progressBar.style.width) || 0;
                    progressBar.style.width = `${Math.min(100, current + percentIncrement)}%`;
                }
            }
            console.log('Device Types Detection ended, continuing...');

            const devicesToSend = Object.fromEntries(
                Object.entries(devicesDict).filter(([name, info]) => {
                    const t = info?.device_type;
                    return typeof t === 'string' && t.length > 0 && t !== 'error';
                })
            );
            this.showLoadingOverlay('Matching devices with database...');

            console.log(`Sending ${JSON.stringify(devicesToSend, null, '\t')}`)
            const dbMatchingResp = await this._hass.callWS({
                type: 'carbon_footprint/db_matching',
                device_types: devicesToSend,
            });
            let devicesMatched = dbMatchingResp.devices_matched;
            console.log(`Matched ${JSON.stringify(devicesMatched, null, '\t')}`)


            //flow: Once we got the device types: pull the db and match carbon values, this will automatically setup everything where possible.
            //idea: pass the device_types json as argument for another websocket, which will return another json in the following format:
            //{
            //  "<device_name>" : {
            //      "device_type": "<type>"
            //      "carbon_footprint": "<value>"
            //  }
            //}
            //then use this for set_device

            if (progressBar) progressBar.style.width = '100%';
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
            if (successfulBatches !== 0)
                Utils.showToast(this, `Successfully detected ${successfulBatches}/${totalRuns} device batches`)
            else
                Utils.showToast(this, `LLM detection failed on every batch. Check console logs for more information`)
        }
    }

    async renderConsumptionHistogram() {
        const canvas = this.querySelector('#consumption-histogram-chart');
        if (!canvas) {
            return;
        }

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
        }

        const endTime = new Date();
        const startTime = new Date(endTime);
        startTime.setDate(endTime.getDate() - pastDays);

        const result = await this._hass.callWS({
            type: 'carbon_footprint/get_consumption_footprint_time_interval',
            start_time: startTime.toISOString(),
            end_time: endTime.toISOString(),
            granularity: this._currentChartGranularity
        });


        const consumptionData = result.devices_consumptions;
        //if (!consumptionData || Object.keys(consumptionData).length === 0) {
        //    canvas.parentElement.innerHTML = '<p>No consumption data available for the selected period.</p>';
        //    return;
        //}

        const embodiedResult = (this._ecView == 'total' || this._ecView == 'embodied') ? await this._hass.callWS({
            type: 'carbon_footprint/get_embodied_carbon_time_interval',
            start_time: startTime.toISOString(),
            end_time: endTime.toISOString(),
            granularity: this._currentChartGranularity
        }) : {};

        const embodiedData = embodiedResult.embodied_carbon || {};

        const deviceNames = result.device_name_map;
        const aggData = {};

        const procData = (data, type) => {
            for (const deviceId in data) {
                if (data[deviceId]) {
                    data[deviceId].forEach(point => {
                        const date = new Date(point.timestamp);
                        const groupKey = Utils.getDateGroupKey(date, this._currentChartGranularity, this._chartGranularity);

                        if (!aggData[groupKey]) {
                            aggData[groupKey] = {};
                        }
                        if (!aggData[groupKey][deviceId]) {
                            aggData[groupKey][deviceId] = { consumption: 0, embodied: 0 };
                        }
                        aggData[groupKey][deviceId][type] += point.consumption_footprint || point.embodied_footprint || 0;
                    });
                }
            }
        };
        if (this._ecView == 'total' || this._ecView == 'usage') procData(consumptionData, `consumption`);
        procData(embodiedData, `embodied`);
        const sortedTimestamps = Object.keys(aggData).sort();

        const labels = sortedTimestamps.map(ts => {
            const date = new Date(ts);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit' });
                case this._chartGranularity.DAY:
                    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
                case this._chartGranularity.MONTH:
                    return date.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });
                default:
                    return date.toLocaleString();
            }
        });

        const baseColors = [
            'rgba(76, 175, 80, 0.6)',
            'rgba(33, 150, 243, 0.6)',
            'rgba(255, 152, 0, 0.6)',
            'rgba(244, 67, 54, 0.6)',
            'rgba(156, 39, 176, 0.6)',
            'rgba(0, 150, 136, 0.6)',
            'rgba(255, 235, 59, 0.6)',
            'rgba(121, 85, 72, 0.6)',
        ];

        const datasets = [];
        const ctx = canvas.getContext('2d');

        Object.keys(consumptionData).forEach((deviceId, index) => {
            const baseColor = baseColors[index % baseColors.length];
            const deviceName = deviceNames[deviceId];

            // embodied
            const embodiedDataPoints = sortedTimestamps.map(ts => (aggData[ts] && aggData[ts][deviceId]?.embodied) || 0);
            datasets.push({
                label: `${deviceName} (Embodied)`,
                data: this._hiddenDeviceIndices.has(index) ? embodiedDataPoints.map(() => 0) : embodiedDataPoints,
                backgroundColor: (this._ecView === 'total') ? this._createHatchPattern(ctx, baseColor) : baseColor,
                deviceIndex: index,
                stack: deviceId,
            });

            // usage data
            const usageData = sortedTimestamps.map(ts => (aggData[ts] && aggData[ts][deviceId]?.consumption) || 0);
            datasets.push({
                label: `${deviceName} (Usage)`,
                data: this._hiddenDeviceIndices.has(index) ? usageData.map(() => 0) : usageData,
                backgroundColor: baseColor,
                deviceIndex: index,
                stack: deviceId,
            });

        });

        if (this._consumptionChart) {
            this._consumptionChart.destroy();
        }

        this._consumptionChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 },
                            generateLabels: () => {
                                const deviceLabels = Object.keys(consumptionData).map((deviceId, index) => {
                                    const isHidden = this._hiddenDeviceIndices.has(index);
                                    return {
                                        text: deviceNames[deviceId],
                                        fillStyle: baseColors[index % baseColors.length],
                                        hidden: isHidden,
                                        strikethrough: isHidden,
                                        deviceIndex: index,
                                        datasetIndex: index * 2
                                    };
                                });
                                if (this._ecView === 'total') {
                                    deviceLabels.push({
                                        text: 'Embodied (hatched)',
                                        fillStyle: this._createHatchPattern(ctx, 'rgba(120, 120, 120, 0.6)'),
                                        deviceIndex: Object.keys(consumptionData).length
                                    });
                                    deviceLabels.push({
                                        text: 'Usage (solid)',
                                        fillStyle: 'rgba(120, 120, 120, 0.6)',
                                        deviceIndex: Object.keys(consumptionData).length + 1
                                    });
                                }

                                return deviceLabels;
                            }
                        },
                        onClick: (e, legendItem) => {
                            const deviceIndex = legendItem.deviceIndex;

                            if (deviceIndex === undefined || deviceIndex >= Object.keys(consumptionData).length) {
                                return;
                            }

                            if (this._hiddenDeviceIndices.has(deviceIndex)) {
                                this._hiddenDeviceIndices.delete(deviceIndex);
                            } else {
                                this._hiddenDeviceIndices.add(deviceIndex);
                            }
                            this.renderConsumptionHistogram();
                        },
                    },
                    title: {
                        display: true,
                        text: 'Energy Consumption Footprint (gCO₂eq)',
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(4)} gCO₂eq`
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'gCO₂eq'
                        }
                    }
                }
            }
        });
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
                    borderWidth: 0,
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

    _createHatchPattern(ctx, color) { // made with the help of chatgpt
        const patternCanvas = document.createElement('canvas');
        patternCanvas.width = 16;
        patternCanvas.height = 16;

        const pctx = patternCanvas.getContext('2d');

        pctx.fillStyle = color;
        pctx.fillRect(0, 0, patternCanvas.width, patternCanvas.height);

        // diagonal hatch lines
        pctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
        pctx.lineWidth = 1.5;

        pctx.beginPath();
        pctx.moveTo(0, 16);
        pctx.lineTo(16, 0);
        pctx.stroke();

        pctx.beginPath();
        pctx.moveTo(-4, 12);
        pctx.lineTo(4, 4);
        pctx.stroke();

        pctx.beginPath();
        pctx.moveTo(12, 20);
        pctx.lineTo(20, 12);
        pctx.stroke();

        return ctx.createPattern(patternCanvas, 'repeat');
    }

    // ============================================================================
    // TEST DATA TOGGLES
    // ============================================================================
    // _useFakeCarbonData: Uses generic fake lab data (Kitchen, Bedroom, etc.)
    //   - Good for UI/visualization testing
    //   - Doesn't depend on backend or real devices
    //
    // _useFakeRoomData: Uses test data from test_data.py (requires TEST_MODE=True)
    //   - Good for recommendation system testing
    //   - Matches real device structure (Living Room, Kitchen, Bedroom)
    //   - Doesn't interfere with real device data collection
    //
    // Set either to true to enable test mode. Example:
    //   this._useFakeRoomData = true;  // Test recommendations without real devices
    // ============================================================================

    // turn on/off fake data here
    _useFakeCarbonData = false;
    _useFakeRoomData = false;  // Toggle for test data (from test_data.py) - doesn't affect real devices
    _hiddenRoomIndices = new Set();

    _getFakeCarbonData() {
        return [
            {
                room: 'Kitchen',
                embodied_carbon: 120,
                usage_carbon: 80,
                total_carbon: 200,
                predicted_carbon: 260,
                devices: [
                    { name: 'Fridge', embodied_carbon: 50, usage_carbon: 30, total_carbon: 80, predicted_carbon: 100 },
                    { name: 'Oven', embodied_carbon: 40, usage_carbon: 25, total_carbon: 65, predicted_carbon: 85 },
                    { name: 'Dishwasher', embodied_carbon: 30, usage_carbon: 25, total_carbon: 55, predicted_carbon: 75 },
                ]
            },
            {
                room: 'Bedroom',
                embodied_carbon: 90,
                usage_carbon: 110,
                total_carbon: 200,
                predicted_carbon: 250,
                devices: [
                    { name: 'Lamp', embodied_carbon: 10, usage_carbon: 20, total_carbon: 30, predicted_carbon: 35 },
                    { name: 'Heater', embodied_carbon: 35, usage_carbon: 60, total_carbon: 95, predicted_carbon: 125 },
                    { name: 'Fan', embodied_carbon: 15, usage_carbon: 10, total_carbon: 25, predicted_carbon: 30 },
                    { name: 'TV', embodied_carbon: 30, usage_carbon: 20, total_carbon: 50, predicted_carbon: 60 },
                ]
            },
            {
                room: 'Living Room',
                embodied_carbon: 70,
                usage_carbon: 30,
                total_carbon: 100,
                predicted_carbon: 140,
                devices: [
                    { name: 'TV', embodied_carbon: 25, usage_carbon: 10, total_carbon: 35, predicted_carbon: 45 },
                    { name: 'Speaker', embodied_carbon: 15, usage_carbon: 5, total_carbon: 20, predicted_carbon: 28 },
                    { name: 'Game Console', embodied_carbon: 30, usage_carbon: 15, total_carbon: 45, predicted_carbon: 67 },
                ]
            },
            {
                room: 'Unknown Room',
                embodied_carbon: 20,
                usage_carbon: 15,
                total_carbon: 35,
                predicted_carbon: 50,
                devices: [
                    { name: 'Unknown Device A', embodied_carbon: 10, usage_carbon: 5, total_carbon: 15, predicted_carbon: 20 },
                    { name: 'Unknown Device B', embodied_carbon: 10, usage_carbon: 10, total_carbon: 20, predicted_carbon: 30 },
                ]
            }
        ];
    }

    _getFakeRoomData() {
        // Test data matching test_data.py structure from async_setup_test_data
        // This provides consistent test data for the recommendation system
        return [
            {
                room: 'Bedroom',
                room_id: 'fake_bedroom',
                embodied_carbon: 12.0,
                usage_carbon: 1.8,
                predicted_carbon: 2.7,
                total_carbon: 13.8,
                devices: [
                    { id: 'Bedroom AC Unit', name: 'Bedroom AC Unit', embodied_carbon: 12.0, usage_carbon: 1.8, predicted_carbon: 2.7, total_carbon: 13.8 }
                ]
            },
            {
                room: 'Kitchen',
                room_id: 'fake_kitchen',
                embodied_carbon: 58.0,
                usage_carbon: 3.5,
                predicted_carbon: 5.25,
                total_carbon: 61.5,
                devices: [
                    { id: 'Kitchen Refrigerator', name: 'Kitchen Refrigerator', embodied_carbon: 35.0, usage_carbon: 2.5, predicted_carbon: 3.75, total_carbon: 37.5 },
                    { id: 'Kitchen Dishwasher', name: 'Kitchen Dishwasher', embodied_carbon: 18.5, usage_carbon: 0.8, predicted_carbon: 1.2, total_carbon: 19.3 },
                    { id: 'Kitchen Coffee Maker', name: 'Kitchen Coffee Maker', embodied_carbon: 4.5, usage_carbon: 0.2, predicted_carbon: 0.3, total_carbon: 4.7 }
                ]
            },
            {
                room: 'Living Room',
                room_id: 'fake_living_room',
                embodied_carbon: 45.0,
                usage_carbon: 3.8,
                predicted_carbon: 5.7,
                total_carbon: 48.8,
                devices: [
                    { id: 'Living Room TV', name: 'Living Room TV', embodied_carbon: 15.5, usage_carbon: 0.5, predicted_carbon: 0.75, total_carbon: 16.0 },
                    { id: 'Living Room Heater', name: 'Living Room Heater', embodied_carbon: 22.3, usage_carbon: 3.2, predicted_carbon: 4.8, total_carbon: 25.5 },
                    { id: 'Living Room Smart Speaker', name: 'Living Room Smart Speaker', embodied_carbon: 7.2, usage_carbon: 0.1, predicted_carbon: 0.15, total_carbon: 7.35 }
                ]
            }
        ];
    }

    async renderRoomChart() {
        const canvas = this.querySelector('#room-pie-chart');
        if (!canvas) {
            return;
        }

        let data;
        if (this._useFakeCarbonData) {
            data = this._getFakeCarbonData();
            console.log('Using fake carbon data for room chart:', data);
        } else if (this._useFakeRoomData) {
            // Use test data from test_data.py (only for testing recommendation system)
            data = this._getFakeRoomData();
            console.log('Using fake room data (test_data.py) for testing:', data);
        } else if (this._groupBy === 'type') {
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

        const ctx = canvas.getContext('2d');

        const baseColors = [
            'rgba(76, 175, 80, 0.6)',   // Green
            'rgba(33, 150, 243, 0.6)',  // Blue
            'rgba(255, 152, 0, 0.6)',   // Orange
            'rgba(244, 67, 54, 0.6)',   // Red
            'rgba(156, 39, 176, 0.6)',  // Purple
            'rgba(0, 150, 136, 0.6)',   // Teal
        ];

        const solidBorderColors = baseColors.map(c => c.replace('0.6', '1'));

        if (this._roomChart) {
            this._roomChart.destroy();
        }

        let chartData;
        let chartOptions;

        if (this._carbonView === 'total') {
            const labels = [];
            const values = [];
            const backgroundColors = [];
            const borderColors = [];

            data.forEach((item, index) => {
                const label = item.room || item.type || 'Unknown';
                const baseColor = baseColors[index % baseColors.length];
                const borderColor = solidBorderColors[index % solidBorderColors.length];
                const hatchPattern = this._createHatchPattern(ctx, baseColor);

                const isHidden = this._hiddenRoomIndices.has(index);

                // embodied slice
                labels.push(`${label} - Embodied`);
                values.push(isHidden ? 0 : (item.embodied_carbon || 0));
                backgroundColors.push(hatchPattern);
                borderColors.push(borderColor);

                // usage slice
                labels.push(`${label} - Usage`);
                values.push(isHidden ? 0 : (item.usage_carbon || 0));
                backgroundColors.push(baseColor);
                borderColors.push(borderColor);
            });

            chartData = {
                labels,
                datasets: [{
                    label: 'Total Carbon',
                    data: values,
                    backgroundColor: backgroundColors,
                    borderWidth: 0,
                    hoverBorderWidth: 0,
                    spacing: 0,
                }]
            };

            chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 },
                            generateLabels: () => {
                                const roomItems = data.map((item, index) => {
                                    const label = item.room || item.type || 'Unknown';
                                    const color = baseColors[index % baseColors.length];
                                    const borderColor = solidBorderColors[index % solidBorderColors.length];
                                    const isHidden = this._hiddenRoomIndices.has(index);

                                    return {
                                        text: label,
                                        fillStyle: color,
                                        strokeStyle: borderColor,
                                        lineWidth: 2,
                                        hidden: isHidden,
                                        index
                                    };
                                });

                                roomItems.push({
                                    text: 'Embodied (hatched)',
                                    fillStyle: this._createHatchPattern(ctx, 'rgba(120, 120, 120, 0.6)'),
                                    strokeStyle: '#666',
                                    lineWidth: 2,
                                    hidden: false,
                                    index: data.length
                                });

                                roomItems.push({
                                    text: 'Usage (solid)',
                                    fillStyle: '#999',
                                    strokeStyle: '#666',
                                    lineWidth: 2,
                                    hidden: false,
                                    index: data.length + 1
                                });

                                return roomItems;
                            }
                        },
                        onClick: (event, legendItem, legend) => {
                            const roomIndex = legendItem.index;

                            // Ignore the explanatory style legend items
                            if (roomIndex >= data.length) {
                                return;
                            }

                            if (this._hiddenRoomIndices.has(roomIndex)) {
                                this._hiddenRoomIndices.delete(roomIndex);
                            } else {
                                this._hiddenRoomIndices.add(roomIndex);
                            }

                            this.renderRoomChart();
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
                            label: (context) => {
                                const roomIndex = Math.floor(context.dataIndex / 2);
                                const item = data[roomIndex];

                                const name = item.room || item.type || 'Unknown';
                                const embodied = item.embodied_carbon || 0;
                                const usage = item.usage_carbon || 0;
                                const total = item.total_carbon || (embodied + usage);

                                return [
                                    `${name}`,
                                    `Embodied: ${embodied.toFixed(2)} kgCO₂eq`,
                                    `Usage: ${usage.toFixed(2)} kgCO₂eq`,
                                    `Total: ${total.toFixed(2)} kgCO₂eq`
                                ];
                            }
                        }
                    }
                }
            };
        } else {
            const labels = data.map(item => item.room || item.type || 'Unknown');
            let values;
            let datasetLabel;

            if (this._carbonView === 'embodied') {
                values = data.map(item => item.embodied_carbon || 0);
                datasetLabel = 'Embodied Carbon';
            } else {
                values = data.map(item => item.usage_carbon || 0);
                datasetLabel = 'Usage Carbon';
            }

            chartData = {
                labels,
                datasets: [{
                    label: datasetLabel,
                    data: values,
                    backgroundColor: baseColors.slice(0, data.length),
                    borderWidth: 0,
                    hoverBorderWidth: 0,
                    spacing: 0,
                }]
            };

            chartOptions = {
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
            };
        }

        this._roomChart = new Chart(ctx, {
            type: 'doughnut',
            data: chartData,
            options: chartOptions
        });

        this._addRoomChartClickHandler(data, canvas);
    }

    _addRoomChartClickHandler(rooms, canvas) {
        canvas.onclick = (event) => {
            const points = this._roomChart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
            if (points.length > 0) {
                let index = points[0].index;
                if (this._carbonView === 'total') {
                    index = Math.floor(index / 2);
                }
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
                    borderWidth: 0,
                },
                {
                    label: 'Predicted Carbon (5 years)',
                    data: predictedValues,
                    backgroundColor: 'rgba(243, 33, 33, 0.7)',
                    borderColor: 'rgba(243, 33, 33, 1)',
                    borderWidth: 0,
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
                    borderWidth: 0,
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
                    borderWidth: 0,
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
        const suggestions = [
            "Temperature/humidity sensor",
            "Motion sensor",
            "Luminosity sensor",
            "Air quality sensor",
            "Camera",
            "Speaker",
            "Light bulb",
            "Smart plug",
            "Smart lock",
            "Window/door sensor",
            "Thermostat",
            "Energy monitor",
            "Washing machine",
            "TV",
            "Refrigerator",
            "Dishwasher",
        ];

        const carbonSelector = this.querySelector('#device_carbon_footprint');
        if (carbonSelector) {
            try {
                carbonSelector.hass = this._hass;
                carbonSelector.selector = {
                    number: {
                        min: 0.00,
                        step: 0.01
                    },
                };

                carbonSelector.required = true;
                carbonSelector.value = this._currentCarbonValue;
                carbonSelector.addEventListener('value-changed', (ev) => { this._currentCarbonValue = ev.detail.value; })
            } catch (err) {
                console.debug('Failed to init ha-selector-number', err);
            }
        }

        const typeSelector = this.querySelector('#device_type_selector');
        if (typeSelector) {
            //console.log('Loaded device type selector')
            try {
                typeSelector.hass = this._hass;
                typeSelector.selector = {
                    select: {
                        options: suggestions,
                        custom_value: true,
                        sort: true,
                    },
                };

                typeSelector.value = this._currentType ?? '';
                typeSelector.label = 'Device Type';
                typeSelector.addEventListener('value-changed', async (ev) => {
                    this._currentType = ev.detail.value; console.log(`Type is now ${this._currentType}`); typeSelector.value = ev.detail.value;
                    const embodiedTypeResp = await this._hass.callWS({ type: 'carbon_footprint/get_type_embodied_footprint', device_type: this._currentType });
                    const embodiedVal = embodiedTypeResp.carbon_footprint;
                    this._currentCarbonValue = embodiedVal;
                    carbonSelector.value = this._currentCarbonValue;
                });
            } catch (err) {
                console.debug('Failed to init ha-selector-select', err);
            }

        }

        const selector = this.querySelector('#device_selector');
        if (selector) {
            try {
                selector.hass = this._hass;
                selector.selector = {
                    device: {},
                };
                selector.value = this._currentDevice ?? '';
                selector.required = true;
                selector.addEventListener('value-changed', async (ev) => {
                    this._currentDevice = ev.detail.value;
                    const autoComp = await this._hass.callWS({ type: 'carbon_footprint/get_device_autocomp', device_id: this._currentDevice });
                    this._currentType = autoComp.type;
                    typeSelector.value = this._currentType;
                    this._currentCarbonValue = autoComp.cf;
                    carbonSelector.value = this._currentCarbonValue;
                });
            } catch (err) {
                console.debug('Failed to init ha-selector', err);
            }
        }



        const form = this.querySelector('#add-device-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData(form);

                try {

                    if (this._currentDevice === null || this._currentDevice === '' || this._currentType === null || this._currentType === '') {
                        Utils.showToast(this, "Please fill out all the fields.");
                        return;
                    }

                    await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        device_id: this._currentDevice,
                        device_type: this._currentType,
                        carbon_footprint: this._currentCarbonValue,
                        metadata: {}
                    });

                    this._currentDevice = '';
                    this._currentType = '';
                    this._currentCarbonValue = 0.0;
                    const newData = await this.getCarbonData();
                    Utils.showToast(this, 'Successfully added device!');
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
                    Utils.showToast(this, "Devices have been uploaded to the db interface!");
                }
                else {
                    navigator.clipboard.writeText(array);
                    Utils.showToast(this, "Devices have been copied to the clipboard! If you wanted to upload to the interface, please make sure db_ip and cfdb_token are correct and set.");
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
                    Utils.showToast(this, "Successfully untracked device!");
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
