/**
 * Handles hardware questionnaire dialog and computation.
 */

export class HardwareQuestionnaire {
    constructor() {
        this._hass = null;
    }

    setHass(hass) {
        this._hass = hass;
    }

    show(initialHsl = {}) {
        const dialog = document.createElement('dialog');
        dialog.classList.add('ha-dialog');

        const questions = this._getQuestions();
        let questionsHtml = '';

        for (const [blockName, data] of Object.entries(questions)) {
            questionsHtml += this._createRadioGroup(blockName, data.question, data.options, initialHsl);
        }

        dialog.innerHTML = `
            <form class="dialog-content">
                <h2>Quick Device Questions</h2>
                <p>Select the option that best describes the hardware block for your device.</p>
                <div id="questions-list">
                    ${questionsHtml}
                </div>

                <p id="error-message" style="color: red; margin-top: 10px;"></p>
                <div style="margin-top: 12px; display: flex; justify-content: flex-end; gap: 8px;">
                    <button id="cancel-button" type="button" value="cancel">Cancel</button>
                    <button id="compute-button" type="button" value="confirm">Compute Footprint</button>
                </div>
            </form>
        `;

        const computeBtn = dialog.querySelector('#compute-button');
        const cancelBtn = dialog.querySelector('#cancel-button');
        const errorMessage = dialog.querySelector('#error-message');

        computeBtn.addEventListener('click', async () => {
            await this._handleCompute(dialog, questions, errorMessage);
        });

        cancelBtn.addEventListener('click', () => {
            dialog.close();
            dialog.remove();
        });

        document.body.appendChild(dialog);
        dialog.showModal();
    }

    async _handleCompute(dialog, questions, errorMessage) {
        errorMessage.textContent = '';
        const hslValues = {};
        let allAnswered = true;

        for (const blockName of Object.keys(questions)) {
            const selectedRadio = dialog.querySelector(`input[name="${blockName}"]:checked`);
            if (selectedRadio) {
                hslValues[blockName] = selectedRadio.value;
            } else {
                allAnswered = false;
                break;
            }
        }

        if (!allAnswered) {
            errorMessage.textContent = 'Please answer all the questions before computing the footprint.';
            return;
        }

        try {
            const result = await this._hass.callWS({
                type: 'carbon_footprint/compute_footprint',
                hsl_values: hslValues,
            });

            const formInput = document.querySelector('#carbon_footprint');
            if (formInput) {
                formInput.value = (result.values?.[1] ?? 0).toFixed(2);
            }

            dialog.close();
            dialog.remove();
        } catch (err) {
            console.error('Compute error', err);
            errorMessage.textContent = `Could not compute footprint: ${err.message}`;
        }
    }

    _createRadioGroup(blockName, question, options, initialHsl) {
        let optionsHtml = '';
        Object.entries(options).forEach(([level, label]) => {
            const checked = initialHsl[blockName] == level ? 'checked' : '';
            optionsHtml += `
                <div class="radio-option">
                    <input type="radio" id="${blockName}-${level}" name="${blockName}" value="${level}" ${checked}>
                    <label for="${blockName}-${level}">${label}</label>
                </div>
            `;
        });

        return `
            <div class="question-group">
                <p><b>${question}</b></p>
                <div class="radio-container">
                    ${optionsHtml}
                </div>
            </div>
        `;
    }

    _getQuestions() {
        return {
            ui: {
                question: '1. User Interface (UI): Does it have a screen or complex controls?',
                options: {
                    '0': 'No visible screen or controls.',
                    '1': 'Basic buttons/LEDs only.',
                    '2': 'Small screen / limited touch interface.',
                    '3': 'Medium to large screen (e.g., smart panel, TV).',
                },
            },
            power_supply: {
                question: '2. Power Supply: Is it battery powered / has a complex PSU?',
                options: {
                    '0': 'No battery, mains powered.',
                    '1': 'Alkaline batteries (non-rechargeable).',
                    '2': 'Lithium batteries (rechargeable).',
                    '3': 'Large, complex power supply.',
                },
            },
            sensing: {
                question: '3. Sensing: Does it have a camera or advanced sensors?',
                options: {
                    '0': 'No active sensing.',
                    '1': 'Basic sensing (e.g., temp, humidity).',
                    '2': 'Advanced sensing (e.g., complex motion, sound).',
                    '3': 'High-end sensing (e.g., camera, depth sensor, LIDAR).',
                },
            },
            connectivity: {
                question: '4. Connectivity: How does the device communicate?',
                options: {
                    '0': 'No communications.',
                    '1': 'Simple low-power radio (e.g., Zigbee).',
                    '2': 'Mid-range wireless (e.g., basic Wi-Fi, Ethernet).',
                    '3': 'High-bandwidth / complex (e.g., high-speed Wi-Fi, cellular modem).',
                },
            },
            processing: {
                question: '5. Processing: How "smart" is the device?',
                options: {
                    '0': 'Basic, a switch.',
                    '1': 'Simple data collection.',
                    '2': 'Complex: data aggregation.',
                    '3': 'High-performance: streaming video encoding.',
                },
            },
            memory: {
                question: '6. Memory: Does the device store a lot of data?',
                options: {
                    '0': 'Minimal, no storage of data aside from firmware.',
                    '1': 'Modest: small data logging or storage.',
                    '2': 'Significant: enough to run a full OS, store video clips.',
                    '3': 'Large: has its own memory spot (SSD, HDD).',
                },
            },
            actuators: {
                question: '7. Actuators: Does the device move physically or change its state?',
                options: {
                    '0': 'No movement.',
                    '1': 'Simple mechanical movement (relay).',
                    '2': 'Motorized/complex movement (e.g., small motor).',
                    '3': 'High-power motors (e.g., robotic vacuum, valve control).',
                },
            },
            casing: {
                question: '8. Casing: What is the approximate size and material?',
                options: {
                    '0': 'Very small (no casing or in a wall box).',
                    '1': 'Small plastic casing.',
                    '2': 'Medium plastic / aluminium casing.',
                    '3': 'Large, rugged or complex casing.',
                },
            },
            transport: {
                question: '9. Transport: Where do you think the device was shipped from?',
                options: {
                    '0': 'No transport (locally made).',
                    '1': 'Regional transport (within continent).',
                    '2': 'Transport from another continent (Asia to Europe for example).',
                    '3': 'Long distance / heavy transport.',
                },
            },
            security: {
                question: '10. Security: Does it have a security feature beyond standard communication encryption?',
                options: {
                    '0': 'None or basic encryption.',
                    '1': 'Yes, includes embedded security/passwords.',
                },
            },
            others: {
                question: '11. Others: Does the device include many small components not covered above (cables, resistors)?',
                options: {
                    '0': 'Simple component list.',
                    '1': 'Standard set of small components.',
                    '2': 'Complex components (e.g., many discrete parts).',
                    '3': 'Highly complex (e.g., complex internal wiring).',
                },
            },
        };
    }
}