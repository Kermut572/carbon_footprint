/**
 * Manages form rendering and hardware questionnaire.
 */

import { HardwareQuestionnaire } from './hardware-questionnaire.js';

export class FormManager {
    constructor() {
        this._hass = null;
        this._hardwareQuestionnaire = new HardwareQuestionnaire();
    }

    setHass(hass) {
        this._hass = hass;
        this._hardwareQuestionnaire.setHass(hass);
    }

    renderForm(devices) {
        return `
            <form id="add-device-form">
                <div>
                    <label for="device_name">Entity</label>
                    <select id="device_name" name="device_name" required>
                        <option value="">Select an entity...</option>
                        ${devices.map((deviceName) => `
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

    attachHandlers(form, computeBtn, deviceListContainer, panel) {
        if (form) {
            form.addEventListener('submit', async (e) => {
                await this._handleFormSubmit(e, panel);
            });
        }

        if (computeBtn) {
            computeBtn.addEventListener('click', () => {
                this._hardwareQuestionnaire.show();
            });
        }
    }

    async _handleFormSubmit(e, panel) {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);

        try {
            await this._hass.callWS({
                type: 'carbon_footprint/set_device',
                device_name: formData.get('device_name'),
                device_type: formData.get('device_type'),
                carbon_footprint: parseFloat(formData.get('carbon_footprint')),
                metadata: {},
            });

            const newData = await this._hass.callWS({
                type: 'carbon_footprint/get_data',
            });
            await panel.render(newData);
        } catch (error) {
            console.error('Failed to add device:', error);
            alert(`Error adding device: ${error.message}`);
        }
    }
}