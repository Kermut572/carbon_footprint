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
        this._currentPage = 'main'; // 'main' or 'settings'

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
        if (this._setup)
            this.updateDeviceList();
        else if (this.isConnected) {
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
                </div>
            </ha-app-layout>
        `;

        if (typeof Chart === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
            script.onload = () => {
                this.renderHistogram();
            };
            document.head.appendChild(script);
        } else {
            this.renderHistogram();
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

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.2'; // :skull:
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
                                    ${Object.entries(data.devices).map(([device_name, info]) => `
                                        <li>
                                            <div class="device-info">
                                                <div>
                                                    <b>${device_name}</b><br>
                                                    Type: ${info.type || 'Unknown'}<br>
                                                    Carbon: ${info.carbon_footprint || 0} kgCO₂eq <br>
                                                    Manfucturer: ${info.metadata?.manufacturer || 'N/A'}<br>
                                                    Model: ${info.metadata?.model || 'N/A'}<br>
                                                    Model ID: ${info.metadata?.model_id || 'N/A'}<br>
                                                    Class: ${info.metadata?.device_classes || 'N/A'}<br>
                                                    Total Energy Consumed: ${info.metadata?.total_energy || 'N/A'}<br>
                                                </div>
                                                <button
                                                    type="button"
                                                    class="delete-btn"
                                                    data-entity-id="${device_name}"
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

                    <ha-card header="All Devices">
                        <div class="card-header">
                            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                            <label for="sort-mode" style="font-weight: 500;">Sort by:</label>
                            <select id="sort-mode" style="width : auto; min-width=150px; max-width="200px;">
                                <option value="energy">Energy Consumption</option>
                                <option value="name">Alphabetical</option>
                            </select>
                            </div>
                        </div>
                        <div class="card-content" id="energy-table-container">
                            ${this.renderEnergyTable(energyDevices)}
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
        link.href = '/api/carbon_footprint/style.css?version=1.2'; // :skull:
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

        const computeBtn = this.querySelector('#compute-footprint-btn');
        if (computeBtn) {
            computeBtn.addEventListener('click', () => this.showHardwareDialogAndCompute());
        }

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
