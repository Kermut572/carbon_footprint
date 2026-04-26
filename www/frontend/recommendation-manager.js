// recommendation-manager.js
import { CarbonUtils } from './carbon-utils.js';

/**
 * Get the recommendation for the high-impact area based on room data.
 * @param {Array} roomData - Array of room objects with carbon footprint data.
 * @returns {Object} Recommendation object with title, message, and severity.
 */
export function getHighImpactAreaRecommendation(roomData) {
    if (!Array.isArray(roomData) || roomData.length === 0) {
        return {
            title: "No Data Available",
            message: "We couldn't find any data to determine the high-impact area.",
            severity: "info",
        };
    }

    // Find the room with the highest total carbon footprint
    const highImpactRoom = roomData.reduce((maxRoom, currentRoom) => {
        return currentRoom.total_carbon > (maxRoom.total_carbon || 0) ? currentRoom : maxRoom;
    }, {});

    return {
        title: "High-Impact Area Identified",
        message: `The room with the highest carbon footprint is ${highImpactRoom.room} with a total of ${highImpactRoom.total_carbon.toFixed(2)} kg CO₂.`,
        emoji: '⚠️',
        severity: "warning",
    };
}

export function getCarbonIntensityRecommendation(ci) {
    const label = CarbonUtils.getCarbonLabel(ci);
    const safeCi = Number(ci);

    if (!ci || isNaN(safeCi)) {
        return {
            label,
            message: 'Carbon intensity data unavailable.',
            color: '#eeeeee',
            emoji: '❓',
            severity: 'info',
        };
    }

    if (safeCi < 150) {
        return {
            label,
            message: `The carbon intensity is <b>low (${safeCi} gCO₂eq/kWh)</b>. This is a good time to run appliances like washing machines and dishwashers.`,
            color: '#e8f5e9',
            emoji: '✅',
            severity: 'good',
        };
    }

    if (safeCi < 300) {
        return {
            label,
            message: `The carbon intensity is <b>moderate (${safeCi} gCO₂eq/kWh)</b>. If possible, shift flexible loads to cleaner hours.`,
            color: '#fff8e1',
            emoji: '⚠️',
            severity: 'warning',
        };
    }

    return {
        label,
        message: `The carbon intensity is <b>high (${safeCi} gCO₂eq/kWh)</b>. Avoid heavy appliance use now and delay non-essential loads.`,
        color: '#ffebee',
        emoji: '🔴',
        severity: 'bad',
    };
}

export function getIoTShareRecommendation(yearlyCons) {
    const value = Number(yearlyCons) || 0;
    if (value === 0) {
        return {
            message: 'No IoT consumption share was detected. Add devices to get a more accurate recommendation.',
            emoji: 'ℹ️',
            severity: 'info',
        };
    }
    if (value <= 5) {
        return {
            message: `Your IoT load is low at ${value.toFixed(1)}% of yearly consumption. Keep optimizing with smart scheduling.`,
            emoji: '✅',
            severity: 'good',
        };
    }
    if (value <= 20) {
        return {
            message: `Your IoT load is moderate at ${value.toFixed(1)}%. Review the highest-use devices to reduce waste.`,
            emoji: '⚠️',
            severity: 'warning',
        };
    }
    if (value > 100) {
        return {
            message: `Incoherent value computed, have you set an energy meter or a fallback energy value in the settings?`,
            emoji: '🫥',
            severity: 'bad',
        };
    }
    return {
        message: `Your IoT load is relatively high at ${value.toFixed(1)}%. Consider a device audit and smarter controls to cut emissions.`,
        emoji: '🔴',
        severity: 'bad',
    };
}

