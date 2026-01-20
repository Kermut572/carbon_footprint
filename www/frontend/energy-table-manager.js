/**
 * Manages energy table rendering and sorting.
 */

export class EnergyTableManager {
    constructor() {
        this._hass = null;
    }

    setHass(hass) {
        this._hass = hass;
    }

    renderEnergyTable(devices) {
        if (!devices.length) {
            return '<p>No devices with measurable energy consumption found.</p>';
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
                ${devices.map((device) => `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.total_energy_kwh?.toFixed(2) ?? 'N/A'}</td>
                </tr>
                `).join('')}
            </tbody>
            </table>
        `;
    }

    attachSortHandler(sortSelect, tableContainer, energyDevices) {
        if (sortSelect && tableContainer) {
            sortSelect.addEventListener('change', () => {
                let sortedDevices = [...energyDevices];
                if (sortSelect.value === 'energy') {
                    sortedDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);
                } else if (sortSelect.value === 'name') {
                    sortedDevices.sort((a, b) =>
                        a.device_name.localeCompare(b.device_name)
                    );
                }
                tableContainer.innerHTML = this.renderEnergyTable(sortedDevices);
            });
        }
    }
}