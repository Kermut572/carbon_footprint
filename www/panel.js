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
        // Get all entities from Home Assistant
        const states = this._hass.states;
        return Object.keys(states).sort();
    }

    render(data) {
        const entities = this.getAvailableEntities();

        if (!data || !data.devices || Object.keys(data.devices).length === 0) {
            this.innerHTML = `
                <h1>Carbon Footprint Panel</h1>
                ${this.renderForm(entities)}
                <p>No devices configured yet</p>
            `;
            this.attachFormHandler();
            return;
        }

        const {devices, co2_intensity} = data;
        const deviceList = Object.entries(devices).map(([entity_id, info]) => ({entity_id, ...info}));

        this.innerHTML = `
            <h1>Carbon Footprint Panel</h1>
            <p>Current CO2 Intensity: ${co2_intensity || -1} gCO2/kWh</p>

            <h2>Add New Device</h2>
            ${this.renderForm(entities)}

            <h2>Devices (${deviceList.length}):</h2>
            <ul>
                ${deviceList.map(device => `
                    <li>
                        <strong>${device.entity_id}</strong><br>
                        Type: ${device.type || 'Unknown'}<br>
                        Carbon: ${device.carbon_footprint || 0} kg CO2
                    </li>
                `).join('')}
            </ul>
        `;

        this.attachFormHandler();
    }

    // llm generated code to test adding a device
    renderForm(entities) {
        return `
            <form id="add-device-form">
                <div>
                    <label for="entity_id">Entity:</label>
                    <select id="entity_id" name="entity_id" required>
                        <option value="">Select an entity...</option>
                        ${entities.map(entity_id => `
                            <option value="${entity_id}">${entity_id}</option>
                        `).join('')}
                    </select>
                </div>
                <div>
                    <label for="device_type">Device Type:</label>
                    <input type="text" id="device_type" name="device_type" required>
                </div>
                <div>
                    <label for="carbon_footprint">Carbon Footprint (kg CO2):</label>
                    <input type="number" id="carbon_footprint" name="carbon_footprint"
                           step="0.1" required>
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

                    // Refresh the panel
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

customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
console.log('Panel loaded');