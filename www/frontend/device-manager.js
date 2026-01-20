/**
 * Manages device operations and rendering.
 */

export class DeviceManager {
    constructor() {
        this._hass = null;
    }

    setHass(hass) {
        this._hass = hass;
    }

    async getAllDevicesEnergy(hass) {
        try {
            return await hass.callWS({
                type: 'carbon_footprint/get_all_devices_energy',
            });
        } catch (err) {
            console.error('Error fetching all devices energy:', err);
            return { devices: [] };
        }
    }

    async updateDevicesEnergy(hass) {
        try {
            await hass.callWS({
                type: 'carbon_footprint/update_devices_energy',
            });
        } catch (err) {
            console.error('Error updating devices energy:', err);
        }
    }

    renderDeviceList(container, data) {
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;
        const html = hasDevices
            ? `
                <ul>
                    ${Object.entries(data.devices)
                        .map(([deviceName, info]) => this._renderDeviceItem(deviceName, info))
                        .join('')}
                </ul>
            `
            : '<p>No devices configured yet.</p>';

        if (container) {
            container.innerHTML = html;
            this._attachDeleteHandlers(container);
        }
        return html;
    }

    _renderDeviceItem(deviceName, info) {
        return `
            <li>
                <div class="device-info">
                    <div>
                        <b>${deviceName}</b><br>
                        Type: ${info.type || 'Unknown'}<br>
                        Carbon: ${info.carbon_footprint || 0} kgCO₂eq<br>
                        Manufacturer: ${info.metadata?.manufacturer || 'N/A'}<br>
                        Model: ${info.metadata?.model || 'N/A'}<br>
                        Model ID: ${info.metadata?.model_id || 'N/A'}<br>
                        Class: ${info.metadata?.device_classes || 'N/A'}<br>
                        Total Energy Consumed: ${info.metadata?.total_energy || 'N/A'}<br>
                    </div>
                    <button
                        type="button"
                        class="delete-btn"
                        data-entity-id="${deviceName}"
                        title="Remove device">
                        ✕
                    </button>
                </div>
            </li>
        `;
    }

    _attachDeleteHandlers(container) {
        const deleteButtons = container.querySelectorAll('.delete-btn');
        deleteButtons.forEach((btn) => {
            btn.addEventListener('click', async (e) => {
                const entityId = e.currentTarget.dataset.entityId;

                if (!confirm(`Remove ${entityId} from tracking?`)) {
                    return;
                }

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/remove_device',
                        device_name: entityId,
                    });

                    const newData = await this._hass.callWS({
                        type: 'carbon_footprint/get_data',
                    });
                    this.renderDeviceList(container, newData);
                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }
}