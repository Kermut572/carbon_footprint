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
    return {
        message: `Your IoT load is relatively high at ${value.toFixed(1)}%. Consider a device audit and smarter controls to cut emissions.`,
        emoji: '🔴',
        severity: 'bad',
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

    const energies = histogramData
        .map((point) => Number(point.energy_footprint ?? point.energy ?? NaN))
        .filter((value) => Number.isFinite(value));

    if (energies.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Usage data is present but could not be interpreted.',
            severity: 'info',
            color: '#e8f5e9',
            emoji: 'ℹ️',
        };
    }

    const avg = energies.reduce((sum, value) => sum + value, 0) / energies.length;
    const spikeThreshold = avg * 1.5;
    const spikes = energies.filter((value) => value > spikeThreshold);
    const recentCount = Math.max(1, Math.min(7, energies.length));
    const recent = energies.slice(-recentCount);
    const recentAvg = recent.reduce((sum, value) => sum + value, 0) / recent.length;

    if (spikes.length === 0) {
        return {
            title: 'Usage Pattern Insight',
            message: 'Your usage is fairly smooth and stable over the selected period.',
            severity: 'success',
            color: '#e8f5e9',
            emoji: '✅',
        };
    }

    if (recentAvg > avg * 1.1) {
        return {
            title: 'Usage Pattern Insight',
            message: `Recently you’ve consumed more than usual over the last ${recentCount} entries.`,
            severity: 'warning',
            color: '#fff8e1',
            emoji: '⚠️',
        };
    }

    return {
        title: 'Usage Pattern Insight',
        message: `You’ve had ${spikes.length} high-consumption spikes in this view. Try smoothing usage across the day.`,
        severity: 'warning',
        color: '#fff8e1',
        emoji: '⚠️',
    };
}
