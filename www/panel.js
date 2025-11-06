/**
 * Basic panel for the Carbon Footprint integration. Most of the code is currently ugly and AI-generated
 * for testing purposes. We should rewrite it properly later.
 */
class CarbonFootprintPanel extends HTMLElement {
    constructor() {
        super();
        this._devices = [];
        this._setup = false
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
        const data = await this._hass.callWS({
            type: 'carbon_footprint/get_data'
        });
        return data;
    }

    async getAllDevicesEnergy() {
        try {
            return await this._hass.callWS({
                type: "carbon_footprint/get_all_devices_energy",
            });
            } catch (err) {
            console.error("Error fetching all devices energy:", err);
            return { devices: [] };
        }
    }

    async updateDeviceEnergy() {
        await this._hass.callWS({
            type: "carbon_footprint/update_devices_energy",
        });
    }

    async updateDeviceList() {
        await this.updateDeviceEnergy();
        const data = await this.getCarbonData();
        const deviceListContainer = this.querySelector('.device-list-container');

        if (!deviceListContainer) return;

        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

        deviceListContainer.innerHTML = hasDevices ? `
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
        ` : `<p>No devices configured yet.</p>`;

        this.attachDeleteHandlers();
    }

    async render(data) {
        const devicesResp = await this._hass.callWS({ type: 'carbon_footprint/get_devices_to_add' });
        const devicesArray = devicesResp.device_names || [];
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

        const allDevicesEnergyResp = await this.getAllDevicesEnergy();
        const energyDevices = allDevicesEnergyResp.devices_energy || [];
        energyDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header">
                    <h1>Carbon Footprint</h1>
                </header>

                <div class="content" slot="content">
                    <ha-card header="Overview">
                        <div class="card-content">
                            <p>Current CO₂ Intensity: <b>${data?.co2_intensity ?? 'N/A'}</b> gCO₂eq/kWh</p>
                        </div>
                    </ha-card>

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
        link.href = '/api/carbon_footprint/style.css?version=1.0';
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

                    // Only update device list
                    await this.updateDeviceList();

                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }

    async showHardwareDialogAndCompute() {
        const resp = await fetch('/api/carbon_footprint/blocks_footprints.json');
        const jsonData = await resp.json();

        const dialog = document.createElement('dialog');
        dialog.classList.add('ha-dialog');

        const rows = Object.entries(jsonData).map(([blockName, levels]) => {
            const radios = Object.entries(levels).map(([levelId, values]) => {
                const disabled = values.every(v => v === null);
                const label = disabled ? `Level ${levelId} (N/A)` : `Level ${levelId} [${values.join(', ')}]`;
                return `<label>
                            <input type="radio" name="${blockName}" value="${levelId}" ${disabled ? 'disabled' : ''}>
                            ${label}
                        </label>`;
            }).join('<br>');
            return `<tr><td>${blockName}</td><td>${radios}</td></tr>`;
        }).join('');

        dialog.innerHTML = `
            <form method="dialog" class="dialog-content">
                <h2>Select Hardware Levels</h2>
                <table>
                    <thead>
                        <tr><th>Functional Block</th><th>Level</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
                <div class="dialog-actions">
                    <button value="cancel">Cancel</button>
                    <button value="confirm">Confirm</button>
                </div>
            </form>
        `;

        dialog.addEventListener('close', async () => {
            if (dialog.returnValue === 'confirm') {
                const hsl_values = {};
                Object.keys(jsonData).forEach(block => {
                    const checked = dialog.querySelector(`input[name="${block}"]:checked`);
                    if (checked) hsl_values[block] = checked.value;
                });

                if (Object.keys(hsl_values).length === 0) {
                    alert("No blocks selected.");
                    return;
                }

                try {
                    const result = await this._hass.callWS({
                        type: 'carbon_footprint/compute_footprint',
                        hsl_values
                    });

                    console.log('Computed CO2:', result);

                    const formInput = this.querySelector('#carbon_footprint');
                    if (formInput) {
                        const values = result.values;
                        const avg = values[1]; // TODO change this so we take the 3 values into account
                        formInput.value = avg.toFixed(2);
                    }

                } catch (err) {
                    console.error('Failed to compute footprint:', err);
                    alert('Error computing carbon footprint: ' + err.message);
                }
            }
            dialog.remove();
        });

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css';

        dialog.appendChild(link);

        document.body.appendChild(dialog);
        dialog.showModal();
    }
}

if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');