export function getUsagePatternRecommendation(
    usageHistory,
    intensityHistory,
    currentIntensity
) {
    const title = 'Usage Pattern Insight';
    const resultBase = {
        id: 'usage_pattern',
        title,
    };
    const logPrefix = '[Carbon Footprint][Usage Pattern]';

    const hasCurrentIntensity =
        currentIntensity !== undefined &&
        currentIntensity !== null &&
        !Number.isNaN(Number(currentIntensity));
    const hasIntensityHistory = Array.isArray(intensityHistory) && intensityHistory.length > 0;
    const hasUsageHistory =
        usageHistory && typeof usageHistory === 'object' && Object.keys(usageHistory).length > 0;
    const usageDeviceCount = hasUsageHistory ? Object.keys(usageHistory).length : 0;


    if (!hasIntensityHistory) {
        console.log(logPrefix, 'missing intensity history', {
            hasCurrentIntensity,
            currentIntensity,
        });

        if (hasCurrentIntensity) {
            const safeIntensity = Number(currentIntensity);
            let message = `I do not have enough historical carbon-intensity data yet to compare your usage timing over time. Based on the current grid value, carbon intensity is <b>${safeIntensity.toFixed(0)} gCO₂eq/kWh</b>.`;
            let severity = 'neutral';
            let emoji = '⚪';
            let color = '#fff8e1';

            if (safeIntensity < 150) {
                message += ' That is relatively low, so now is a good moment to run flexible appliances such as a dishwasher, washing machine, dryer, or EV charger.';
                severity = 'good';
                emoji = '✅';
                color = '#e8f5e9';
            } else if (safeIntensity < 300) {
                message += ' That is a moderate level. If the task is flexible, waiting for a cleaner period could slightly reduce emissions.';
                severity = 'neutral';
                emoji = '⚠️';
            } else {
                message += ' That is high. Try to postpone non-essential, energy-heavy tasks until the grid is cleaner.';
                severity = 'warning';
                emoji = '⚠️';
                color = '#ffebee';
            }

            return {
                ...resultBase,
                message,
                severity,
                color,
                emoji,
            };
        }

        return {
            ...resultBase,
            message:
                'I cannot analyze your usage pattern yet because historical carbon-intensity data is unavailable. Once intensity history is collected, this recommendation can check whether your energy use happens during cleaner or dirtier grid periods.',
            severity: 'neutral',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    if (!hasUsageHistory) {
        console.log(logPrefix, 'missing usage history', {
            usageHistory,
        });

        return {
            ...resultBase,
            message:
                'I have carbon-intensity history, but no usable energy-usage history yet. Once device usage is collected, this recommendation will compare when you consume energy against how clean the grid was at those same times.',
            severity: 'neutral',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const usageByTimestamp = new Map();
    let rawUsagePointCount = 0;
    let validUsagePointCount = 0;
    let skippedUsagePointCount = 0;

    for (const deviceId in usageHistory) {
        const devicePoints = usageHistory[deviceId];
        if (!Array.isArray(devicePoints)) {
            console.log(logPrefix, 'skipping device with non-array usage points', {
                deviceId,
                devicePoints,
            });
            continue;
        }

        let previousCumulativeUsage = null;
        for (const point of devicePoints) {
            rawUsagePointCount++;
            const timestamp = point.timestamp;
            let usageValue = Number(point.usage_kwh);

            if (!Number.isFinite(usageValue)) {
                const cumulativeUsage = Number(point.energy ?? point.usage ?? NaN);
                if (Number.isFinite(cumulativeUsage)) {
                    usageValue =
                        previousCumulativeUsage === null
                            ? 0
                            : Math.max(cumulativeUsage - previousCumulativeUsage, 0);
                    previousCumulativeUsage = cumulativeUsage;
                } else {
                    usageValue = Number(
                        point.consumption_footprint ?? point.energy_footprint ?? NaN
                    );
                }
            }

            if (!timestamp || !Number.isFinite(usageValue) || usageValue <= 0) {
                skippedUsagePointCount++;
                continue;
            }

            validUsagePointCount++;
            usageByTimestamp.set(
                timestamp,
                (usageByTimestamp.get(timestamp) || 0) + usageValue
            );
        }
    }


    if (usageByTimestamp.size === 0) {
        console.log(logPrefix, 'no valid usage values extracted');

        return {
            ...resultBase,
            message:
                'Usage history exists, but I could not extract any positive consumption values from it. Check that usage points include a timestamp and a numeric value such as <b>usage_kwh</b>, <b>energy</b>, <b>usage</b>, <b>consumption_footprint</b>, or <b>energy_footprint</b>.',
            severity: 'neutral',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const intensityByTimestamp = new Map();
    let validIntensityPointCount = 0;
    let skippedIntensityPointCount = 0;

    for (const point of intensityHistory) {
        const timestamp = point.timestamp;
        const intensityValue = Number(
            point.intensity ?? point.value ?? point.co2_intensity ?? NaN
        );

        if (!timestamp || !Number.isFinite(intensityValue) || intensityValue <= 0) {
            skippedIntensityPointCount++;
            continue;
        }

        validIntensityPointCount++;
        intensityByTimestamp.set(timestamp, intensityValue);
    }

    console.log(logPrefix, 'intensity extraction summary', {
        rawIntensityPointCount: intensityHistory.length,
        validIntensityPointCount,
        skippedIntensityPointCount,
        intensityTimestamps: intensityByTimestamp.size,
        intensitySample: Array.from(intensityByTimestamp.entries()).slice(0, 5),
    });

    if (intensityByTimestamp.size === 0) {
        console.log(logPrefix, 'no valid intensity values extracted');

        return {
            ...resultBase,
            message:
                'Carbon-intensity history exists, but I could not extract any valid intensity values from it. The recommendation needs timestamped values such as <b>intensity</b>, <b>value</b>, or <b>co2_intensity</b>.',
            severity: 'neutral',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    let matchedUsage = 0;
    let weightedSum = 0;
    const matchedIntensities = [];
    let unmatchedUsageTimestampCount = 0;

    for (const [timestamp, usageValue] of usageByTimestamp) {
        const intensityValue = intensityByTimestamp.get(timestamp);
        if (!Number.isFinite(intensityValue)) {
            unmatchedUsageTimestampCount++;
            continue;
        }

        matchedUsage += usageValue;
        weightedSum += usageValue * intensityValue;
        matchedIntensities.push(intensityValue);
    }

    if (matchedUsage === 0 || matchedIntensities.length < 2) {
        console.log(logPrefix, 'not enough matched usage and intensity timestamps', {
            matchedUsage,
            matchedIntensityCount: matchedIntensities.length,
        });

        return {
            ...resultBase,
            message:
                'I found both usage data and carbon-intensity data, but there were not enough matching timestamps to compare them reliably. This usually means the two histories use different time intervals or timestamp formats.',
            severity: 'neutral',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const weightedIntensity = weightedSum / matchedUsage;
    const averageIntensity =
        matchedIntensities.reduce((sum, value) => sum + value, 0) /
        matchedIntensities.length;
    const intensityDifference = weightedIntensity - averageIntensity;
    const intensityDifferencePercent =
        averageIntensity > 0 ? (intensityDifference / averageIntensity) * 100 : 0;
    const comparisonDirection =
        intensityDifferencePercent > 0 ? 'higher' : 'lower';
    const comparisonText =
        Math.abs(intensityDifferencePercent) < 1
            ? 'almost exactly in line with'
            : `${Math.abs(intensityDifferencePercent).toFixed(0)}% ${comparisonDirection} than`;
    const metricsMessage =
        `Across <b>${matchedIntensities.length}</b> matched time periods, your usage-weighted grid intensity was <b>${weightedIntensity.toFixed(0)} gCO₂eq/kWh</b>. ` +
        `The average grid intensity during those same periods was <b>${averageIntensity.toFixed(0)} gCO₂eq/kWh</b>, so your usage was ${comparisonText} the period average.`;



    if (weightedIntensity > averageIntensity * 1.15) {
        console.log(logPrefix, 'returning warning recommendation');

        return {
            ...resultBase,
            message:
                `${metricsMessage} This suggests a noticeable share of your energy use happened when the grid was dirtier than usual. Try shifting flexible loads, such as laundry, dishwashing, charging, or heating cycles, to lower-carbon hours when possible.`,
            severity: 'warning',
            color: '#ffebee',
            emoji: '⚠️',
        };
    }

    if (weightedIntensity < averageIntensity * 0.85) {
        console.log(logPrefix, 'returning good recommendation');

        return {
            ...resultBase,
            message:
                `${metricsMessage} This is a good pattern: your energy use is already aligned with cleaner grid periods. Keep scheduling flexible appliances during lower-carbon hours to maintain the benefit.`,
            severity: 'good',
            color: '#e8f5e9',
            emoji: '✅',
        };
    }

    console.log(logPrefix, 'returning neutral recommendation version 1.0');

    return {
        ...resultBase,
        message:
            `${metricsMessage} Your timing is close to average, so there is no strong problem signal. You may still reduce emissions by moving flexible, energy-heavy tasks away from higher-carbon periods when convenient.`,
        severity: 'neutral',
        color: '#fff8e1',
        emoji: '⚠️',
    };
}

/**
 * Analyze the correlation between energy usage and carbon intensity over time.
 * Detects whether the user tends to consume energy during high carbon intensity periods.
 * @param {Object} energyData - Consumption data from WS call, format: {device_id: [{timestamp, consumption_footprint}, ...]}
 * @param {Array} intensityData - Historical carbon intensity data, format: [{timestamp, intensity}, ...]
 * @returns {Object} Recommendation object with title, message, and severity.
 */
export function getUsageVsIntensityRecommendation(energyData, intensityData) {
    // Check for sufficient data
    if (!energyData || typeof energyData !== 'object' || Object.keys(energyData).length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'No energy consumption data available to analyze usage patterns against carbon intensity.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    if (!Array.isArray(intensityData) || intensityData.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Carbon intensity history is not available. Unable to analyze usage timing.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    // Aggregate total consumption per timestamp across all devices
    const consumptionByTime = new Map();
    let totalConsumption = 0;

    for (const deviceId in energyData) {
        const devicePoints = energyData[deviceId];
        if (!Array.isArray(devicePoints)) continue;

        for (const point of devicePoints) {
            const ts = point.timestamp;
            const consumption = Number(point.consumption_footprint) || 0;
            if (consumption > 0) {
                consumptionByTime.set(ts, (consumptionByTime.get(ts) || 0) + consumption);
                totalConsumption += consumption;
            }
        }
    }

    if (totalConsumption === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'No energy consumption recorded in the selected period.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    // Create intensity lookup map for faster access
    const intensityByTime = new Map();
    for (const point of intensityData) {
        intensityByTime.set(point.timestamp, Number(point.intensity) || 0);
    }

    // Compute weighted average carbon intensity of user's consumption
    let weightedSum = 0;
    let validPoints = 0;

    for (const [ts, consumption] of consumptionByTime) {
        const intensity = intensityByTime.get(ts);
        if (intensity !== undefined && intensity > 0) {
            weightedSum += consumption * intensity;
            validPoints++;
        }
    }

    if (validPoints === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Unable to match consumption data with carbon intensity data for the selected period.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const userWeightedIntensity = weightedSum / totalConsumption;

    // Compute average grid carbon intensity over the same period
    const intensities = Array.from(intensityByTime.values()).filter(i => i > 0);
    const avgGridIntensity = intensities.reduce((sum, i) => sum + i, 0) / intensities.length;

    // Compare user's weighted intensity to grid average
    const ratio = userWeightedIntensity / avgGridIntensity;
    const threshold = 0.1; // 10% difference considered similar

    if (ratio > 1 + threshold) {
        // User consumes at higher intensity times
        return {
            title: 'Usage Pattern Insight',
            message: 'A significant portion of your usage occurs during high carbon intensity periods. Shifting usage to low-carbon hours could reduce emissions.',
            severity: 'bad',
            color: '#ffebee',
            emoji: '🔴',
        };
    } else if (ratio < 1 - threshold) {
        // User consumes at lower intensity times
        return {
            title: 'Usage Pattern Insight',
            message: 'Your usage is well aligned with low-carbon periods. Good job optimizing your consumption timing!',
            severity: 'good',
            color: '#e8f5e9',
            emoji: '✅',
        };
    } else {
        // Similar to average
        return {
            title: 'Usage Pattern Insight',
            message: 'Your usage is moderately aligned with grid carbon intensity. Some improvements in timing are possible.',
            severity: 'warning',
            color: '#fff8e1',
            emoji: '⚠️',
        };
    }
}
