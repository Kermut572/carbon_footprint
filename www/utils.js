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
}