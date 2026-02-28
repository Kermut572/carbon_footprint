/**
 * Utility functions for carbon footprint calculations and formatting.
 */

export class CarbonUtils {
    static getCarbonColor(ci) {
        if (!ci || isNaN(ci)) return 'ci-unknown';
        if (ci < 150) return 'ci-low';
        if (ci < 300) return 'ci-medium';
        return 'ci-high';
    }

    static getCarbonLabel(ci) {
        if (!ci || isNaN(ci)) return 'Unknown';
        if (ci < 150) return 'Good';
        if (ci < 300) return 'Moderate';
        return 'High';
    }

    /**
     * Fetch carbon footprint data
     * @param {CarbonFootprintPanel} instance - The component instance
     * @returns {Promise<Object>} Carbon data from the backend
     */
    static async getCarbonData(instance) {
        const data = await instance._hass.callWS({
            type: 'carbon_footprint/get_data'
        });
        return data;
    }

    /**
     * Fetch all devices energy data
     * @param {CarbonFootprintPanel} instance - The component instance
     * @returns {Promise<Object>} Energy data for all devices
     */
    static async getAllDevicesEnergy(instance) {
        try {
            return await instance._hass.callWS({
                type: "carbon_footprint/get_all_devices_energy",
            });
        } catch (err) {
            console.error("Error fetching all devices energy:", err);
            return { devices: [] };
        }
    }

    /**
     * Update device energy data
     * @param {CarbonFootprintPanel} instance - The component instance
     */
    static async updateDeviceEnergy(instance) {
        try {
            await instance._hass.callWS({
                type: "carbon_footprint/update_devices_energy",
            });
        } catch (err) {
            console.error("Error updating devices energy:", err);
        }
    }

    /**
     * Update the device list display
     * @param {CarbonFootprintPanel} instance - The component instance
     */
    static async updateDeviceList(instance) {
        await CarbonUtils.updateDeviceEnergy(instance);
        console.log('in carbonutils file');
        const data = await CarbonUtils.getCarbonData(instance);
        const deviceListContainer = instance.querySelector('.device-list-container');

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
                                Area: ${info.metadata?.area_id || 'N/A'} <br>
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

        instance.attachDeleteHandlers();
    }
}