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
}