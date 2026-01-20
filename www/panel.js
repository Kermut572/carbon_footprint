/**
 * Main panel component for the Carbon Footprint integration.
 */

import { HistogramManager } from './frontend/histogram-manager.js';
import { DeviceManager } from './frontend/device-manager.js';
import { FormManager } from './frontend/form-manager.js';
import { EnergyTableManager } from './frontend/energy-table-manager.js';
import { CarbonUtils } from './frontend/carbon-utils.js';

class CarbonFootprintPanel extends HTMLElement {
    constructor() {
        super();
        this._hass = null;
        this._setup = false;

        this.histogramManager = new HistogramManager();
        this.deviceManager = new DeviceManager();
        this.formManager = new FormManager();
        this.energyTableManager = new EnergyTableManager();
    }

    async connectedCallback() {
        const data = await this.getCarbonData();
        await this.render(data);
        this._setup = true;
    }

    set hass(hass) {
        this._hass = hass;
        this.histogramManager.setHass(hass);
        this.deviceManager.setHass(hass);
        this.formManager.setHass(hass);
        this.energyTableManager.setHass(hass);

        if (this._setup) {
            this.updateDeviceList();
        } else if (this.isConnected) {
            this.connectedCallback();
        }
    }

    get hass() {
        return this._hass;
    }

    async getCarbonData() {
        return await this._hass.callWS({
            type: 'carbon_footprint/get_data',
        });
    }

    async updateDeviceList() {
        await this.deviceManager.updateDevicesEnergy(this._hass);
        const data = await this.getCarbonData();
        await this.deviceManager.renderDeviceList(
            this.querySelector('.device-list-container'),
            data,
            this._hass
        );
    }

    async render(data) {
        const devicesResp = await this._hass.callWS({
            type: 'carbon_footprint/get_devices_to_add',
        });
        const devicesArray = devicesResp.device_names || [];

        const allDevicesEnergyResp = await this.deviceManager.getAllDevicesEnergy(
            this._hass
        );
        const energyDevices = allDevicesEnergyResp.devices_energy || [];
        energyDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);

        const energyHistogram = await this.histogramManager.getEnergyHistogram(
            this._hass
        );

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header">
                    <h1>Carbon Footprint</h1>
                </header>

                <div class="content" slot="content">
                    ${this.renderCarbonIntensityCard(data)}
                    ${this.renderAddDeviceCard(devicesArray)}
                    ${this.renderConfiguredDevicesCard(data)}
                    ${this.renderAllDevicesCard(energyDevices)}
                </div>
            </ha-app-layout>
        `;

        this.attachStylesheet();
        this.histogramManager.initialize(
            this,
            energyHistogram,
            this._hass
        );
        this.formManager.attachHandlers(
            this.querySelector('#add-device-form'),
            this.querySelector('#compute-footprint-btn'),
            this.querySelector('.device-list-container'),
            this
        );
        this.energyTableManager.attachSortHandler(
            this.querySelector('#sort-mode'),
            this.querySelector('#energy-table-container'),
            energyDevices
        );
    }

    renderCarbonIntensityCard(data) {
        const color = CarbonUtils.getCarbonColor(data?.co2_intensity);
        const label = CarbonUtils.getCarbonLabel(data?.co2_intensity);

        return `
            <ha-card header="Energy Footprint">
                <div class="card-content">
                    <p>Current Energy CO₂ Intensity:
                    <span class="ci-value"><b>${data?.co2_intensity ?? 'N/A'}</b></span>
                    gCO₂eq/kWh
                    <span class="ci-indicator ${color}"></span>
                    <span class="ci-label">${label}</span></p>
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
                        <!-- Histogram will be rendered here -->
                    </div>
                </div>
            </ha-card>
        `;
    }

    renderAddDeviceCard(devices) {
        return `
            <ha-card header="Add New Device">
                <div class="card-content">
                    ${this.formManager.renderForm(devices)}
                </div>
            </ha-card>
        `;
    }

    renderConfiguredDevicesCard(data) {
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

        return `
            <ha-card header="Configured Devices">
                <div class="card-content device-list-container">
                    ${hasDevices ? this.deviceManager.renderDeviceList(null, data) : '<p>No devices configured yet.</p>'}
                </div>
            </ha-card>
        `;
    }

    renderAllDevicesCard(energyDevices) {
        return `
            <ha-card header="All Devices">
                <div class="card-header">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <label for="sort-mode" style="font-weight: 500;">Sort by:</label>
                        <select id="sort-mode" style="width: auto; min-width: 150px; max-width: 200px;">
                            <option value="energy">Energy Consumption</option>
                            <option value="name">Alphabetical</option>
                        </select>
                    </div>
                </div>
                <div class="card-content" id="energy-table-container">
                    ${this.energyTableManager.renderEnergyTable(energyDevices)}
                </div>
            </ha-card>
        `;
    }

    attachStylesheet() {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.2';
        this.appendChild(link);
    }
}

if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');