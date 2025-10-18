class CarbonFootprintPanel extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
            <div style="padding: 20px; font-family: var(--primary-font-family);">
                <h1 style="color: var(--primary-text-color);">Carbon Footprint Panel</h1>
                <p style="color: var(--primary-text-color);">Panel is working! ✓</p>
                <p style="color: var(--secondary-text-color);">
                    Hass object available: ${this.hass ? 'Yes ✓' : 'No ✗'}
                </p>
            </div>
        `;
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
}

customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
console.log('Panel loadeddddd');