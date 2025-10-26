/**
 * Basic panel for the Carbon Footprint integration. Most of the code is currently ugly and AI-generated
 * for testing purposes. We should rewrite it properly later.
 */
class CarbonFootprintPanel extends HTMLElement {
    constructor() {
        super();
        this._devices = [];
    }

    async connectedCallback() {
        const data = await this.getCarbonData();
        this.render(data);
    }

    set hass(hass) {
        this._hass = hass;
        if (this.isConnected) {
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

    getAvailableEntities() {
        const states = this._hass.states;
        return Object.keys(states).sort();
    }

    render(data) {
        const entities = this.getAvailableEntities();
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

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
                            ${this.renderForm(entities)}
                        </div>
                    </ha-card>

                    <ha-card header="Configured Devices">
                        <div class="card-content">
                            ${hasDevices ? `
                                <ul>
                                    ${Object.entries(data.devices).map(([entity_id, info]) => `
                                        <li>
                                            <div class="device-info">
                                                <div>
                                                    <b>${entity_id}</b><br>
                                                    Type: ${info.type || 'Unknown'}<br>
                                                    Carbon: ${info.carbon_footprint || 0} kgCO₂eq
                                                </div>
                                                <button
                                                    type="button"
                                                    class="delete-btn"
                                                    data-entity-id="${entity_id}"
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

        this.attachFormHandler();

        const style = document.createElement('style');
        style.textContent = `
            .content {
                padding: 16px;
                display: flex;
                flex-direction: column;
                gap: 16px;
            }
            form {
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            label {
                font-weight: 500;
                display: block;
                margin-bottom: 4px;
            }
            input, select {
                width: 100%;
                padding: 6px;
                box-sizing: border-box;
                border-radius: 4px;
                border: 1px solid var(--divider-color);
                background-color: var(--card-background-color);
                color: var(--primary-text-color);
            }
            .button-group {
                display: flex;
                gap: 8px;
                align-items: center;
            }
            button {
                background-color: var(--primary-color);
                color: var(--text-primary-color);
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: 500;
            }
            button[type="button"] {
                background-color: var(--secondary-background-color);
                color: var(--primary-text-color);
            }
            button:hover {
                opacity: 0.9;
            }
            ul {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            li {
                padding: 8px 0;
                border-bottom: 1px solid var(--divider-color);
            }
            .device-info {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 16px;
            }
            .delete-btn {
                background-color: transparent;
                color: var(--error-color, #db4437);
                border: 1px solid var(--divider-color);
                padding: 4px 8px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                min-width: 32px;
                height: 32px;
                flex-shrink: 0;
            }
            .delete-btn:hover {
                background-color: var(--error-color, #db4437);
                color: var(--text-primary-color);
                opacity: 1;
            }
            .ha-header {
                display: flex;
                align-items: center;
                height: 56px;
                background-color: var(--app-header-background-color, var(--primary-color));
                color: var(--app-header-text-color, var(--text-primary-color));
                padding: 0 16px;
                box-sizing: border-box;
                box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,0.2));
            }

            .ha-header h1 {
                font-size: 20px;
                font-weight: 400;
                margin: 0;
                margin-left: 20px;
                color: var(--app-header-text-color, var(--text-primary-color));
            }
        `;
        this.appendChild(style);
    }

    renderForm(entities) {
        return `
            <form id="add-device-form">
                <div>
                    <label for="entity_id">Entity</label>
                    <select id="entity_id" name="entity_id" required>
                        <option value="">Select an entity...</option>
                        ${entities.map(entity_id => `
                            <option value="${entity_id}">${entity_id}</option>
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

    attachFormHandler() {
        const form = this.querySelector('#add-device-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData(form);

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        entity_id: formData.get('entity_id'),
                        device_type: formData.get('device_type'),
                        carbon_footprint: parseFloat(formData.get('carbon_footprint')),
                        metadata: {}
                    });

                    const newData = await this.getCarbonData();
                    this.render(newData);

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
                        entity_id: entityId
                    });

                    const newData = await this.getCarbonData();
                    this.render(newData);

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
                        const avg = (values[0] + values[1] + values[2]) / 3;
                        formInput.value = avg.toFixed(2);
                    }

                } catch (err) {
                    console.error('Failed to compute footprint:', err);
                    alert('Error computing carbon footprint: ' + err.message);
                }
            }
            dialog.remove();
        });

        const style = document.createElement('style');
        style.textContent = `
            .ha-dialog::backdrop { background: rgba(0,0,0,0.4); }
            .ha-dialog { border: none; border-radius: 12px; padding: 0; background: var(--card-background-color); color: var(--primary-text-color); max-width: 700px; width: 90%; }
            .dialog-content { padding: 16px; }
            h2 { margin-top: 0; font-weight: 500; font-size: 1.2rem; }
            table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
            th, td { padding: 8px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
            .dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
            button { background-color: var(--primary-color); color: var(--text-primary-color); border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 500; }
            button[value="cancel"] { background-color: var(--secondary-background-color); color: var(--primary-text-color); }
        `;
        dialog.appendChild(style);

        document.body.appendChild(dialog);
        dialog.showModal();
    }
}

if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');