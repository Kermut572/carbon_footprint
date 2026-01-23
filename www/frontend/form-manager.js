//dialog manager
import { HARDWARE_QUESTIONS } from './questions.js';

export function openFullForm(instance, initialHsl = {}, inferred = null) {
    const dialog = document.createElement('dialog');
    dialog.classList.add('ha-dialog');

    const questions = HARDWARE_QUESTIONS;

    const createRadioGroup = (blockName, question, options) => {
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
    };

    let questionsHtml = '';
    for (const [blockName, data] of Object.entries(questions)) {
        questionsHtml += createRadioGroup(blockName, data.question, data.options);
    }

    dialog.innerHTML = `
        <form class="dialog-content">
            <h2>Quick Device Questions</h2>
            <p>Select the option that best describes the hardware block for your device.</p>
            <div id="questions-list">
                ${questionsHtml}
            </div>

            <p id="error-message" style="color: red; margin-top: 10px;"></p> <div style="margin-top:12px; display: flex; justify-content: flex-end; gap: 8px;">
                <button id="cancel-button" type="button" value="cancel">Cancel</button>
                <button id="compute-button" type="button" value="confirm">Compute Footprint</button>
            </div>
        </form>
    `;

    const computeBtn = dialog.querySelector('#compute-button');
    const cancelBtn = dialog.querySelector('#cancel-button');
    const errorMessage = dialog.querySelector('#error-message');

    computeBtn.addEventListener('click', async () => {
        errorMessage.textContent = '';
        const hsl_values = Object.assign({}, initialHsl);
        let allAnswered = true;

        for (const blockName of Object.keys(questions)) {
            const selectedRadio = dialog.querySelector(`input[name="${blockName}"]:checked`);
            if (selectedRadio) {
                hsl_values[blockName] = selectedRadio.value;
            } else {
                allAnswered = false;
                break;
            }
        }

        if (!allAnswered) {
            errorMessage.textContent = "Please answer all the questions before computing the footprint.";
            return;
        }

        const ALL_BLOCKS = ['ui', 'power_supply', 'sensing', 'connectivity', 'processing', 'memory', 'actuators', 'casing', 'transport', 'security', 'others'];
        ALL_BLOCKS.forEach(b => {
            if (hsl_values[b] === undefined) {
                hsl_values[b] = initialHsl[b] ?? '0'; // Default HSL 0 as string
            }
        });

        try {
            //console.log('Computing footprint with HSL values:', hsl_values);
            const result = await instance._hass.callWS({ type: 'carbon_footprint/compute_footprint', hsl_values });

            const formInput = instance.querySelector('#carbon_footprint');
            if (formInput) formInput.value = (result.values?.[1] ?? 0).toFixed(2);

            dialog.close();
            dialog.remove();

        } catch (err) {
            console.error('compute error', err);
            errorMessage.textContent = `Could not compute footprint: ${err.message}`;
        }
    });

    cancelBtn.addEventListener('click', () => {
        dialog.close();
        dialog.remove();
    });

    document.body.appendChild(dialog);
    dialog.showModal();
    }