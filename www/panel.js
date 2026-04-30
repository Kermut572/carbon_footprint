/**
 * Basic panel for the Carbon Footprint integration. Most of the code is currently ugly and AI-generated
 * for testing purposes. We should rewrite it properly later.
 */

import { CarbonUtils } from './frontend/carbon-utils.js?v=1.1';
import { openFullForm } from './frontend/form-manager.js';
import { Utils } from './utils.js';

class CarbonFootprintPanel extends HTMLElement {

    constructor() {
        super();
        this._devices = [];
        this._setup = false
        this._histogramData = null;
        this._chart = null;
        this._roomChart = null;
        this._deviceChart = null;
        this._consumptionChart = null;
        this._roomData = null;
        this._selectedRoom = null;
        this._currentPage = 'main'; // 'main' or 'settings'
        this._carbonView = 'total'; // 'total', 'embodied', 'usage', or 'appliance'
        this._showApplianceUsage = false;
        this._showEnergyApplianceUsage = false;
        this._ecView = 'total';
        this._groupBy = 'room'; // 'room' or 'type'
        this._currentDevice = null;
        this._currentType = null;
        this._currentCarbonValue = 0.0;

        this._hiddenDeviceIndices = new Set();

        this._chartGranularity = {
            HOUR: "hour",
            DAY: "day",
            MONTH: "month"
        };
        this._currentChartGranularity = this._chartGranularity.DAY;

        this._timeFrame = {
            WEEK: "last-week",
            MONTH: "last-month",
            YEAR: "last-year",
            CUSTOM: "custom"
        };
        this._currentTimeFrame = this._timeFrame.MONTH;
        const defaultEndDate = new Date();
        const defaultStartDate = new Date(defaultEndDate);
        defaultStartDate.setDate(defaultEndDate.getDate() - 30);
        this._customStartDate = this._formatDateInputValue(defaultStartDate);
        this._customEndDate = this._formatDateInputValue(defaultEndDate);
    }


    async connectedCallback() {
        const data = await this.getCarbonData();
        await this.render(data);
        this._setup = true
    }

    set hass(hass) {
        this._hass = hass;

        if (!this._setup && this.isConnected) {
            this.connectedCallback();
        }
    }

    get hass() {
        return this._hass;
    }

    async getCarbonData() {
        //console.log('Getting carbon data from backend');
        return await CarbonUtils.getCarbonData(this);
    }

    async getAllDevicesEnergy() {
        return await CarbonUtils.getAllDevicesEnergy(this);
    }

    async updateDeviceEnergy() {
        return await CarbonUtils.updateDeviceEnergy(this);
    }

    async getCarbonByRoom() {
        try {
            if (this._useFakeCarbonData) {
                const fakeData = this._getFakeCarbonDataForCurrentView();
                console.log('Using fake carbon data for room data:', fakeData);
                this._roomData = fakeData || [];
                return this._roomData;
            }

            // Support test data toggle for recommendations testing
            if (this._useFakeRoomData) {
                const fakeData = this._getFakeRoomDataForCurrentView();
                console.log('Using fake room data (test_data.py) for testing:', fakeData);
                this._roomData = fakeData || [];
                return this._roomData;
            }

            if (this._carbonView === 'appliance') {
                const applianceResult = await this._hass.callWS({
                    type: 'carbon_footprint/get_carbon_by_room_with_usage',
                    is_appliance: true
                });
                this._roomData = this._normalizeApplianceOnlyData(applianceResult.rooms || []);
                return this._roomData;
            }

            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_carbon_by_room_with_usage',
                is_appliance: false
            });

            let rooms = result.rooms || [];
            if (this._showApplianceUsage) {
                const applianceResult = await this._hass.callWS({
                    type: 'carbon_footprint/get_carbon_by_room_with_usage',
                    is_appliance: true
                });
                rooms = this._mergeApplianceUsageData(rooms, applianceResult.rooms || []);
            }

