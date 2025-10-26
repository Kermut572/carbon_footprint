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
                                            <b>${entity_id}</b><br>
                                            Type: ${info.type || 'Unknown'}<br>
                                            Carbon: ${info.carbon_footprint || 0} kgCO₂eq
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

        // Inject minimal style to match HA cards and layout spacing
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
            button {
                align-self: start;
                background-color: var(--primary-color);
                color: var(--text-primary-color);
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: 500;
            }
            button:hover {
                background-color: var(--primary-color);
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
                    <input type="number" id="carbon_footprint" name="carbon_footprint" step="0.1" required>
                </div>
                <button type="submit">Add Device</button>
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
    }
}

//fixes annoying bug when reloading the panel
if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');
