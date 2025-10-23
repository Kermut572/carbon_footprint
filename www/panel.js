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
        const {devices, co2_intensity} = data;
        this.innerHTML = `
            <h1>Carbon Footprint Panel</h1>
            <p>Current CO2 Intensity: ${co2_intensity} gCO2/kWh</p>
            <h2>Devices:</h2>
            <ul>
                ${devices.map(device => `
                    <li>
                        <strong>${device.entity_id}</strong>
                    </li>
                `).join('')}
            </ul>
        `;
    }
}

customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
console.log('Panel loadeddddd');