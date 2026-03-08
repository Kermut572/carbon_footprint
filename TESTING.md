"""
TESTING GUIDE FOR CARBON FOOTPRINT SENSORS
=============================================

This guide explains how to test the newly added sensors with fake data.

## QUICK START

The integration is configured to use FAKE DATA by default for testing purposes.
To switch between test and real data, simply change the TEST_MODE flag in const.py:

  - In `const.py`, line ~11:
    TEST_MODE = True   # Use fake data (for testing)
    TEST_MODE = False  # Use real Electricity Maps data (production)

## WHAT THE FAKE DATA PROVIDES

1. **sensor.carbon_intensity_now**
   - 24 hours of historical CO2 intensity data (150-330 gCO2/kWh)
   - Realistic daily pattern (higher at night when less renewable energy)
   - Updates alongside real hourly data

2. **sensor.carbon_emission_now**
   - 3 fake power sensors simulating devices:
     * Fake Laptop: 50W
     * Fake Water Heater: 3000W
     * Fake Refrigerator: 200W
   - Total: 3.25kW consumption
   - Formula: (3250W / 1000) × [current intensity] = gCO2/h

3. **sensor.carbon_total_today**
   - Sums all hourly CO2 intensity values from today
   - Example: If intensity values are [280, 270, 260...], total = sum / 1000

## EXPECTED VALUES

With fake data, you should see approximately:

- **sensor.carbon_intensity_now**: 200-330 gCO2/kWh (varies by time of day)
- **sensor.carbon_emission_now**: ~0.5-1.0 gCO2/h (calculated from 3.25kW × intensity)
- **sensor.carbon_total_today**: 3-6 kgCO2 (sum of 24 hourly values ÷ 1000)

## REMOVING FAKE DATA

Once you integrate with real Electricity Maps:

1. In `const.py`, set: TEST_MODE = False
2. Delete the `test_data.py` file completely
3. Remove the test_data import from `__init__.py` (lines around the TEST_MODE check)
4. That's it! The integration will use real data.

## MANUAL TESTING

To manually test sensor updates without waiting for the hourly update cycle:

```python
# In Home Assistant developer console or a test script:
from homeassistant.components.carbon_footprint.test_data import async_simulate_hourly_update

await async_simulate_hourly_update(hass, energy_store)
```

This will:
- Generate a new random CO2 intensity value
- Update the electricity_maps_co2_intensity sensor
- Fire the carbon_footprint_energy_updated event
- Trigger sensor recalculations

## DEBUGGING

Check Home Assistant logs for these messages:
- "⚠️  TEST MODE ENABLED" → confirms test data is active
- "✓ Generated 24h of fake CO2 intensity data" → historical data loaded
- "✓ Created 3 fake power sensors" → mock devices ready
- "✓ Set fake electricity_maps_co2_intensity" → current intensity set

To see detailed debug logs, add to configuration.yaml:
```yaml
logger:
  logs:
    custom_components.carbon_footprint: debug
```

## TROUBLESHOOTING

If sensors show "unavailable":

1. Check that TEST_MODE = True in const.py
2. Restart Home Assistant
3. Check logs for any import errors
4. Verify sensor entities exist: Go to Developer Tools → States
   - Look for: sensor.carbon_intensity_now, sensor.carbon_emission_now, sensor.carbon_total_today

If values don't change:
- Wait 1 hour for the hourly update cycle
- Or manually simulate an update using async_simulate_hourly_update()
- Check that energy_store.json file is being updated in config/.storage/carbon_footprint_energy.data

## IMPORTANT NOTES

- Fake data is ONLY for testing sensors
- Do NOT use fake data in production
- Switch to real data (TEST_MODE = False) when integrating with Electricity Maps
- The test_data.py file should be deleted when using real data
"""