            this._roomData = rooms;
            return this._roomData;

        } catch (err) {
            console.error('Error loading room data:', err);
            return [];
        }
    }

    async getCarbonByType() {
        try {
            if (this._carbonView === 'appliance') {
                const applianceResult = await this._hass.callWS({
                    type: 'carbon_footprint/get_carbon_by_type_with_usage',
                    is_appliance: true
                });
                this._typeData = this._normalizeApplianceOnlyData(applianceResult.types || []);
                return this._typeData;
            }

            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_carbon_by_type_with_usage',
                is_appliance: false
            });

            let types = result.types || [];
            if (this._showApplianceUsage) {
                const applianceResult = await this._hass.callWS({
                    type: 'carbon_footprint/get_carbon_by_type_with_usage',
                    is_appliance: true
                });
                types = this._mergeApplianceUsageData(types, applianceResult.types || []);
            }

            this._typeData = types;
            return this._typeData;

        } catch (err) {
            console.error('Error loading type data:', err);
            return [];
        }
    }

    async updateDeviceList() {
        return await CarbonUtils.updateDeviceList(this);
    }

    async render(data) {
        if (this._currentPage === 'settings') {
            this.renderSettingsPage(data);
            return;
        }

        const yearlyConsCall = await this._hass.callWS({ type: 'carbon_footprint/get_yearly_contribution' });
        const yearlyCons = yearlyConsCall.yearly_contribution;
        console.log(`Found ${yearlyCons}kWh for this year.`)

        const emissionNowRaw = this._hass.states['sensor.carbon_emission_now']?.state;
        const carbonTodayRaw = this._hass.states['sensor.carbon_total_today']?.state;

        const emissionNow = emissionNowRaw && emissionNowRaw !== 'unknown' && emissionNowRaw !== 'unavailable'
            ? parseFloat(emissionNowRaw)
            : null;

        const carbonToday = carbonTodayRaw && carbonTodayRaw !== 'unknown' && carbonTodayRaw !== 'unavailable'
            ? parseFloat(carbonTodayRaw)
            : null;

        // Fetch room data and recommendation inputs
        const roomData = await this.getCarbonByRoom();

        const currentCarbonIntensity = data?.co2_intensity_status === 'fallback'
            ? null
            : data?.co2_intensity;

        // Fetch consumption data for usage vs intensity recommendation (last 30 days)
        const recEndTime = new Date();
        const recStartTime = new Date(recEndTime);
        recStartTime.setDate(recEndTime.getDate() - 30);
        const recResult = await this._hass.callWS({
            type: 'carbon_footprint/get_consumption_footprint_time_interval',
            start_time: recStartTime.toISOString(),
            end_time: recEndTime.toISOString(),
            granularity: 'day'
        });
        const energyData = recResult.devices_consumptions;
        const intensityData = data?.intensity_history || [];
        let recommendations;
        try {
            recommendations = await this._hass.callWS({
                type: 'carbon_footprint/get_recommendations',
                room_data: roomData,
                yearly_contribution: yearlyCons,
                usage_history: energyData,
                intensity_history: intensityData,
                current_intensity: currentCarbonIntensity,
            });
        } catch (err) {
            console.error('Error loading recommendations:', err);
            recommendations = {
                high_impact_area: {
                    title: 'No Data Available',
                    message: "We couldn't determine the high-impact area.",
                    severity: 'info',
                },
                carbon_intensity: {
                    label: ' ',
                    message: 'Carbon intensity data unavailable.',
                    color: '#eeeeee',
                    severity: 'info',
                },
                iot_share: {
                    message: 'IoT share recommendation unavailable.',
                    severity: 'info',
                },
                usage_pattern: {
                    title: 'Usage Pattern Insight',
                    message: 'Usage pattern recommendation unavailable.',
                    color: '#eeeeee',
                    severity: 'info',
                },
                carbon_intensity_info: {
                    colorClass: 'ci-unknown',
                    label: ' ',
                },
            };
        }
        const recommendation = recommendations.high_impact_area;
        const intensityRec = recommendations.carbon_intensity;
        const iotShareRec = recommendations.iot_share;
        const usagePatternRec = recommendations.usage_pattern;
        const carbonIntensityInfo = recommendations.carbon_intensity_info;
        const annualConsumption = await CarbonUtils.getAnnualConsumptionSummary(this);

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <h1>Carbon Footprint</h1>
                    <button id="settings-btn" style="position: absolute; right: 20px; top: 15px; padding: 8px 16px; background-color: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">Settings</button>
                </header>

                <div class="content" slot="content">
                    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px;">
                        <ha-card header="Annual consumption">
                            <div class="card-content" style="font-size: 22px; font-weight: 600;">
                                ${annualConsumption.kgCO2eq === null ? 'N/A' : annualConsumption.kgCO2eq.toFixed(2)} kgCO₂eq
                                <div style="font-size: 13px; font-weight: 400; color: #666; margin-top: 6px;">${annualConsumption.rangeText}</div>
                                <div style="font-size: 13px; font-weight: 400; color: #666; margin-top: 6px;">
                                    which is equivalent to riding ${annualConsumption.carKm === null ? 'N/A' : annualConsumption.carKm.toFixed(1)} km by car
                                    <span title="According to the ImpactCO2 framework of the French Republic. Considering a gasoline-powered car." style="display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 50%; border: 1px solid #777; color: #555; font-size: 11px; font-weight: 600; cursor: help; margin-left: 4px;">i</span>
                                </div>
                            </div>
                        </ha-card>
                        <ha-card header="Carbon intensity">
                            <div class="card-content" style="font-size: 22px; font-weight: 600;">
                                ${data?.co2_intensity_status === 'fallback' ? 'Unknown' : `${data?.co2_intensity ?? 'N/A'} gCO₂eq/kWh`}
                                <span class="ci-indicator ${carbonIntensityInfo.colorClass}"></span>
                                <span class="ci-label" style="font-size: 14px; font-weight: 500;">${carbonIntensityInfo.label}</span>
                                <div style="font-size: 13px; font-weight: 400; color: #666; margin-top: 6px; line-height: 1.35;">
                                    ${intensityRec.message}
                                </div>
                            </div>
                        </ha-card>
                        <ha-card header="Blablabla">
                            <div class="card-content" style="font-size: 22px; font-weight: 600;">
                                N/A
                            </div>
                        </ha-card>
                    </div>

                    <ha-card header="Energy Consumption Footprint">
                        <div class="card-content">
                            <p style="font-size: 12px; color: #666; margin-top: 8px; margin-bottom: 16px;">
                                <em>Devices energy consumption footprint over time (in grams CO₂ equivalent)</em>
                            </p>
                            <div class="histogram-controls">
                                <label for="granularity-select">Granularity:</label>
                                <select id="granularity-select">
                                    <option value="hour">Hour</option>
                                    <option value="day">Day</option>
                                    <option value="month">Month</option>
                                </select>


                                <label for="time-frame-select">Time Frame:</label>
                                <select id="time-frame-select">
                                    <option value="last-week">Last Week</option>
                                    <option value="last-month">Last Month</option>
                                    <option value="last-year">Last Year</option>
                                    <option value="custom">Custom</option>
                                </select>

                                <div id="custom-time-frame-controls" style="display: ${this._currentTimeFrame === this._timeFrame.CUSTOM ? 'flex' : 'none'}; align-items: center; gap: 8px; flex-wrap: wrap;">
                                    <label for="custom-start-date">From:</label>
                                    <input type="date" id="custom-start-date" value="${this._customStartDate}" max="${this._customEndDate}" style="padding: 5px;">
                                    <label for="custom-end-date">To:</label>
                                    <input type="date" id="custom-end-date" value="${this._customEndDate}" min="${this._customStartDate}" style="padding: 5px;">
                                </div>

                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span>Appliance data:</span>
                                    <div id="energy-appliance-usage-toggle" role="group" aria-label="Use appliance usage data in energy chart" style="display: inline-flex; border: 1px solid #bdbdbd; border-radius: 4px; overflow: hidden;">
                                        <button type="button" data-appliance-usage="false" aria-pressed="${!this._showEnergyApplianceUsage}" style="min-width: 44px; padding: 6px 12px; border: none; cursor: pointer; background-color: ${this._showEnergyApplianceUsage ? '#f5f5f5' : 'var(--primary-color, #03a9f4)'}; color: ${this._showEnergyApplianceUsage ? '#333' : '#fff'}; font-weight: ${this._showEnergyApplianceUsage ? '400' : '600'};">No</button>
                                        <button type="button" data-appliance-usage="true" aria-pressed="${this._showEnergyApplianceUsage}" style="min-width: 44px; padding: 6px 12px; border: none; border-left: 1px solid #bdbdbd; cursor: pointer; background-color: ${this._showEnergyApplianceUsage ? 'var(--primary-color, #03a9f4)' : '#f5f5f5'}; color: ${this._showEnergyApplianceUsage ? '#fff' : '#333'}; font-weight: ${this._showEnergyApplianceUsage ? '600' : '400'};">Yes</button>
                                    </div>
                                </div>
                            </div>

                            <div style="margin-bottom: 12px;">
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="total" ${this._ecView === 'total' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Total (Stacked)</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="embodied" ${this._ecView === 'embodied' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Embodied Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="usage" ${this._ecView === 'usage' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Usage Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="ec-view" value="appliance" ${this._ecView === 'appliance' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Appliances Only</span>
                                    </label>
                                </div>
                            </div>
                            <div style="position: relative; height: 400px; width: 100%;">
                                <canvas id="consumption-histogram-chart"></canvas>
                            </div>
                        </div>

                    </ha-card>

                    <ha-card header="Carbon Usage">
                        <div class="card-content">
                            <div class="histogram-controls" style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                                <label for="group-by-select">Group by:</label>
                                <select id="group-by-select">
                                    <option value="room" ${this._groupBy === 'room' ? 'selected' : ''}>Room</option>
                                    <option value="type" ${this._groupBy === 'type' ? 'selected' : ''}>Type</option>
                                </select>

                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span>Appliance data:</span>
                                    <div id="appliance-usage-toggle" role="group" aria-label="Use appliance usage data" style="display: inline-flex; border: 1px solid #bdbdbd; border-radius: 4px; overflow: hidden;">
                                        <button type="button" data-appliance-usage="false" aria-pressed="${!this._showApplianceUsage}" style="min-width: 44px; padding: 6px 12px; border: none; cursor: pointer; background-color: ${this._showApplianceUsage ? '#f5f5f5' : 'var(--primary-color, #03a9f4)'}; color: ${this._showApplianceUsage ? '#333' : '#fff'}; font-weight: ${this._showApplianceUsage ? '400' : '600'};">No</button>
                                        <button type="button" data-appliance-usage="true" aria-pressed="${this._showApplianceUsage}" style="min-width: 44px; padding: 6px 12px; border: none; border-left: 1px solid #bdbdbd; cursor: pointer; background-color: ${this._showApplianceUsage ? 'var(--primary-color, #03a9f4)' : '#f5f5f5'}; color: ${this._showApplianceUsage ? '#fff' : '#333'}; font-weight: ${this._showApplianceUsage ? '600' : '400'};">Yes</button>
                                    </div>
                                </div>
                            </div>

                            <!-- Carbon view toggle with unit explanation -->
                            <div style="margin-bottom: 12px;">
                                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="total" ${this._carbonView === 'total' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Total (Stacked)</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="embodied" ${this._carbonView === 'embodied' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Embodied Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="usage" ${this._carbonView === 'usage' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Usage Only</span>
                                    </label>
                                    <label style="display: flex; align-items: center; cursor: pointer;">
                                        <input type="radio" name="carbon-view" value="appliance" ${this._carbonView === 'appliance' ? 'checked' : ''} style="margin-right: 6px;">
                                        <span>Appliances Only</span>
                                    </label>
                                </div>
                            </div>

                            <!-- Room-level pie chart view -->
                            <div id="room-chart-view" style="display: block;">
                                <div style="position: relative; height: 400px; width: 100%;">
                                    <canvas id="room-pie-chart"></canvas>
                                </div>
                            </div>

                            <!-- Device detail view (hidden by default) -->
                            <div id="device-detail-view" style="display: none;">
                                <button id="back-to-rooms-btn" style="margin-bottom: 16px; padding: 8px 16px; background-color: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;">← Back to Chart</button>
                                <h3 id="selected-room-title"></h3>

                                <!-- Legend explaining embodied vs usage -->
                                <div style="margin-bottom: 16px; padding: 12px; background-color: #f9f9f9; border-radius: 4px; border: 1px solid #ddd; font-size: 13px;">
                                    <div style="margin-bottom: 8px;"><strong>Carbon Types (kgCO₂eq):</strong></div>
                                    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <div style="width: 16px; height: 16px; background-color: rgba(76, 175, 80, 0.7); border: 1px solid rgb(76, 175, 80);"></div>
                                            <span><strong>Embodied:</strong> Manufacturing, transport, disposal</span>
                                        </div>
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <div style="width: 16px; height: 16px; background-color: rgba(33, 150, 243, 0.7); border: 1px solid rgb(33, 150, 243);"></div>
                                            <span><strong>Usage:</strong> Operational energy consumption</span>
                                        </div>
                                    </div>
                                </div>

                                <p id="device-breakdown-text" style="margin-bottom: 12px; font-size: 13px; color: #666;"></p>
                                <div style="position: relative; height: 300px; width: 100%;">
                                    <canvas id="device-bar-chart"></canvas>
                                </div>
                            </div>
                        </div>
                    </ha-card>
                    <ha-card header="Recommendations">
                        <div class="card-content">
                            <div style="display: flex; flex-direction: column; gap: 8px;">


                                <!-- Current yearly cons -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: ${
                                            '#e8f5e9'
                                        }; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-0').style.display = this.parentElement.querySelector('.recommendation-content-0').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-0').textContent = this.parentElement.querySelector('.recommendation-content-0').style.display === 'none' ? '▼' : '▲';">
                                        <strong>IoT share of consumption</strong>
                                        <span class="toggle-icon-0" style="font-size: 12px;">▲</span>
                                    </div>

                                    <div class="recommendation-content-0"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${iotShareRec.message}
                                        </p>
                                    </div>
                                </div>

                                <!-- Usage Pattern Insight -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: ${usagePatternRec.color}; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-pattern').style.display = this.parentElement.querySelector('.recommendation-content-pattern').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-pattern').textContent = this.parentElement.querySelector('.recommendation-content-pattern').style.display === 'none' ? '▼' : '▲';">
                                        <strong>${usagePatternRec.title}</strong>
                                        <span class="toggle-icon-pattern" style="font-size: 12px;">▲</span>
                                    </div>
                                    <div class="recommendation-content-pattern"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${usagePatternRec.message}
                                        </p>
                                    </div>
                                </div>

                                <!-- High-Impact Area Recommendation -->
                                <div style="border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
                                    <div class="recommendation-header"
                                        style="padding: 12px; background-color: #fff8e1; cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none;"
                                        onclick="this.parentElement.querySelector('.recommendation-content-high-impact').style.display = this.parentElement.querySelector('.recommendation-content-high-impact').style.display === 'none' ? 'block' : 'none'; this.querySelector('.toggle-icon-high-impact').textContent = this.parentElement.querySelector('.recommendation-content-high-impact').style.display === 'none' ? '▼' : '▲';">
                                        <strong> ${recommendation.title}</strong>
                                        <span class="toggle-icon-high-impact" style="font-size: 12px;">▲</span>
                                    </div>
                                    <div class="recommendation-content-high-impact"
                                        style="padding: 12px; background-color: #fafafa; border-top: 1px solid #e0e0e0;">
                                        <p style="margin: 0; font-size: 13px; color: #555;">
                                            ${recommendation.message}
                                        </p>
                                    </div>
                                </div>

                            </div>
                        </div>
                    </ha-card>

                </div>
            </ha-app-layout>
        `;

        if (typeof Chart === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js';
            script.onload = async () => {
                //this.renderHistogram();
                await this.renderRoomChart();
                await this.renderConsumptionHistogram();
            };
            document.head.appendChild(script);
        } else {
            //this.renderHistogram();
            await this.renderRoomChart();
            await this.renderConsumptionHistogram();
        }

        const energyConsumptionRadios = this.querySelectorAll('input[name="ec-view"]');
        for (const radio of energyConsumptionRadios) {
            radio.addEventListener('change', async (e) => {
                this._ecView = e.target.value;
                await this.renderConsumptionHistogram();
            });
        }

        const granSelect = this.querySelector('#granularity-select');
        if (granSelect) {
            granSelect.value = this._currentChartGranularity;
            granSelect.addEventListener('change', async (e) => {
                this._currentChartGranularity = e.target.value;
                await this.renderConsumptionHistogram();
            });
        }

        const timeFrameSelect = this.querySelector('#time-frame-select');
        if (timeFrameSelect) {
            timeFrameSelect.value = this._currentTimeFrame;
            timeFrameSelect.addEventListener('change', async (e) => {
                this._currentTimeFrame = e.target.value;
                this._updateCustomTimeFrameControls();
                await this.renderConsumptionHistogram();
            });
        }

        const customStartDate = this.querySelector('#custom-start-date');
        const customEndDate = this.querySelector('#custom-end-date');
        if (customStartDate && customEndDate) {
            customStartDate.addEventListener('change', async (e) => {
                this._customStartDate = e.target.value;
                customEndDate.min = this._customStartDate;
                if (this._customEndDate < this._customStartDate) {
                    this._customEndDate = this._customStartDate;
                    customEndDate.value = this._customEndDate;
                }
                await this.renderConsumptionHistogram();
            });

            customEndDate.addEventListener('change', async (e) => {
                this._customEndDate = e.target.value;
                customStartDate.max = this._customEndDate;
                if (this._customStartDate > this._customEndDate) {
                    this._customStartDate = this._customEndDate;
                    customStartDate.value = this._customStartDate;
                }
                await this.renderConsumptionHistogram();
            });
        }

        const energyApplianceUsageToggle = this.querySelector('#energy-appliance-usage-toggle');
        if (energyApplianceUsageToggle) {
            energyApplianceUsageToggle.addEventListener('click', async (e) => {
                const button = e.target.closest('button[data-appliance-usage]');
                if (!button) {
                    return;
                }

                this._showEnergyApplianceUsage = button.dataset.applianceUsage === 'true';
                this._updateSegmentedToggleState('#energy-appliance-usage-toggle', this._showEnergyApplianceUsage);
                await this.renderConsumptionHistogram();
            });
        }

        // Add settings button click handler
        const settingsBtn = this.querySelector('#settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => {
                this._currentPage = 'settings';
                this.render(data);
            });
        }

        const groupBySelect = this.querySelector('#group-by-select');
        if (groupBySelect) {
            groupBySelect.addEventListener('change', async (e) => {
                this._groupBy = e.target.value;
                await this.renderRoomChart();
            });
        }

        // Add back to rooms button handler
        const backBtn = this.querySelector('#back-to-rooms-btn');
        if (backBtn) {
            backBtn.addEventListener('click', () => {
                this.showRoomChart();
            });
        }

        // Add carbon view radio buttons event listeners
        const carbonViewRadios = this.querySelectorAll('input[name="carbon-view"]');
        for (const radio of carbonViewRadios) {
            radio.addEventListener('change', async (e) => {
                this._carbonView = e.target.value;
                await this.renderRoomChart();

                // If device detail view is visible, also re-render device chart
                const deviceDetailView = this.querySelector('#device-detail-view');
                if (deviceDetailView && deviceDetailView.style.display !== 'none') {
                    // Re-fetch room data to get updated values for the selected view
                    const data = this._groupBy === 'type'
                        ? await this.getCarbonByType()
                        : await this.getCarbonByRoom();

                    const updatedItem = this._findUpdatedSelectedGroup(data);
                    if (updatedItem) {
                        this._selectedRoom = updatedItem;
                        this.renderDeviceChart();
                    }
                }
            });
        }

        const applianceUsageToggle = this.querySelector('#appliance-usage-toggle');
        if (applianceUsageToggle) {
            applianceUsageToggle.addEventListener('click', async (e) => {
                const button = e.target.closest('button[data-appliance-usage]');
                if (!button) {
                    return;
                }

                this._showApplianceUsage = button.dataset.applianceUsage === 'true';
                this._updateApplianceUsageToggleState();
                await this.renderRoomChart();

                const deviceDetailView = this.querySelector('#device-detail-view');
                if (deviceDetailView && deviceDetailView.style.display !== 'none') {
                    const data = this._groupBy === 'type'
                        ? await this.getCarbonByType()
                        : await this.getCarbonByRoom();

                    const updatedItem = this._findUpdatedSelectedGroup(data);
                    if (updatedItem) {
                        this._selectedRoom = updatedItem;
                        this.renderDeviceChart();
                    }
                }
            });
        }

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.12'; // :skull:
        this.appendChild(link);
    }

    _updateApplianceUsageToggleState() {
        this._updateSegmentedToggleState('#appliance-usage-toggle', this._showApplianceUsage);
    }

    _updateSegmentedToggleState(selector, isOn) {
        const buttons = this.querySelectorAll(`${selector} button[data-appliance-usage]`);
        for (const button of buttons) {
            const isActive = (button.dataset.applianceUsage === 'true') === isOn;
            button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
            button.style.backgroundColor = isActive ? 'var(--primary-color, #03a9f4)' : '#f5f5f5';
            button.style.color = isActive ? '#fff' : '#333';
            button.style.fontWeight = isActive ? '600' : '400';
        }
    }

    _formatDateInputValue(date) {
        return date.toISOString().slice(0, 10);
    }

    _updateCustomTimeFrameControls() {
        const controls = this.querySelector('#custom-time-frame-controls');
        if (controls) {
            controls.style.display = this._currentTimeFrame === this._timeFrame.CUSTOM ? 'flex' : 'none';
        }
    }

    _getConsumptionHistogramTimeRange() {
        if (this._currentTimeFrame === this._timeFrame.CUSTOM) {
            const startTime = new Date(`${this._customStartDate}T00:00:00`);
            const endTime = new Date(`${this._customEndDate}T23:59:59`);
            return { startTime, endTime };
        }

        let pastDays;
        switch (this._currentTimeFrame) {
            case this._timeFrame.WEEK:
                pastDays = 7;
                break;
            case this._timeFrame.MONTH:
                pastDays = 30;
                break;
            case this._timeFrame.YEAR:
                pastDays = 365;
                break;
            default:
                pastDays = 7;
        }

        const endTime = new Date();
        const startTime = new Date(endTime);
        startTime.setDate(endTime.getDate() - pastDays);
        return { startTime, endTime };
    }

    _findUpdatedSelectedGroup(data) {
        if (!data || !this._selectedRoom) {
            return null;
        }

        const key = this._groupBy === 'type' ? 'type' : 'room';
        const selectedValue = this._selectedRoom[key];
        if (selectedValue === undefined || selectedValue === null) {
            return null;
        }

        return data.find(item => item[key] === selectedValue) || null;
    }


    setCarbonValue(value) {
        this._currentCarbonValue = value;
        const carbonSelector = this.querySelector('#device_carbon_footprint');
        carbonSelector.value = this._currentCarbonValue;
    }

    renderForm(devices) {

        return `

            <form id="add-device-form">
                <div>
                    <label for="device_name">Device</label>
                    <ha-selector id="device_selector"></ha-selector>
                </div>
                <div>
                    <label for="device_type">Device Type</label>
                    <ha-selector id="device_type_selector"></ha-selector>
                </div>
                <div>
                    <label for="carbon_footprint">Carbon Footprint (kgCO₂eq)</label>
                    <ha-selector id="device_carbon_footprint"></ha-selector>
                </div>
                <div class="button-group">
                    <button type="button" id="compute-footprint-btn">Compute Footprint</button>
                    <button type="submit">Add Device</button>
                    <button type="button" id="detect-devices-btn"><div class="loader" id="loader"></div>Automatic Setup</button>
                    <button type="button" id="export-json-btn">Export to JSON</button>
                </div>
            </form>
        `;
    }

    renderEnergyTable(devices) {
        if (!devices.length) {
            return `<p>No devices with measurable energy consumption found.</p>`;
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
                ${devices.map(device => `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.total_energy_kwh?.toFixed(2) ?? 'N/A'}</td>
                </tr>
                `).join('')}
            </tbody>
            </table>
        `;
    }

    async renderSettingsPage(data) {
        const devicesResp = await this._hass.callWS({ type: 'carbon_footprint/get_devices_to_add' });
        const devicesArray = devicesResp.device_names || [];
        const hasDevices = data && data.devices && Object.keys(data.devices).length > 0;

        const allDevicesEnergyResp = await this.getAllDevicesEnergy();
        const energyDevices = allDevicesEnergyResp.devices_energy || [];
        energyDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);

        this.innerHTML = `
            <ha-app-layout>
                <header class="ha-header" style="display: flex; justify-content: space-between; align-items: center;">
                    <h1>Carbon Footprint</h1>
                    <button id="back-btn" style="position: absolute; right: 20px; top: 15px; padding: 8px 16px; background-color: #03a9f4; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">← Back</button>
                </header>

                <div class="content" slot="content">
                    <ha-card header="Add New Device">
                        <div class="card-content">
                            ${this.renderForm(devicesArray)}
                        </div>
                    </ha-card>

                    <ha-card header="Configured Devices">
                        <div class="card-content device-list-container">
                            ${hasDevices ? `
                                <ul>
                                    ${Object.entries(data.devices).map(([device_id, info]) => `
                                        <li>
                                            <div class="device-info">
                                                <div class="device-header">
                                                    <h2><b>${info.metadata?.display_name || device_id}</b></h2><br>
                                                    <div class="device-extended">
                                                        Type: ${info.type || 'Unknown'}<br>
                                                        Area: ${info.metadata?.area_id || 'N/A'} <br>
                                                        Carbon: ${info.carbon_footprint || 0} kgCO₂eq <br>
                                                        Manfucturer: ${info.metadata?.manufacturer || 'N/A'}<br>
                                                        Model: ${info.metadata?.model || 'N/A'}<br>
                                                        Model ID: ${info.metadata?.model_id || 'N/A'}<br>
                                                        Class: ${info.metadata?.device_classes || 'N/A'}<br>
                                                        HA ID: ${device_id || 'UNKNOWN'} <br>
                                                        Total Energy Consumed: ${info.metadata?.total_energy || 'N/A'}<br>
                                                    </div>
                                                </div>
                                                <button
                                                    type="button"
                                                    class="extend-btn"
                                                    title="More information">
                                                    ▼
                                                </button>
                                                <button
                                                    type="button"
                                                    class="delete-btn"
                                                    data-entity-id="${device_id}"
                                                    title="Remove device">
                                                    ✕
                                                </button>
                                            </div>
                                        </li>
                                    `).join('')}
                                </ul>
                            ` : `<p>No devices configured yet.</p>`}
                        </div>
                    </ha-card>
                </div>
            </ha-app-layout>
        `;

        const backBtn = this.querySelector('#back-btn');
        if (backBtn) {
            backBtn.addEventListener('click', async () => {
                this._currentPage = 'main';
                const newData = await this.getCarbonData();
                await this.render(newData);
            });
        }

        const sortSelect = this.querySelector('#sort-mode');
        const tableContainer = this.querySelector('#energy-table-container');

        if (sortSelect && tableContainer) {
            sortSelect.addEventListener('change', () => {
                let sortedDevices = [...energyDevices];
                if (sortSelect.value === 'energy') {
                    sortedDevices.sort((a, b) => b.total_energy_kwh - a.total_energy_kwh);
                } else if (sortSelect.value === 'name') {
                    sortedDevices.sort((a, b) => a.device_name.localeCompare(b.device_name));
                }
                tableContainer.innerHTML = this.renderEnergyTable(sortedDevices);
            });
        }

        this.attachFormHandler();

        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/api/carbon_footprint/style.css?version=1.18'; // :skull:
        this.appendChild(link);
    }

    showLoadingOverlay(message = 'Loading...') {
        this.hideLoadingOverlay();

        const overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-content">
                <div class="spinner"></div>
                <p>${message}</p>
                <div class="progress-cont">
                    <div class="progress-bar"></div>
                </div>
            </div>
        `;

        this.appendChild(overlay);

    }

    hideLoadingOverlay() {
        const overlay = this.querySelector('#loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    async detectDevicesType(detectBtn, loaderAnim) {
        const devicesResp = await this._hass.callWS({ type: 'carbon_footprint/get_devices_to_add' });
        let deviceIds = devicesResp.device_ids || [];
        let deviceNames = devicesResp.device_names || [];
        let deviceModels = devicesResp.device_models || [];
        let deviceManufacturers = devicesResp.device_manufacturers || [];


        let devicesDict = {};

        let typedDevices = {};
        let unmatchedDevices = [];
        for (let i = 0; i < deviceNames.length; i++) {
            let infoDict = {};
            infoDict['model'] = deviceModels[i];
            infoDict['manufacturer'] = deviceManufacturers[i];
            devicesDict[deviceNames[i]] = infoDict;
        }

        let nbDevices = deviceNames.length;
        let chunkSize = Math.round(nbDevices / 10);
        let successfulBatches = 0;

        const totalRuns = Math.max(1, Math.ceil(nbDevices / chunkSize));
        const percentIncrement = Math.round(100 / totalRuns);

        try {
            this.showLoadingOverlay('Detecting device types...');
            const progressBar = this.querySelector(".progress-bar");

            progressBar.style.width = '0%';
            console.log(`Chunked data dictionary into chunks of ${chunkSize} devices`)

            for (let i = 0; i < nbDevices; i += chunkSize) {
                const chunkDevicesDict = Object.fromEntries(Object.entries(devicesDict).slice(i, i + chunkSize));
                const chunkDeviceIds = deviceIds.slice(i, i + chunkSize);
                console.log(`Running device type detection, run ${i/chunkSize}. Sent devices are: ${JSON.stringify(chunkDevicesDict, null, '\t')}`);
                try {
                    const llmResp = await this._hass.callWS({
                        type: 'carbon_footprint/llm_detection',
                        devices: chunkDevicesDict
                    });
                    let deviceTypes = JSON.parse(llmResp.device_types || "{}");
                    let unmatchedDevicesTypes = JSON.parse(llmResp.unmatched_devices || "{}")
                    Object.keys(chunkDevicesDict).forEach((key, idx) => {
                        if (key in unmatchedDevicesTypes) {
                            unmatchedDevices.push(key);
                        } else {
                            devicesDict[key].device_type = deviceTypes[key] ?? "unknown";
                            devicesDict[key].device_id = chunkDeviceIds[idx] ?? null;
                            typedDevices[key] = devicesDict[key];
                        }
                    });
                    console.log(`Batch ${i / chunkSize} successfully detected, continuing`);
                    successfulBatches++;
                } catch (error) {
                    console.error(`Failed detection for batch ${i/chunkSize} with error: ${error.message || error.code}`);
                    let j = 0;
                    Object.keys(chunkDevicesDict).forEach((key, idx) => {
                        devicesDict[key].device_type = "error";
                        devicesDict[key].device_id = chunkDeviceIds[idx] ?? null;
                        unmatchedDevices.push(key);
                    });
                } finally {
                    const current = parseFloat(progressBar.style.width) || 0;
                    progressBar.style.width = `${Math.min(100, current + percentIncrement)}%`;
                }
            }
            if (unmatchedDevices.length != 0) {
                console.log(`Could not detect device type for devices ${unmatchedDevices.toString()}`);
            }
            console.log('Device Types Detection ended, continuing...');

            const devicesToSend = Object.fromEntries(
                Object.entries(typedDevices).filter(([name, info]) => {
                    const t = info?.device_type;
                    return typeof t === 'string' && t.length > 0 && t !== 'error';
                })
            );
            this.showLoadingOverlay('Matching devices with database...');

            console.log(`Sending ${JSON.stringify(devicesToSend, null, '\t')}`);
            const dbMatchingResp = await this._hass.callWS({
                type: 'carbon_footprint/db_matching',
                device_types: devicesToSend,
            });
            let devicesMatched = dbMatchingResp.devices_matched;
            console.log(`Matched ${JSON.stringify(devicesMatched, null, '\t')}`);


            //flow: Once we got the device types: pull the db and match carbon values, this will automatically setup everything where possible.
            //idea: pass the device_types json as argument for another websocket, which will return another json in the following format:
            //{
            //  "<device_name>" : {
            //      "device_type": "<type>"
            //      "carbon_footprint": "<value>"
            //  }
            //}
            //then use this for set_device

            if (progressBar) progressBar.style.width = '100%';
            this.showLoadingOverlay('Adding devices to Carbon Footprint Integration...');
            for (const [deviceName, deviceInfo] of Object.entries(devicesMatched)) {
                console.log(`Processing ${deviceName}: `, deviceInfo)
                await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        device_name: deviceName,
                        device_type: deviceInfo.device_type,
                        carbon_footprint: deviceInfo.carbon_footprint,
                        metadata: {}
                    });
            }
        } catch (error) {
            console.error('LLM detection failed:', error);
            alert(`Device type detection failed: ${error.message || error.code}`);
        }
        finally {
            this.hideLoadingOverlay();
            detectBtn.disabled = false;
            loaderAnim.style.display = 'none';
            const updatedData = await this.getCarbonData();
            await this.renderSettingsPage(updatedData);
            if (unmatchedDevices.length != 0) {
                Utils.showToast(this, `Could not detect device type for devices ${unmatchedDevices.toString()}`);
                console.log(`Could not detect device type for devices ${unmatchedDevices.toString()}`);
            }
            else {
                Utils.showToast(this, `Successfully detected all device types`);
            }
        }
    }

    async renderConsumptionHistogram() {
        const canvas = this.querySelector('#consumption-histogram-chart');
        if (!canvas) {
            return;
        }
        const canvasContainer = canvas.parentElement;
        const showEmptyConsumptionChartMessage = (message) => {
            if (this._consumptionChart) {
                this._consumptionChart.destroy();
                this._consumptionChart = null;
            }
            if (canvasContainer) {
                canvasContainer.style.display = 'none';
                let emptyMessage = canvasContainer.nextElementSibling;
                if (!emptyMessage || emptyMessage.id !== 'consumption-empty-message') {
                    emptyMessage = document.createElement('p');
                    emptyMessage.id = 'consumption-empty-message';
                    emptyMessage.style.margin = '16px 0';
                    emptyMessage.style.color = '#666';
                    canvasContainer.insertAdjacentElement('afterend', emptyMessage);
                }
                emptyMessage.textContent = message;
                emptyMessage.style.display = 'block';
            }
        };
        const hideEmptyConsumptionChartMessage = () => {
            if (canvasContainer) {
                canvasContainer.style.display = '';
                const emptyMessage = canvasContainer.nextElementSibling;
                if (emptyMessage?.id === 'consumption-empty-message') {
                    emptyMessage.style.display = 'none';
                }
            }
        };

        const { startTime, endTime } = this._getConsumptionHistogramTimeRange();

        let consumptionData;
        let embodiedData;
        let deviceNameMap = {};

        if (this._useFakeConsumptionData) {
            const fakeData = this._getFakeConsumptionHistogramData(startTime, endTime);
            consumptionData = this._ecView === 'appliance'
                ? fakeData.appliance_consumptions
                : (this._showEnergyApplianceUsage
                    ? this._mergeDeviceTimeSeriesData(fakeData.devices_consumptions, fakeData.appliance_consumptions)
                    : fakeData.devices_consumptions);
            embodiedData = fakeData.embodied_carbon;
            deviceNameMap = fakeData.device_name_map || {};
            console.log('Using fake consumption histogram data:', fakeData);
        } else {
            const result = await this._hass.callWS({
                type: 'carbon_footprint/get_consumption_footprint_time_interval',
                start_time: startTime.toISOString(),
                end_time: endTime.toISOString(),
                granularity: this._currentChartGranularity,
                is_appliance: false
            });

            consumptionData = result.devices_consumptions;
            deviceNameMap = result.device_name_map || {};

            if (this._showEnergyApplianceUsage || this._ecView == 'appliance') {
                const applianceResult = await this._hass.callWS({
                    type: 'carbon_footprint/get_consumption_footprint_time_interval',
                    start_time: startTime.toISOString(),
                    end_time: endTime.toISOString(),
                    granularity: this._currentChartGranularity,
                    is_appliance: true
                });

                consumptionData = this._ecView === 'appliance'
                    ? applianceResult.devices_consumptions
                    : this._mergeDeviceTimeSeriesData(consumptionData, applianceResult.devices_consumptions);
                deviceNameMap = {
                    ...deviceNameMap,
                    ...(applianceResult.device_name_map || {}),
                };
            }
        }
        //if (!consumptionData || Object.keys(consumptionData).length === 0) {
        //    canvas.parentElement.innerHTML = '<p>No consumption data available for the selected period.</p>';
        //    return;
        //}

        if (!this._useFakeConsumptionData) {
            const embodiedResult = (this._ecView == 'total' || this._ecView == 'embodied') ? await this._hass.callWS({
                type: 'carbon_footprint/get_embodied_carbon_time_interval',
                start_time: startTime.toISOString(),
                end_time: endTime.toISOString(),
                granularity: this._currentChartGranularity
            }) : {};

            embodiedData = embodiedResult.embodied_carbon || {};
        }

        const aggData = {};

        const procData = (data, type) => {
            if (!data) {
                return;
            }
            for (const deviceId in data) {
                if (data[deviceId]) {
                    data[deviceId].forEach(point => {
                        const date = new Date(point.timestamp);
                        const groupKey = Utils.getDateGroupKey(date, this._currentChartGranularity, this._chartGranularity);

                        if (!aggData[groupKey]) {
                            aggData[groupKey] = {};
                        }
                        if (!aggData[groupKey][deviceId]) {
                            aggData[groupKey][deviceId] = { consumption: 0, embodied: 0 };
                        }
                        aggData[groupKey][deviceId][type] += point.consumption_footprint || point.embodied_footprint || 0;
                    });
                }
            }
        };
        if (this._ecView == 'total' || this._ecView == 'usage' || this._ecView === 'appliance') procData(consumptionData, `consumption`);
        procData(embodiedData, `embodied`);
        const sortedTimestamps = Object.keys(aggData).sort();
        const hasConsumptionData = sortedTimestamps.some(ts => {
            const devices = aggData[ts] || {};
            return Object.values(devices).some(deviceData => (deviceData.consumption || 0) > 0);
        });
        if (this._ecView === 'appliance' && !hasConsumptionData) {
            showEmptyConsumptionChartMessage('No appliances available for the selected period.');
            return;
        }
        hideEmptyConsumptionChartMessage();

        const labels = sortedTimestamps.map(ts => {
            const date = new Date(ts);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit' });
                case this._chartGranularity.DAY:
                    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
                case this._chartGranularity.MONTH:
                    return date.toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' });
                default:
                    return date.toLocaleString();
            }
        });

        const baseColors = [
            'rgba(76, 175, 80, 0.6)',
            'rgba(33, 150, 243, 0.6)',
        ];

        const datasets = [];
        const ctx = canvas.getContext('2d');

        const sumByTimestamp = (ts, type) => {
            const devices = aggData[ts] || {};
            return Object.values(devices).reduce((sum, deviceData) => sum + (deviceData[type] || 0), 0);
        };
        const formatKgCO2 = grams => `${(grams / 1000).toFixed(3)} kgCO₂eq`;

        if (this._ecView === 'total' || this._ecView === 'embodied') {
            const embodiedDataPoints = sortedTimestamps.map(ts => sumByTimestamp(ts, 'embodied'));
            datasets.push({
                label: 'Embodied Carbon',
                data: embodiedDataPoints,
                backgroundColor: this._ecView === 'total' ? this._createHatchPattern(ctx, baseColors[0]) : baseColors[0],
                metricType: 'embodied',
                stack: 'all-devices',
            });
        }

        if (this._ecView === 'total' || this._ecView === 'usage' || this._ecView === 'appliance') {
            const usageData = sortedTimestamps.map(ts => sumByTimestamp(ts, 'consumption'));
            datasets.push({
                label: this._ecView === 'appliance' ? 'Appliance Usage Carbon' : 'Usage Carbon',
                data: usageData,
                backgroundColor: this._ecView === 'appliance' ? 'rgba(255, 152, 0, 0.6)' : baseColors[1],
                metricType: 'consumption',
                stack: 'all-devices',
            });
        }

        if (this._consumptionChart) {
            this._consumptionChart.destroy();
        }

        this._consumptionChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 },
                            generateLabels: () => {
                                const labels = [];
                                if (this._ecView === 'total') {
                                    labels.push({
                                        text: 'Embodied (hatched)',
                                        fillStyle: this._createHatchPattern(ctx, baseColors[0]),
                                    });
                                    labels.push({
                                        text: 'Usage (solid)',
                                        fillStyle: baseColors[1],
                                    });
                                } else if (this._ecView === 'embodied') {
                                    labels.push({
                                        text: 'Embodied Carbon',
                                        fillStyle: baseColors[0],
                                    });
                                } else if (this._ecView === 'appliance') {
                                    labels.push({
                                        text: 'Appliance Usage Carbon',
                                        fillStyle: 'rgba(255, 152, 0, 0.6)',
                                    });
                                } else {
                                    labels.push({
                                        text: 'Usage Carbon',
                                        fillStyle: baseColors[1],
                                    });
                                }

                                return labels;
                            }
                        },
                    },
                    title: {
                        display: true,
                        text: 'Energy Consumption Footprint (gCO₂eq)',
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const metricType = context.dataset.metricType;
                                const timestamp = sortedTimestamps[context.dataIndex];
                                const devices = aggData[timestamp] || {};
                                const deviceBreakdown = Object.entries(devices)
                                    .map(([deviceId, values]) => ({
                                        name: deviceNameMap[deviceId] || deviceId,
                                        value: values[metricType] || 0,
                                    }))
                                    .filter(item => item.value > 0)
                                    .sort((a, b) => b.value - a.value);

                                const lines = [`${context.dataset.label}: ${formatKgCO2(context.parsed.y)}`];
                                if (deviceBreakdown.length) {
                                    lines.push('Devices:');
                                    deviceBreakdown.forEach(item => {
                                        lines.push(`${item.name}: ${formatKgCO2(item.value)}`);
                                    });
                                }
                                return lines;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'gCO₂eq'
                        }
                    }
                }
            }
        });
    }

    renderHistogram() {
        const canvas = this.querySelector('#energy-histogram-chart');
        if (!canvas || !this._histogramData) {
            return;
        }

        const labels = this._histogramData.map(point => {
            const date = new Date(point.timestamp);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    return date.toLocaleDateString('fr-FR', {
                        day: '2-digit',
                        month: '2-digit',
                        hour: '2-digit'
                    });
                case this._chartGranularity.DAY:
                    return date.toLocaleDateString('fr-FR', {
                        day: '2-digit',
                        month: '2-digit',
                    });
                case this._chartGranularity.MONTH:
                    return date.toLocaleDateString('fr-FR', {
                        month: '2-digit',
                        year: 'numeric'
                    });
            }
        });

        const values = this._histogramData.map(point => point.energy_footprint);
        if (this._chart) {
            this._chart.destroy();
        }
        this._chart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'CO₂ intensity (gCO₂eq/kWh)',
                    data: values,
                    backgroundColor: 'rgba(3, 169, 244, 0.5)',
                    borderColor: 'rgb(3, 169, 244)',
                    borderWidth: 0,
                }]
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
                            label: (context) => `${context.parsed.y.toFixed(1)} gCO₂eq/kWh`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'gCO₂eq/kWh'
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45
                        }
                    }
                }
            }
        });
    }

    _createHatchPattern(ctx, color) { // made with the help of chatgpt
        const patternCanvas = document.createElement('canvas');
        patternCanvas.width = 16;
        patternCanvas.height = 16;

        const pctx = patternCanvas.getContext('2d');

        pctx.fillStyle = color;
        pctx.fillRect(0, 0, patternCanvas.width, patternCanvas.height);

        // diagonal hatch lines
        pctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
        pctx.lineWidth = 1.5;

        pctx.beginPath();
        pctx.moveTo(0, 16);
        pctx.lineTo(16, 0);
        pctx.stroke();

        pctx.beginPath();
        pctx.moveTo(-4, 12);
        pctx.lineTo(4, 4);
        pctx.stroke();

        pctx.beginPath();
        pctx.moveTo(12, 20);
        pctx.lineTo(20, 12);
        pctx.stroke();

        return ctx.createPattern(patternCanvas, 'repeat');
    }

    // ============================================================================
    // TEST DATA TOGGLES
    // ============================================================================
    // _useFakeCarbonData: Uses generic fake lab data (Kitchen, Bedroom, etc.)
    //   - Good for UI/visualization testing
    //   - Doesn't depend on backend or real devices
    //
    // _useFakeRoomData: Uses test data from test_data.py (requires TEST_MODE=True)
    //   - Good for recommendation system testing
    //   - Matches real device structure (Living Room, Kitchen, Bedroom)
    //   - Doesn't interfere with real device data collection
    //
    // Set either to true to enable test mode. Example:
    //   this._useFakeRoomData = true;  // Test recommendations without real devices
    // ============================================================================

    // turn on/off fake data here
    _useFakeCarbonData = false;
    _useFakeRoomData = false;  // Toggle for test data (from test_data.py) - doesn't affect real devices
    _useFakeConsumptionData = false; // Toggle for Energy Consumption Footprint chart testing
    _hiddenRoomIndices = new Set();

    _getFakeConsumptionHistogramData(startTime, endTime) {
        const stepDate = (date) => {
            const nextDate = new Date(date);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    nextDate.setHours(nextDate.getHours() + 1);
                    break;
                case this._chartGranularity.MONTH:
                    nextDate.setMonth(nextDate.getMonth() + 1);
                    break;
                case this._chartGranularity.DAY:
                default:
                    nextDate.setDate(nextDate.getDate() + 1);
                    break;
            }
            return nextDate;
        };

        const alignDate = (date) => {
            const aligned = new Date(date);
            switch (this._currentChartGranularity) {
                case this._chartGranularity.HOUR:
                    aligned.setMinutes(0, 0, 0);
                    break;
                case this._chartGranularity.MONTH:
                    aligned.setDate(1);
                    aligned.setHours(0, 0, 0, 0);
                    break;
                case this._chartGranularity.DAY:
                default:
                    aligned.setHours(0, 0, 0, 0);
                    break;
            }
            return aligned;
        };

        const maxPoints = this._currentChartGranularity === this._chartGranularity.HOUR ? 12 : 8;
        const timestamps = [];
        let cursor = alignDate(startTime);
        while (cursor <= endTime && timestamps.length < maxPoints) {
            timestamps.push(new Date(cursor));
            cursor = stepDate(cursor);
        }

        const devices = [
            { id: 'fake_living_lamp', usageStart: 18, embodiedStart: 7 },
            { id: 'fake_rpi_plug', usageStart: 10, embodiedStart: 3 },
        ];

        const devices_consumptions = {};
        const appliance_consumptions = {};
        const embodied_carbon = {};
        for (const device of devices) {
            devices_consumptions[device.id] = [];
            embodied_carbon[device.id] = [];
            timestamps.forEach((timestamp, index) => {
                devices_consumptions[device.id].push({
                    timestamp: timestamp.toISOString(),
                    consumption_footprint: device.usageStart + index * 4,
                });
                embodied_carbon[device.id].push({
                    timestamp: timestamp.toISOString(),
                    embodied_footprint: device.embodiedStart + index,
                });
            });
        }

        appliance_consumptions.fake_kitchen_air_fryer = timestamps.map((timestamp, index) => ({
            timestamp: timestamp.toISOString(),
            consumption_footprint: 14 + index * 3,
        }));

        return {
            devices_consumptions,
            appliance_consumptions,
            embodied_carbon,
            device_name_map: {
                fake_living_lamp: 'Living lamp',
                fake_rpi_plug: 'Rpi plug',
                fake_kitchen_air_fryer: 'Kitchen air fryer',
            },
        };
    }

    _mergeDeviceTimeSeriesData(baseData = {}, extraData = {}) {
        const merged = {};
        for (const [deviceId, points] of Object.entries(baseData || {})) {
            merged[deviceId] = [...(points || [])];
        }

        for (const [deviceId, points] of Object.entries(extraData || {})) {
            if (!merged[deviceId]) {
                merged[deviceId] = [];
            }
            merged[deviceId].push(...(points || []));
        }

        return merged;
    }

    _mergeApplianceUsageData(baseData, applianceData) {
        const keyForGroup = item => item.room || item.type || 'Unknown';
        const keyForDevice = device => device.id || device.name;
        const applianceGroups = new Map(applianceData.map(item => [keyForGroup(item), item]));

        return baseData.map(item => {
            const applianceItem = applianceGroups.get(keyForGroup(item)) || {};
            const applianceDevices = new Map((applianceItem.devices || []).map(device => [keyForDevice(device), device]));

            const devices = (item.devices || []).map(device => {
                const applianceDevice = applianceDevices.get(keyForDevice(device)) || {};
                const usageCarbon = (device.usage_carbon || 0) + (applianceDevice.usage_carbon || 0);
                const predictedCarbon = (device.predicted_carbon || 0) + (applianceDevice.predicted_carbon || 0);

                return {
                    ...device,
                    usage_carbon: usageCarbon,
                    appliance_usage_carbon: applianceDevice.usage_carbon || 0,
                    predicted_carbon: predictedCarbon,
                    appliance_predicted_carbon: applianceDevice.predicted_carbon || 0,
                    total_carbon: (device.embodied_carbon || 0) + usageCarbon,
                };
            });

            for (const [deviceKey, applianceDevice] of applianceDevices) {
                if (devices.some(device => keyForDevice(device) === deviceKey)) {
                    continue;
                }

                devices.push({
                    ...applianceDevice,
                    embodied_carbon: applianceDevice.embodied_carbon || 0,
                    appliance_usage_carbon: applianceDevice.usage_carbon || 0,
                    appliance_predicted_carbon: applianceDevice.predicted_carbon || 0,
                    total_carbon: (applianceDevice.embodied_carbon || 0) + (applianceDevice.usage_carbon || 0),
                });
            }

            const usageCarbon = devices.reduce((sum, device) => sum + (device.usage_carbon || 0), 0);
            const applianceUsageCarbon = devices.reduce((sum, device) => sum + (device.appliance_usage_carbon || 0), 0);
            const predictedCarbon = devices.reduce((sum, device) => sum + (device.predicted_carbon || 0), 0);
            const appliancePredictedCarbon = devices.reduce((sum, device) => sum + (device.appliance_predicted_carbon || 0), 0);

            return {
                ...item,
                usage_carbon: usageCarbon,
                appliance_usage_carbon: applianceUsageCarbon,
                predicted_carbon: predictedCarbon,
                appliance_predicted_carbon: appliancePredictedCarbon,
                total_carbon: (item.embodied_carbon || 0) + usageCarbon,
                devices,
            };
        });
    }

    _normalizeApplianceOnlyData(applianceData) {
        return (applianceData || []).map(item => {
            const sourceDevices = item.devices || [];
            const applianceDevices = sourceDevices.filter(device => this._isExplicitApplianceDevice(device));

            const devices = applianceDevices.map(device => {
                const applianceUsageCarbon = device.appliance_usage_carbon ?? device.usage_carbon ?? 0;
                const appliancePredictedCarbon = device.appliance_predicted_carbon ?? device.predicted_carbon ?? 0;

                return {
                    ...device,
                    embodied_carbon: 0,
                    usage_carbon: 0,
                    appliance_usage_carbon: applianceUsageCarbon,
                    predicted_carbon: 0,
                    appliance_predicted_carbon: appliancePredictedCarbon,
                    total_carbon: applianceUsageCarbon,
                };
            });

            const applianceUsageCarbon = devices.reduce((sum, device) => sum + (device.appliance_usage_carbon || 0), 0);
            const appliancePredictedCarbon = devices.reduce((sum, device) => sum + (device.appliance_predicted_carbon || 0), 0);

            return {
                ...item,
                embodied_carbon: 0,
                usage_carbon: 0,
                appliance_usage_carbon: applianceUsageCarbon,
                predicted_carbon: 0,
                appliance_predicted_carbon: appliancePredictedCarbon,
                total_carbon: applianceUsageCarbon,
                devices,
            };
        });
    }

    _isExplicitApplianceDevice(device) {
        const name = `${device?.name || ''} ${device?.id || ''}`.toLowerCase();
        return name.includes('appliance') && !name.includes('plug');
    }

    _getFakeDataForCurrentView(data) {
        if (this._carbonView === 'appliance') {
            return this._normalizeApplianceOnlyData(data);
        }

        if (!this._showApplianceUsage) {
            return data.map(room => ({
                ...room,
                devices: (room.devices || []).filter(device =>
                    (device.embodied_carbon || 0) !== 0 ||
                    (device.usage_carbon || 0) !== 0 ||
                    (device.predicted_carbon || 0) !== 0
                ),
            }));
        }

        return data.map(room => {
            const devices = (room.devices || []).map(device => {
                const applianceUsageCarbon = device.appliance_usage_carbon || 0;
                const appliancePredictedCarbon = device.appliance_predicted_carbon || 0;
                const usageCarbon = (device.usage_carbon || 0) + applianceUsageCarbon;
                const predictedCarbon = (device.predicted_carbon || 0) + appliancePredictedCarbon;

                return {
                    ...device,
                    usage_carbon: usageCarbon,
                    appliance_usage_carbon: applianceUsageCarbon,
                    predicted_carbon: predictedCarbon,
                    appliance_predicted_carbon: appliancePredictedCarbon,
                    total_carbon: (device.embodied_carbon || 0) + usageCarbon,
                };
            });

            const usageCarbon = devices.reduce((sum, device) => sum + (device.usage_carbon || 0), 0);
            const applianceUsageCarbon = devices.reduce((sum, device) => sum + (device.appliance_usage_carbon || 0), 0);
            const predictedCarbon = devices.reduce((sum, device) => sum + (device.predicted_carbon || 0), 0);
            const appliancePredictedCarbon = devices.reduce((sum, device) => sum + (device.appliance_predicted_carbon || 0), 0);

            return {
                ...room,
                usage_carbon: usageCarbon,
                appliance_usage_carbon: applianceUsageCarbon,
                predicted_carbon: predictedCarbon,
                appliance_predicted_carbon: appliancePredictedCarbon,
                total_carbon: (room.embodied_carbon || 0) + usageCarbon,
                devices,
            };
        });
    }

    _getFakeCarbonDataForCurrentView() {
        return this._getFakeDataForCurrentView(this._getFakeCarbonData());
    }

    _getFakeRoomDataForCurrentView() {
        return this._getFakeDataForCurrentView(this._getFakeRoomData());
    }

    _getFakeCarbonData() {
        return [
            {
                room: 'Kitchen',
                embodied_carbon: 120,
                usage_carbon: 80,
                total_carbon: 200,
                predicted_carbon: 260,
                devices: [
                    { name: 'Fridge plug', embodied_carbon: 50, usage_carbon: 30, appliance_usage_carbon: 24, total_carbon: 80, predicted_carbon: 100, appliance_predicted_carbon: 82 },
                    { name: 'Oven plug', embodied_carbon: 40, usage_carbon: 25, appliance_usage_carbon: 18, total_carbon: 65, predicted_carbon: 85, appliance_predicted_carbon: 61 },
                    { name: 'Dishwasher plug', embodied_carbon: 30, usage_carbon: 25, appliance_usage_carbon: 20, total_carbon: 55, predicted_carbon: 75, appliance_predicted_carbon: 60 },                ]
            },
            {
                room: 'Bedroom',
                embodied_carbon: 90,
                usage_carbon: 110,
                total_carbon: 200,
                predicted_carbon: 250,
                devices: [
                    { name: 'Lamp plug', embodied_carbon: 10, usage_carbon: 20, appliance_usage_carbon: 3, total_carbon: 30, predicted_carbon: 35, appliance_predicted_carbon: 5 },
                    { name: 'Heater plug', embodied_carbon: 35, usage_carbon: 60, appliance_usage_carbon: 52, total_carbon: 95, predicted_carbon: 125, appliance_predicted_carbon: 108 },
                    { name: 'Fan plug', embodied_carbon: 15, usage_carbon: 10, appliance_usage_carbon: 7, total_carbon: 25, predicted_carbon: 30, appliance_predicted_carbon: 21 },
                    { name: 'TV plug', embodied_carbon: 30, usage_carbon: 20, appliance_usage_carbon: 14, total_carbon: 50, predicted_carbon: 60, appliance_predicted_carbon: 42 },
                ]
            },
            {
                room: 'Living Room',
                embodied_carbon: 70,
                usage_carbon: 30,
                total_carbon: 100,
                predicted_carbon: 140,
                devices: [
                    { name: 'TV plug', embodied_carbon: 25, usage_carbon: 10, appliance_usage_carbon: 8, total_carbon: 35, predicted_carbon: 45, appliance_predicted_carbon: 36 },
                    { name: 'Speaker plug', embodied_carbon: 15, usage_carbon: 5, appliance_usage_carbon: 2, total_carbon: 20, predicted_carbon: 28, appliance_predicted_carbon: 11 },
                    { name: 'Game Console plug', embodied_carbon: 30, usage_carbon: 15, appliance_usage_carbon: 12, total_carbon: 45, predicted_carbon: 67, appliance_predicted_carbon: 54 },
                ]
            },
            {
                room: 'Unknown Room',
                embodied_carbon: 20,
                usage_carbon: 15,
                total_carbon: 35,
                predicted_carbon: 50,
                devices: [
                    { name: 'Unknown plug A', embodied_carbon: 10, usage_carbon: 5, appliance_usage_carbon: 0, total_carbon: 15, predicted_carbon: 20, appliance_predicted_carbon: 0 },
                    { name: 'Unknown plug B', embodied_carbon: 10, usage_carbon: 10, appliance_usage_carbon: 6, total_carbon: 20, predicted_carbon: 30, appliance_predicted_carbon: 18 },
                ]
            }
        ];
    }

    _getFakeRoomData() {
        // Test data matching test_data.py structure from async_setup_test_data
        // This provides consistent test data for the recommendation system
        return [
            {
                room: 'Bedroom',
                room_id: 'fake_bedroom',
                embodied_carbon: 12.0,
                usage_carbon: 1.8,
                predicted_carbon: 2.7,
                total_carbon: 13.8,
                devices: [
                    { id: 'Bedroom AC Unit', name: 'Bedroom AC Unit plug', embodied_carbon: 12.0, usage_carbon: 1.8, appliance_usage_carbon: 1.4, predicted_carbon: 2.7, appliance_predicted_carbon: 2.1, total_carbon: 13.8 }
                ]
            },
            {
                room: 'Kitchen',
                room_id: 'fake_kitchen',
                embodied_carbon: 58.0,
                usage_carbon: 3.5,
                predicted_carbon: 5.25,
                total_carbon: 61.5,
                devices: [
                    { id: 'Kitchen Refrigerator', name: 'Kitchen Refrigerator plug', embodied_carbon: 35.0, usage_carbon: 2.5, appliance_usage_carbon: 2.1, predicted_carbon: 3.75, appliance_predicted_carbon: 3.15, total_carbon: 37.5 },
                    { id: 'Kitchen Dishwasher', name: 'Kitchen Dishwasher plug', embodied_carbon: 18.5, usage_carbon: 0.8, appliance_usage_carbon: 0.6, predicted_carbon: 1.2, appliance_predicted_carbon: 0.9, total_carbon: 19.3 },
                    { id: 'Kitchen Coffee Maker', name: 'Kitchen Coffee Maker plug', embodied_carbon: 4.5, usage_carbon: 0.2, appliance_usage_carbon: 0.1, predicted_carbon: 0.3, appliance_predicted_carbon: 0.15, total_carbon: 4.7 }
                ]
            },
            {
                room: 'Living Room',
                room_id: 'fake_living_room',
                embodied_carbon: 45.0,
                usage_carbon: 3.8,
                predicted_carbon: 5.7,
                total_carbon: 48.8,
                devices: [
                    { id: 'Living Room TV', name: 'Living Room TV plug', embodied_carbon: 15.5, usage_carbon: 0.5, appliance_usage_carbon: 0.35, predicted_carbon: 0.75, appliance_predicted_carbon: 0.52, total_carbon: 16.0 },
                    { id: 'Living Room Heater', name: 'Living Room Heater plug', embodied_carbon: 22.3, usage_carbon: 3.2, appliance_usage_carbon: 2.6, predicted_carbon: 4.8, appliance_predicted_carbon: 3.9, total_carbon: 25.5 },
                    { id: 'Living Room Smart Speaker', name: 'Living Room Smart Speaker plug', embodied_carbon: 7.2, usage_carbon: 0.1, appliance_usage_carbon: 0.04, predicted_carbon: 0.15, appliance_predicted_carbon: 0.06, total_carbon: 7.35 }
                ]
            }
        ];
    }

    async renderRoomChart() {
        let canvas = this.querySelector('#room-pie-chart');
        if (!canvas) {
            const container = this.querySelector('#room-chart-view');
            if (container) {
                container.innerHTML = `
                    <div style="position: relative; height: 400px; width: 100%;">
                        <canvas id="room-pie-chart"></canvas>
                    </div>
                `;
                canvas = this.querySelector('#room-pie-chart');
            }
        }

        if (!canvas) {
            return;
        }

        let data;
        if (this._useFakeCarbonData) {
            data = this._getFakeCarbonDataForCurrentView();
            console.log('Using fake carbon data for room chart:', data);
        } else if (this._useFakeRoomData) {
            // Use test data from test_data.py (only for testing recommendation system)
            data = this._getFakeRoomDataForCurrentView();
            console.log('Using fake room data (test_data.py) for testing:', data);
        } else if (this._groupBy === 'type') {
            data = await this.getCarbonByType();
        } else {
            data = await this.getCarbonByRoom();
        }

        if (!data || data.length === 0) {
            const container = this.querySelector('#room-chart-view');
            if (this._roomChart) {
                this._roomChart.destroy();
                this._roomChart = null;
            }
            if (container) {
                const groupLabel = this._groupBy === 'type' ? 'type' : 'room';
                container.innerHTML = `<p>No ${groupLabel} data available</p>`;
            }
            return;
        }

        const hasApplianceDevices = data.some(item => (item.devices || []).length > 0);
        const hasApplianceCarbon = data.some(item => (item.appliance_usage_carbon ?? item.usage_carbon ?? 0) > 0);
        if (this._carbonView === 'appliance' && (!hasApplianceDevices || !hasApplianceCarbon)) {
            const container = this.querySelector('#room-chart-view');
            if (this._roomChart) {
                this._roomChart.destroy();
                this._roomChart = null;
            }
            if (container) {
                container.innerHTML = '<p>No appliances available.</p>';
            }
            return;
        }

        const ctx = canvas.getContext('2d');

        const baseColors = [
            'rgba(76, 175, 80, 0.6)',   // Green
            'rgba(33, 150, 243, 0.6)',  // Blue
            'rgba(255, 152, 0, 0.6)',   // Orange
            'rgba(244, 67, 54, 0.6)',   // Red
            'rgba(156, 39, 176, 0.6)',  // Purple
            'rgba(0, 150, 136, 0.6)',   // Teal
        ];

        const solidBorderColors = baseColors.map(c => c.replace('0.6', '1'));

        if (this._roomChart) {
            this._roomChart.destroy();
        }

        let chartData;
        let chartOptions;

        if (this._carbonView === 'total') {
            const labels = [];
            const values = [];
            const backgroundColors = [];
            const borderColors = [];

            data.forEach((item, index) => {
                const label = item.room || item.type || 'Unknown';
                const baseColor = baseColors[index % baseColors.length];
                const borderColor = solidBorderColors[index % solidBorderColors.length];
                const hatchPattern = this._createHatchPattern(ctx, baseColor);

                const isHidden = this._hiddenRoomIndices.has(index);

                // embodied slice
                labels.push(`${label} - Embodied`);
                values.push(isHidden ? 0 : (item.embodied_carbon || 0));
                backgroundColors.push(hatchPattern);
                borderColors.push(borderColor);

                // usage slice
                labels.push(`${label} - Usage`);
                values.push(isHidden ? 0 : (item.usage_carbon || 0));
                backgroundColors.push(baseColor);
                borderColors.push(borderColor);
            });

            chartData = {
                labels,
                datasets: [{
                    label: 'Total Carbon',
                    data: values,
                    backgroundColor: backgroundColors,
                    borderWidth: 0,
                    hoverBorderWidth: 0,
                    spacing: 0,
                }]
            };

            chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 },
                            generateLabels: () => {
                                const roomItems = data.map((item, index) => {
                                    const label = item.room || item.type || 'Unknown';
                                    const color = baseColors[index % baseColors.length];
                                    const borderColor = solidBorderColors[index % solidBorderColors.length];
                                    const isHidden = this._hiddenRoomIndices.has(index);

                                    return {
                                        text: label,
                                        fillStyle: color,
                                        strokeStyle: borderColor,
                                        lineWidth: 2,
                                        hidden: isHidden,
                                        index
                                    };
                                });

                                roomItems.push({
                                    text: 'Embodied (hatched)',
                                    fillStyle: this._createHatchPattern(ctx, 'rgba(120, 120, 120, 0.6)'),
                                    strokeStyle: '#666',
                                    lineWidth: 2,
                                    hidden: false,
                                    index: data.length
                                });

                                roomItems.push({
                                    text: 'Usage (solid)',
                                    fillStyle: '#999',
                                    strokeStyle: '#666',
                                    lineWidth: 2,
                                    hidden: false,
                                    index: data.length + 1
                                });

                                return roomItems;
                            }
                        },
                        onClick: (event, legendItem, legend) => {
                            const roomIndex = legendItem.index;

                            // Ignore the explanatory style legend items
                            if (roomIndex >= data.length) {
                                return;
                            }

                            if (this._hiddenRoomIndices.has(roomIndex)) {
                                this._hiddenRoomIndices.delete(roomIndex);
                            } else {
                                this._hiddenRoomIndices.add(roomIndex);
                            }

                            this.renderRoomChart();
                        }
                    },
                    title: {
                        display: true,
                        text: 'kgCO₂eq',
                        font: { size: 12, weight: 'normal' },
                        padding: { bottom: 10 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const roomIndex = Math.floor(context.dataIndex / 2);
                                const item = data[roomIndex];

                                const name = item.room || item.type || 'Unknown';
                                const embodied = item.embodied_carbon || 0;
                                const usage = item.usage_carbon || 0;
                                const total = item.total_carbon || (embodied + usage);

                                return [
                                    `${name}`,
                                    `Embodied: ${embodied.toFixed(2)} kgCO₂eq`,
                                    `Usage: ${usage.toFixed(2)} kgCO₂eq`,
                                    `Total: ${total.toFixed(2)} kgCO₂eq`
                                ];
                            }
                        }
                    }
                }
            };
        } else {
            const labels = data.map(item => item.room || item.type || 'Unknown');
            let values;
            let datasetLabel;

            if (this._carbonView === 'embodied') {
                values = data.map(item => item.embodied_carbon || 0);
                datasetLabel = 'Embodied Carbon';
            } else if (this._carbonView === 'appliance') {
                values = data.map(item => item.appliance_usage_carbon ?? item.usage_carbon ?? 0);
                datasetLabel = 'Appliance Usage Carbon';
            } else {
                values = data.map(item => item.usage_carbon || 0);
                datasetLabel = 'Usage Carbon';
            }

            chartData = {
                labels,
                datasets: [{
                    label: datasetLabel,
                    data: values,
                    backgroundColor: baseColors.slice(0, data.length),
                    borderWidth: 0,
                    hoverBorderWidth: 0,
                    spacing: 0,
                }]
            };

            chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 13 }
                        }
                    },
                    title: {
                        display: true,
                        text: 'kgCO₂eq',
                        font: { size: 12, weight: 'normal' },
                        padding: { bottom: 10 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.label}: ${context.parsed.toFixed(2)} kgCO₂eq`
                        }
                    }
                }
            };
        }

        this._roomChart = new Chart(ctx, {
            type: 'doughnut',
            data: chartData,
            options: chartOptions
        });

        this._addRoomChartClickHandler(data, canvas);
    }

    _addRoomChartClickHandler(rooms, canvas) {
        canvas.onclick = (event) => {
            const points = this._roomChart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
            if (points.length > 0) {
                let index = points[0].index;
                if (this._carbonView === 'total') {
                    index = Math.floor(index / 2);
                }
                this._selectedRoom = rooms[index];
                this.showDeviceDetail();
                this.renderDeviceChart();
            }
        };
    }

    showDeviceDetail() {
        const roomChartView = this.querySelector('#room-chart-view');
        const deviceDetailView = this.querySelector('#device-detail-view');
        const roomTitle = this.querySelector('#selected-room-title');
        const groupBySelect = this.querySelector('#group-by-select');

        if (roomChartView && deviceDetailView) {
            roomChartView.style.display = 'none';
            deviceDetailView.style.display = 'block';
            roomTitle.textContent = `Devices in ${this._selectedRoom.room || this._selectedRoom.type}`;
            if (groupBySelect) {
                groupBySelect.disabled = true;
                groupBySelect.title = 'Go back to the chart to change this setting';
                groupBySelect.style.appearance = 'none';
                groupBySelect.style.webkitAppearance = 'none';
                groupBySelect.style.mozAppearance = 'none';
            }
        }
    }

    showRoomChart() {
        const roomChartView = this.querySelector('#room-chart-view');
        const deviceDetailView = this.querySelector('#device-detail-view');
        const groupBySelect = this.querySelector('#group-by-select');

        if (roomChartView && deviceDetailView) {
            roomChartView.style.display = 'block';
            deviceDetailView.style.display = 'none';
            this._selectedRoom = null;
            if (groupBySelect) {
                groupBySelect.disabled = false;
                groupBySelect.title = '';
                groupBySelect.style.appearance = '';
                groupBySelect.style.webkitAppearance = '';
                groupBySelect.style.mozAppearance = '';
            }
        }
    }

    renderDeviceChart() {
        if (!this._selectedRoom) {
            return;
        }

        const canvas = this.querySelector('#device-bar-chart');
        if (!canvas) {
            return;
        }

        const devices = this._selectedRoom.devices;
        const labels = devices.map(d => d.name);

        const canvasContainer = canvas.parentElement;
        const breakdownText = this.querySelector('#device-breakdown-text');

        let values;
        let datasetLabel;
        let breakdown = '';

        if (this._carbonView === 'appliance' && devices.length === 0) {
            if (this._deviceChart) {
                this._deviceChart.destroy();
                this._deviceChart = null;
            }
            if (breakdownText) {
                const groupName = this._selectedRoom.room || this._selectedRoom.type || 'this group';
                breakdownText.textContent = `No appliances found in ${groupName}.`;
            }
            if (canvasContainer) {
                canvasContainer.style.display = 'none';
            }
            return;
        }

        if (canvasContainer) {
            const minHeight = 300;
            const heightPerDevice = 40;
            const newHeight = Math.max(minHeight, devices.length * heightPerDevice);
            canvasContainer.style.display = '';
            canvasContainer.style.height = `${newHeight}px`;
        }

        // Calculate breakdown text
        const embodiedTotal = devices.reduce((sum, d) => sum + (d.embodied_carbon || 0), 0);
        const usageTotal = devices.reduce((sum, d) => sum + (d.usage_carbon || 0), 0);
        const applianceUsageTotal = devices.reduce((sum, d) => sum + (d.appliance_usage_carbon || 0), 0);
        const totalSum = devices.reduce((sum, d) => sum + (d.total_carbon || 0), 0);

        breakdown = `Embodied: ${embodiedTotal.toFixed(2)} kgCO₂eq | Total usage: ${usageTotal.toFixed(2)} kgCO₂eq`;
        if (this._showApplianceUsage || this._carbonView === 'appliance') {
            breakdown += ` | Appliance usage: ${applianceUsageTotal.toFixed(2)} kgCO₂eq`;
        }
        breakdown += ` | Total: ${totalSum.toFixed(2)} kgCO₂eq`;
        if (breakdownText) {
            breakdownText.textContent = breakdown;
        }

        if (this._deviceChart) {
            this._deviceChart.destroy();
        }

        // Build datasets based on view
        let datasets;
        let stacked = false;

        if (this._carbonView === 'total') {
            // Stacked bars showing embodied and usage
            const embodiedValues = devices.map(d => d.embodied_carbon);
            const usageValues = devices.map(d => d.usage_carbon);
            const predictedValues = devices.map(d => d.predicted_carbon);

            datasets = [
                {
                    label: 'Embodied Carbon',
                    data: embodiedValues,
                    backgroundColor: 'rgba(76, 175, 80, 0.7)',  // Green
                    borderColor: 'rgb(76, 175, 80)',
                    borderWidth: 1,
                },
                {
                    label: 'Usage Carbon',
                    data: usageValues,
                    backgroundColor: 'rgba(33, 150, 243, 0.7)',  // Blue
                    borderColor: 'rgb(33, 150, 243)',
                    borderWidth: 0,
                },
                {
                    label: 'Predicted Carbon (5 years)',
                    data: predictedValues,
                    backgroundColor: 'rgba(243, 33, 33, 0.7)',
                    borderColor: 'rgba(243, 33, 33, 1)',
                    borderWidth: 0,
                }
            ];
            stacked = true;
        } else if (this._carbonView === 'embodied') {
            // Single bars for embodied
            const embodiedValues = devices.map(d => d.embodied_carbon);
            datasets = [
                {
                    label: 'Embodied Carbon',
                    data: embodiedValues,
                    backgroundColor: 'rgba(76, 175, 80, 0.7)',  // Green
                    borderColor: 'rgb(76, 175, 80)',
                    borderWidth: 0,
                }
            ];
        } else if (this._carbonView === 'appliance') {
            const applianceUsageValues = devices.map(d => d.appliance_usage_carbon ?? d.usage_carbon ?? 0);
            datasets = [
                {
                    label: 'Appliance Usage Carbon',
                    data: applianceUsageValues,
                    backgroundColor: 'rgba(255, 152, 0, 0.7)',
                    borderColor: 'rgb(255, 152, 0)',
                    borderWidth: 0,
                }
            ];
        } else {
            // Single bars for usage
            const usageValues = devices.map(d => d.usage_carbon);
            datasets = [
                {
                    label: 'Usage Carbon',
                    data: usageValues,
                    backgroundColor: 'rgba(33, 150, 243, 0.7)',  // Blue
                    borderColor: 'rgb(33, 150, 243)',
                    borderWidth: 0,
                }
            ];
        }

        this._deviceChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',  // Horizontal bar chart
                scales: {
                    x: {
                        stacked: stacked,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'kgCO₂eq',
                            font: { weight: 'bold', size: 12 }
                        },
                        ticks: {
                            callback: (value) => `${value}`
                        }
                    },
                    y: {
                        stacked: stacked,
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.dataset.label}: ${context.parsed.x.toFixed(2)} kgCO₂eq`
                        }
                    }
                },
            }
        });
    }

    attachFormHandler() {
        const suggestions = [
            "Temperature/humidity sensor",
            "Motion sensor",
            "Luminosity sensor",
            "Air quality sensor",
            "Camera",
            "Speaker",
            "Light bulb",
            "Smart plug",
            "Smart lock",
            "Window/door sensor",
            "Thermostat",
            "Energy monitor",
            "Washing machine",
            "TV",
            "Refrigerator",
            "Dishwasher",
        ];

        const carbonSelector = this.querySelector('#device_carbon_footprint');
        if (carbonSelector) {
            try {
                carbonSelector.hass = this._hass;
                carbonSelector.selector = {
                    number: {
                        min: 0.00,
                        step: 0.01
                    },
                };

                carbonSelector.required = true;
                carbonSelector.value = this._currentCarbonValue;
                carbonSelector.addEventListener('value-changed', (ev) => { this._currentCarbonValue = ev.detail.value; })
            } catch (err) {
                console.debug('Failed to init ha-selector-number', err);
            }
        }

        const typeSelector = this.querySelector('#device_type_selector');
        if (typeSelector) {
            //console.log('Loaded device type selector')
            try {
                typeSelector.hass = this._hass;
                typeSelector.selector = {
                    select: {
                        options: suggestions,
                        custom_value: true,
                        sort: true,
                    },
                };

                typeSelector.value = this._currentType ?? '';
                typeSelector.label = 'Device Type';
                typeSelector.addEventListener('value-changed', async (ev) => {
                    this._currentType = ev.detail.value; console.log(`Type is now ${this._currentType}`); typeSelector.value = ev.detail.value;
                    const embodiedTypeResp = await this._hass.callWS({ type: 'carbon_footprint/get_type_embodied_footprint', device_type: this._currentType });
                    const embodiedVal = embodiedTypeResp.carbon_footprint;
                    this._currentCarbonValue = embodiedVal;
                    carbonSelector.value = this._currentCarbonValue;
                });
            } catch (err) {
                console.debug('Failed to init ha-selector-select', err);
            }

        }

        const selector = this.querySelector('#device_selector');
        if (selector) {
            try {
                selector.hass = this._hass;
                selector.selector = {
                    device: {},
                };
                selector.value = this._currentDevice ?? '';
                selector.required = true;
                selector.addEventListener('value-changed', async (ev) => {
                    this._currentDevice = ev.detail.value;
                    const autoComp = await this._hass.callWS({ type: 'carbon_footprint/get_device_autocomp', device_id: this._currentDevice });
                    this._currentType = autoComp.type;
                    typeSelector.value = this._currentType;
                    this._currentCarbonValue = autoComp.cf;
                    carbonSelector.value = this._currentCarbonValue;
                });
            } catch (err) {
                console.debug('Failed to init ha-selector', err);
            }
        }



        const form = this.querySelector('#add-device-form');
        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData(form);

                try {

                    if (this._currentDevice === null || this._currentDevice === '' || this._currentType === null || this._currentType === '') {
                        Utils.showToast(this, "Please fill out all the fields.");
                        return;
                    }

                    await this._hass.callWS({
                        type: 'carbon_footprint/set_device',
                        device_id: this._currentDevice,
                        device_type: this._currentType,
                        carbon_footprint: this._currentCarbonValue,
                        metadata: {}
                    });

                    this._currentDevice = '';
                    this._currentType = '';
                    this._currentCarbonValue = 0.0;
                    const newData = await this.getCarbonData();
                    Utils.showToast(this, 'Successfully added device!');
                    await this.render(newData);

                } catch (error) {
                    console.error('Failed to add device:', error);
                    alert(`Error adding device: ${error.message}`);
                }
            });
        }

        const detectBtn = this.querySelector('#detect-devices-btn');
        const loaderAnim = this.querySelector('#loader');
        if (detectBtn) {
            detectBtn.addEventListener('click', async () => {
                this.detectDevicesType(detectBtn, loaderAnim)
                detectBtn.disabled = true;
                loaderAnim.style.display = 'inline-block';
            });
        }

        const exportBtn = this.querySelector('#export-json-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', async () => {
                let jsonArray = await this._hass.callWS({ type: 'carbon_footprint/export_json' });

                const array = JSON.stringify(jsonArray.json_array);
                const uploaded = jsonArray.uploaded
                if (uploaded === 'yes') {
                    Utils.showToast(this, "Devices have been uploaded to the db interface!");
                }
                else {
                    navigator.clipboard.writeText(array);
                    Utils.showToast(this, "Devices have been copied to the clipboard! If you wanted to upload to the interface, please make sure db_ip and cfdb_token are correct and set.");
                }
            })
        }

        const computeBtn = this.querySelector('#compute-footprint-btn');
        if (computeBtn) {
            computeBtn.addEventListener('click', () => this.showHardwareDialogAndCompute());
        }

        const extendButtons = this.querySelectorAll('.extend-btn');
        extendButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const deviceInfo = e.currentTarget.closest('.device-info');
                const extendedDiv = deviceInfo.querySelector('.device-extended');

                if (extendedDiv) {
                    const isHidden = extendedDiv.style.display === 'none' || !extendedDiv.style.display;
                    extendedDiv.style.display = isHidden ? 'block' : 'none';

                    e.currentTarget.textContent = isHidden ? '▲' : '▼';
                }
            })
        })

        const deleteButtons = this.querySelectorAll('.delete-btn');
        deleteButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const entityId = e.currentTarget.dataset.entityId;

                if (!confirm(`Remove ${entityId} from tracking?`)) {
                    return;
                }

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/remove_device',
                        device_name: entityId
                    });

                    const newData = await this.getCarbonData();
                    Utils.showToast(this, "Successfully untracked device!");
                    await this.render(newData);

                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }

    attachDeleteHandlers() {
        const deleteButtons = this.querySelectorAll('.delete-btn');
        deleteButtons.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const entityId = e.currentTarget.dataset.entityId;

                if (!confirm(`Remove ${entityId} from tracking?`)) {
                    return;
                }

                try {
                    await this._hass.callWS({
                        type: 'carbon_footprint/remove_device',
                        device_name: entityId
                    });

                    await this.updateDeviceList();

                } catch (error) {
                    console.error('Failed to remove device:', error);
                    alert(`Error removing device: ${error.message}`);
                }
            });
        });
    }

    async showHardwareDialogAndCompute(deviceMeta = {}) {
        const initialHsl = {};
        const inferred = null;
        openFullForm(this,initialHsl, null);
    }

}

if (!customElements.get('carbon-footprint-panel')) {
    customElements.define('carbon-footprint-panel', CarbonFootprintPanel);
}
console.log('Panel loaded');
