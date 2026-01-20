/**
 * Manages histogram rendering and data fetching.
 */

export class HistogramManager {
    constructor() {
        this._hass = null;
        this._histogramData = null;
        this._chart = null;
        this._currentChartGranularity = 'hour';
        this._currentTimeFrame = 'last-week';

        this._chartGranularity = {
            HOUR: 'hour',
            DAY: 'day',
            MONTH: 'month',
        };

        this._timeFrame = {
            WEEK: 'last-week',
            MONTH: 'last-month',
            YEAR: 'last-year',
        };
    }

    setHass(hass) {
        this._hass = hass;
    }

    async getEnergyHistogram() {
        try {
            const pastDays = this._getPastDays();
            const endTime = new Date();
            const startTime = new Date(endTime);
            startTime.setDate(endTime.getDate() - pastDays);

            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_energy_footprint_time_interval',
                start_time: startTime.toISOString(),
                end_time: endTime.toISOString(),
                granularity: this._currentChartGranularity,
            });

            if (!result.energy_footprints || result.energy_footprints.length === 0) {
                return '<p>No historical data available</p>';
            }

            this._histogramData = result.energy_footprints;

            return `
                <div style="position: relative; height: 300px; width: 100%;">
                    <canvas id="energy-histogram-chart"></canvas>
                </div>
            `;
        } catch (err) {
            console.error('Error loading histogram:', err);
            return '<p>Error loading histogram data</p>';
        }
    }

    initialize(panel, histogramHtml, hass) {
        const container = panel.querySelector('#energy-histogram-container');
        if (container) {
            container.innerHTML = histogramHtml;
        }

        this._loadChartLibrary(() => this.renderHistogram());

        const granSelect = panel.querySelector('#granularity-select');
        if (granSelect) {
            granSelect.value = this._currentChartGranularity;
            granSelect.addEventListener('change', async (e) => {
                this._currentChartGranularity = e.target.value;
                await this.refreshHistogram(panel);
            });
        }

        const timeFrameSelect = panel.querySelector('#time-frame-select');
        if (timeFrameSelect) {
            timeFrameSelect.value = this._currentTimeFrame;
            timeFrameSelect.addEventListener('change', async (e) => {
                this._currentTimeFrame = e.target.value;
                await this.refreshHistogram(panel);
            });
        }
    }

    async refreshHistogram(panel) {
        const newHtml = await this.getEnergyHistogram();
        const container = panel.querySelector('#energy-histogram-container');
        if (container) {
            container.innerHTML = newHtml;
        }

        this._loadChartLibrary(() => this.renderHistogram());
    }

    renderHistogram() {
        const canvas = document.querySelector('#energy-histogram-chart');
        if (!canvas || !this._histogramData) {
            return;
        }

        const labels = this._histogramData.map((point) =>
            this._formatLabel(point.timestamp)
        );
        const values = this._histogramData.map((point) => point.energy_footprint);

        if (this._chart) {
            this._chart.destroy();
        }

        this._chart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'CO₂ intensity (gCO₂eq/kWh)',
                        data: values,
                        backgroundColor: 'rgba(3, 169, 244, 0.5)',
                        borderColor: 'rgb(3, 169, 244)',
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.parsed.y.toFixed(1)} gCO₂eq/kWh`,
                        },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'gCO₂eq/kWh',
                        },
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45,
                        },
                    },
                },
            },
        });
    }

    _getPastDays() {
        switch (this._currentTimeFrame) {
            case this._timeFrame.WEEK:
                return 7;
            case this._timeFrame.MONTH:
                return 30;
            case this._timeFrame.YEAR:
                return 365;
            default:
                return 7;
        }
    }

    _formatLabel(timestamp) {
        const date = new Date(timestamp);
        switch (this._currentChartGranularity) {
            case this._chartGranularity.HOUR:
                return date.toLocaleDateString('fr-FR', {
                    day: '2-digit',
                    month: '2-digit',
                    hour: '2-digit',
                });
            case this._chartGranularity.DAY:
                return date.toLocaleDateString('fr-FR', {
                    day: '2-digit',
                    month: '2-digit',
                });
            case this._chartGranularity.MONTH:
                return date.toLocaleDateString('fr-FR', {
                    month: '2-digit',
                    year: 'numeric',
                });
        }
    }

    _loadChartLibrary(callback) {
        if (typeof Chart === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
            script.onload = callback;
            document.head.appendChild(script);
        } else {
            callback();
        }
    }
}