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
        };
    }

    if (safeCi < 150) {
        return {
            label,
            message: `The carbon intensity is <b>low (${safeCi} gCO₂eq/kWh)</b>. This is a good time to run appliances like washing machines and dishwashers.`,
            color: '#e8f5e9',
            emoji: '✅',
        };
    }

    if (safeCi < 300) {
        return {
            label,
            message: `The carbon intensity is <b>moderate (${safeCi} gCO₂eq/kWh)</b>. If possible, shift flexible loads to cleaner hours.`,
            color: '#fff8e1',
            emoji: '⚠️',
        };
    }

    return {
        label,
        message: `The carbon intensity is <b>high (${safeCi} gCO₂eq/kWh)</b>. Avoid heavy appliance use now and delay non-essential loads.`,
        color: '#ffebee',
        emoji: '🔴',
    };
}

export function getIoTShareRecommendation(yearlyCons) {
    const value = Number(yearlyCons) || 0;
    if (value === 0) {
        return {
            message: 'No IoT consumption share was detected. Add devices to get a more accurate recommendation.',
        };
    }
    if (value <= 5) {
        return {
            message: `Your IoT load is low at ${value.toFixed(1)}% of yearly consumption. Keep optimizing with smart scheduling.`,
        };
    }
    if (value <= 20) {
        return {
            message: `Your IoT load is moderate at ${value.toFixed(1)}%. Review the highest-use devices to reduce waste.`,
        };
    }
    return {
        message: `Your IoT load is relatively high at ${value.toFixed(1)}%. Consider a device audit and smarter controls to cut emissions.`,
    };
}

export function getUsagePatternRecommendation(histogramData, intensityData) {
    if (!Array.isArray(histogramData) || histogramData.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'No historical usage data is available to analyze your usage patterns.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    if (!Array.isArray(intensityData) || intensityData.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Unable to evaluate whether usage is concentrated in high-impact periods because historical intensity data is missing. TODO: add backend support for historical intensity time series in the same data payload.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const parseTimestamp = (point) => {
        if (!point || !point.timestamp) return null;
        const date = new Date(point.timestamp);
        return Number.isNaN(date.getTime()) ? null : date.toISOString();
    };

    const intensityMap = new Map();
    intensityData.forEach((point) => {
        const key = parseTimestamp(point);
        if (key) {
            const value = Number(point.co2_intensity ?? point.intensity ?? point.value ?? NaN);
            if (!Number.isNaN(value)) {
                intensityMap.set(key, value);
            }
        }
    });

    const matched = histogramData
        .map((point) => {
            const key = parseTimestamp(point);
            const intensity = key ? intensityMap.get(key) : undefined;
            return {
                energy: Number(point.energy_footprint ?? point.energy ?? NaN),
                intensity,
            };
        })
        .filter((entry) => !Number.isNaN(entry.energy) && entry.intensity !== undefined);

    if (matched.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Received historical data, but could not match energy and intensity timestamps. TODO: align backend time series formats for analysis.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const allIntensityAverage = matched.reduce((sum, point) => sum + point.intensity, 0) / matched.length;
    const usageAverage = matched.reduce((sum, point) => sum + point.energy, 0) / matched.length;
    const highUsagePoints = matched.filter((point) => point.energy > usageAverage);

    if (highUsagePoints.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Usage appears evenly distributed across available periods; no strong high-impact concentration was detected.',
            severity: 'success',
            color: '#e8f5e9',
            emoji: '✅',
        };
    }

    const highUsageIntensityAverage = highUsagePoints.reduce((sum, point) => sum + point.intensity, 0) / highUsagePoints.length;

    if (highUsageIntensityAverage > allIntensityAverage * 1.1) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Your higher usage periods tend to happen when carbon intensity is above average. Consider shifting flexible loads to cleaner hours.',
            severity: 'warning',
            color: '#fff8e1',
            emoji: '⚠️',
        };
    }

    return {
        title: 'Usage Pattern Insight',
        message: 'Your higher usage periods are not strongly aligned with higher carbon intensity. Keep monitoring and shift when possible.',
        severity: 'success',
        color: '#e8f5e9',
        emoji: '✅',
    };
}
