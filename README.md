# Carbon Footprint

A Home Assistant custom integration to estimate embodied and usage carbon for devices and rooms.

## Dependencies
- [PowerCalc](https://github.com/bramstroker/homeassistant-powercalc): Not essential but recommended, as it gives power and energy consumption profiles for device that do not come with energy meters

## Installation
1. Clone the repo into `config/custom_components/`:
   ```bash
   git clone https://github.com/Kermut572/carbon_footprint.git
   ```
   or
   ```bash
   gh repo clone Kermut572/carbon_footprint
   ```
2. Restart Home Assistant
3. Install the integration from the UI (Settings → Devices & Services → Add integration → "Carbon Footprint").

## Configuration
There are three optional settings needed to unlock all features:
- `db_ip`: CFDB interface URL (default: https://interface.kermut.org)
- `api_key`: OpenRouter API key for automatic device type detection (get one at https://openrouter.ai)
- `cfdb_token`: Token to upload data to CFDB (get one by registering on https://interface.kermut.org with your `GitHub` account)

## Usage
- Open the Carbon Footprint panel in the sidebar
- Click Settings → "Automatic setup" to detect and add devices
- Use "Add device" to compute or override a device footprint via the questionnaire
- Use "Export to JSON" to upload local devices to the shared database

## Troubleshooting
- `Provider Error` during Automatic Setup: likely an upstream OpenRouter issue, wait a bit and retry
