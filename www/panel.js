class CarbonFootprintPanel extends HTMLElement {
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

    render(data) {
        if (!data || !data.devices || Object.keys(data.devices).length === 0) {
            this.innerHTML = `
                <h1>Carbon Footprint Panel</h1>
                <p>No data available</p>
            `;
            return;
        }
        const {devices, co2_intensity} = data;
        const deviceList = Object.entries(devices).map(([entity_id, info]) => ({entity_id, ...info}));

        this.innerHTML = `
            <h1>Carbon Footprint Panel</h1>
            <p>Current CO2 Intensity: ${co2_intensity || -1} gCO2/kWh</p>
            <h2>Devices (${deviceList.length}):</h2>
            <ul>
                ${deviceList.map(device => `
                    <li>
                        <strong>${device.entity_id}</strong>
                        Type: ${device.type || 'Unknown'}<br>
                        Carbon: ${device.carbon_footprint || 0} kg CO2
                    </li>
                `).join('')}
            </ul>
        `;
    }
}

customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
console.log('Panel loadeddddd');