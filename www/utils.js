export class Utils {
    static showToast(instance, message, duration = 3000) {
        instance.dispatchEvent(
            new CustomEvent("hass-notification", {
                detail: {
                    message,
                    duration,
                },
                bubbles: true,
                composed: true,
            })
        );
    }

    static getDateGroupKey(date, granularity) {
        switch (granularity) {
            case this._chartGranularity.HOUR:
                return new Date(date.getFullYear(), date.getMonth(), date.getDate(), date.getHours()).toISOString();
            case this._chartGranularity.DAY:
                return new Date(date.getFullYear(), date.getMonth(), date.getDate()).toISOString();
            case this._chartGranularity.MONTH:
                return new Date(date.getFullYear(), date.getMonth(), 1).toISOString();
            default:
                return date.toISOString();
        }
    }
}