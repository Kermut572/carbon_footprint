"""Test data generator for Carbon Footprint integration.

This module generates fake data for testing sensors without Electricity Maps.
Used when TEST_MODE is enabled in const.py.

REMOVE THIS FILE WHEN INTEGRATING WITH REAL DATA
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_test_data(hass: HomeAssistant, energy_store: Any, cf_store: Any) -> None:
    """Generate fake test data for sensors.
    
    This function:
    1. Creates historical energy footprint data (24h of electricity grid CO2 intensity)
    2. Sets up a fake electricity_maps_co2_intensity sensor that updates hourly
    3. Creates fake devices organized in different rooms with carbon footprint values
    4. Optionally creates power sensors for testing CarbonEmissionNow
    """
    _LOGGER.warning(
        "⚠️  TEST MODE ENABLED - Using fake data. "
        "Change TEST_MODE in const.py to False when using real data"
    )

    # Generate 24 hours of fake CO2 intensity data
    # Format: "dd-mm-yyyy-hh" -> intensity value (gCO2/kWh)
    now = datetime.now()
    
    # Simulate realistic CO2 intensity values (varies throughout the day)
    # Typically 150-300 gCO2/kWh depending on renewables in grid
    base_values = [
        280,  # 00:00 - high (less renewables at night)
        270, 260, 250,  # 01:00-03:00 - declining as coal/gas plants power down
        240, 235, 230,  # 04:00-06:00 - minimum at dawn
        245, 260, 280,  # 07:00-09:00 - morning peak
        300, 310, 320,  # 10:00-12:00 - midday (even with solar, demand is high)
        330, 325, 315,  # 13:00-15:00 - early afternoon
        300, 285, 270,  # 16:00-18:00 - evening decline
        260, 250, 240,  # 19:00-21:00 - decline continues
        250, 260,  # 22:00-23:00 - approaching night peak
    ]

    for i, intensity in enumerate(base_values):
        # Generate dates for past 24 hours
        time = now - timedelta(hours=24 - i)
        date_key = time.strftime("%d-%m-%Y-%H")
        await energy_store.async_set_energy_footprint(date_key, intensity)

    _LOGGER.info("✓ Generated 24h of fake CO2 intensity data")

    # Set initial electricity maps sensor state
    # This is what the sensors read from
    hass.states.async_set(
        "sensor.electricity_maps_co2_intensity",
        base_values[-1],  # Use the last value (current hour)
        {
            "unit_of_measurement": "gCO2/kWh",
            "friendly_name": "Electricity Maps CO2 Intensity",
            "icon": "mdi:leaf",
        },
    )
    _LOGGER.info(f"✓ Set fake electricity_maps_co2_intensity to {base_values[-1]} gCO2/kWh")

    # Optional: Create fake power sensors for testing CarbonEmissionNow
    # These simulate devices consuming power
    await _create_fake_power_sensors(hass)

    # Create fake devices organized by room for testing room grouping
    await _create_fake_devices(hass, cf_store)


async def _create_fake_power_sensors(hass: HomeAssistant) -> None:
    """Create fake power sensors for testing CarbonEmissionNow sensor.
    
    Creates 3 simulated devices with varying power consumption:
    - Fake Laptop: 50W
    - Fake Water Heater: 3000W (high consumption)
    - Fake Refrigerator: 200W (always on)
    """
    fake_sensors = [
        {
            "entity_id": "sensor.fake_laptop_power",
            "state": "50",
            "attributes": {
                "unit_of_measurement": "W",
                "friendly_name": "Fake Laptop Power",
                "icon": "mdi:laptop",
            },
        },
        {
            "entity_id": "sensor.fake_water_heater_power",
            "state": "3000",
            "attributes": {
                "unit_of_measurement": "W",
                "friendly_name": "Fake Water Heater Power",
                "icon": "mdi:water-heater",
            },
        },
        {
            "entity_id": "sensor.fake_refrigerator_power",
            "state": "200",
            "attributes": {
                "unit_of_measurement": "W",
                "friendly_name": "Fake Refrigerator Power",
                "icon": "mdi:fridge",
            },
        },
    ]

    for sensor in fake_sensors:
        hass.states.async_set(sensor["entity_id"], sensor["state"], sensor["attributes"])

    total_power = sum(float(s["state"]) for s in fake_sensors)
    _LOGGER.info(
        f"✓ Created 3 fake power sensors with total consumption: {total_power}W "
        f"({total_power/1000:.1f}kW)"
    )


async def _create_fake_devices(hass: HomeAssistant, cf_store: Any) -> None:
    """Create fake devices organized by room for testing room grouping.
    
    Creates 7 devices across 3 rooms:
    - Living Room: TV, Heater, Smart Speaker (3 devices)
    - Kitchen: Refrigerator, Dishwasher, Coffee Maker (3 devices)
    - Bedroom: AC Unit (1 device)
    
    Note: For testing purposes, devices are stored with room names in metadata
    since we're using fake data. In production, devices would be linked via
    the Home Assistant device registry.
    """
    
    # Define fake devices with room assignments and carbon footprint (embodied)
    # Usage carbon simulates annual CO2 from energy consumption
    fake_devices = [
        # Living Room (3 devices) - embodied ~45 kgCO2eq, usage ~3.8 kgCO2eq/year
        {"name": "Living Room TV", "room": "Living Room", "type": "Entertainment", "embodied": 15.5, "usage": 0.5},
        {"name": "Living Room Heater", "room": "Living Room", "type": "Climate", "embodied": 22.3, "usage": 3.2},
        {"name": "Living Room Smart Speaker", "room": "Living Room", "type": "Speaker", "embodied": 7.2, "usage": 0.1},
        
        # Kitchen (3 devices) - embodied ~58 kgCO2eq, usage ~3.5 kgCO2eq/year
        {"name": "Kitchen Refrigerator", "room": "Kitchen", "type": "Appliance", "embodied": 35.0, "usage": 2.5},
        {"name": "Kitchen Dishwasher", "room": "Kitchen", "type": "Appliance", "embodied": 18.5, "usage": 0.8},
        {"name": "Kitchen Coffee Maker", "room": "Kitchen", "type": "Appliance", "embodied": 4.5, "usage": 0.2},
        
        # Bedroom (1 device) - embodied ~12 kgCO2eq, usage ~1.8 kgCO2eq/year
        {"name": "Bedroom AC Unit", "room": "Bedroom", "type": "Climate", "embodied": 12.0, "usage": 1.8},
    ]
    
    # Add devices to cf_store
    for device_info in fake_devices:
        device_name = device_info["name"]
        await cf_store.async_set_device_info(
            entity_id=device_name,
            type=device_info["type"],
            carbon_footprint=device_info["embodied"],
            metadata={
                "manufacturer": "Fake Manufacturer",
                "model": "FakeModel-2026",
                "model_id": f"fake_{device_name.lower().replace(' ', '_')}",
                "fake_room": device_info["room"],  # Store room name for reference
                "usage_carbon_kg": device_info["usage"],  # Simulated annual usage carbon
            },
        )
    
    embodied_total = sum(d["embodied"] for d in fake_devices)
    usage_total = sum(d["usage"] for d in fake_devices)
    total_carbon = embodied_total + usage_total
    _LOGGER.info(
        f"✓ Created 7 fake devices across 3 rooms"
        f"\n  Embodied: {embodied_total:.1f} kgCO2eq | Usage: {usage_total:.1f} kgCO2eq | Total: {total_carbon:.1f} kgCO2eq"
    )
    _LOGGER.info(
        f"  Living Room: 3 devices (45.0 kgCO2eq) | "
        f"Kitchen: 3 devices (58.0 kgCO2eq) | "
        f"Bedroom: 1 device (12.0 kgCO2eq)"
    )


async def async_simulate_hourly_update(hass: HomeAssistant, energy_store: Any) -> None:
    """Simulate an hourly CO2 intensity update.
    
    Call this to test what happens when new data arrives.
    This is useful for testing the CarbonTotalToday sensor updates.
    """
    now = datetime.now()
    date_key = now.strftime("%d-%m-%Y-%H")
    
    # Use a random value between 200-350 gCO2/kWh
    import random
    new_intensity = random.randint(200, 350)
    
    await energy_store.async_set_energy_footprint(date_key, new_intensity)
    
    # Update the sensor state so listeners pick it up
    hass.states.async_set(
        "sensor.electricity_maps_co2_intensity",
        new_intensity,
    )
    
    # Fire the event that sensors listen to
    hass.bus.async_fire("carbon_footprint_energy_updated")
    
    _LOGGER.info(f"✓ Simulated hourly update: {new_intensity} gCO2/kWh")
