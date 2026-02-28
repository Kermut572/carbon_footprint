"""Sensors for the Carbon Footprint integration.

This module provides sensor entities that track:
- Current CO2 intensity of the grid
- Current carbon emissions (calculated from power consumption)
- Daily total carbon emissions

These sensors follow Home Assistant best practices for sensor implementation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .energy_store import EnergyStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Carbon Footprint."""
    # Get the data stores from the integration
    cf_store = entry.runtime_data.cf_store
    energy_store = entry.runtime_data.energy_store

    # Create sensor entities
    entities = [
        CarbonIntensityNowSensor(hass),
        CarbonEmissionNowSensor(hass, cf_store),
        CarbonTotalTodaySensor(hass, energy_store),
    ]

    async_add_entities(entities)


class CarbonIntensityNowSensor(SensorEntity):
    """Sensor for current CO2 intensity of the grid.

    DESIGN CHOICE: This sensor reads directly from the Electricity Maps
    integration (sensor.electricity_maps_co2_intensity) since that's our
    authoritative source for grid CO2 intensity. We cache the value locally
    but don't duplicate the polling.

    Unit: gCO2/kWh (grams of CO2 equivalent per kilowatt-hour)
    State class: measurement (point-in-time value, not cumulative)
    """

    _attr_unique_id = "carbon_footprint_intensity_now"
    _attr_name = "Carbon Intensity Now"
    _attr_icon = "mdi:leaf"
    _attr_native_unit_of_measurement = "gCO2/kWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False  # We'll update via state change listener

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "carbon_footprint")},
            "name": "Carbon Footprint",
            "manufacturer": "Carbon Footprint Integration",
        }

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()

        # Listen for changes from Electricity Maps integration
        self.async_on_remove(
            self.hass.bus.async_listen_once(
                "homeassistant_ready",
                self._fetch_initial_intensity,
            )
        )

        # Also update whenever the Electricity Maps sensor changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                "sensor.electricity_maps_co2_intensity",
                self._intensity_updated,
            )
        )

        # Fetch initial value
        await self._fetch_initial_intensity(None)

    async def _fetch_initial_intensity(self, event: Any) -> None:
        """Fetch initial intensity value."""
        state = self.hass.states.get("sensor.electricity_maps_co2_intensity")
        if state and state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(state.state)
                self.async_write_ha_state()
            except ValueError, TypeError:
                _LOGGER.warning("Could not parse CO2 intensity value: %s", state.state)

    async def _intensity_updated(self, event: Any) -> None:
        """Handle CO2 intensity update from Electricity Maps."""
        new_state = event.data.get("new_state")
        if new_state and new_state.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(new_state.state)
                await self.async_write_ha_state()
            except ValueError, TypeError:
                _LOGGER.warning(
                    "Could not parse CO2 intensity value: %s", new_state.state
                )

    @property
    def native_value(self) -> StateType:
        """Return the native value of the sensor."""
        return self._attr_native_value if hasattr(self, "_attr_native_value") else None


class CarbonEmissionNowSensor(SensorEntity):
    """Sensor for current carbon emissions rate.

    DESIGN CHOICE: This sensor calculates present emissions by multiplying
    current grid intensity with the sum of power consumption from all
    tracked energy sensors (if available). Falls back to unavailable if
    no energy sensors exist.

    The calculation is: Sum(device_power) * grid_intensity / 1000
    Unit: gCO2/h (grams of CO2 equivalent per hour)
    State class: measurement (measurement of current rate, not cumulative)

    NOTE: This sensor requires energy sensors to be available in the system.
    If no energy consumption data is available, the sensor will show unavailable.
    """

    _attr_unique_id = "carbon_footprint_emission_now"
    _attr_name = "Carbon Emission Now"
    _attr_icon = "mdi:leaf"
    _attr_native_unit_of_measurement = "gCO2/h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, cf_store: Any) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.cf_store = cf_store
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "carbon_footprint")},
            "name": "Carbon Footprint",
            "manufacturer": "Carbon Footprint Integration",
        }
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()

        # Update when Electricity Maps intensity changes
        # (we'll recalculate based on new intensity)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                "sensor.electricity_maps_co2_intensity",
                self._on_intensity_change,
            )
        )

        # Listen for any sensor state changes (energy sensors)
        self.async_on_remove(
            self.hass.bus.async_listen(
                "state_changed",
                self._on_state_change,
            )
        )

        # Initial update
        await self._update_emission()

    async def _update_emission(self) -> None:
        """Calculate and update current emission."""
        # Get current CO2 intensity
        intensity_state = self.hass.states.get("sensor.electricity_maps_co2_intensity")
        if not intensity_state or intensity_state.state in ("unknown", "unavailable"):
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        try:
            intensity = float(intensity_state.state)  # gCO2/kWh
        except ValueError, TypeError:
            self._attr_native_value = None
            self.async_write_ha_state()
            return

        # Get total power consumption from all tracked devices
        # We sum the power attribute from power sensors
        total_power_kw = 0.0
        devices = self.cf_store.get_devices_data()

        for device_name in devices.keys():
            # Look for power sensors related to this device
            # Common entity suffixes for power: _power, power consumption
            for entity_id in self.hass.states.async_entity_ids("sensor"):
                state = self.hass.states.get(entity_id)
                if not state:
                    continue

                # Check if this sensor belongs to the device and is a power sensor
                if (
                    device_name.lower() in entity_id.lower()
                    and state.attributes.get("unit_of_measurement") == "W"
                ):
                    try:
                        # Convert watts to kilowatts
                        power_w = float(state.state)
                        total_power_kw += power_w / 1000.0
                    except ValueError, TypeError:
                        continue

        # Calculate emission: power (kW) * intensity (gCO2/kWh) = gCO2/h
        if total_power_kw > 0:
            self._attr_native_value = round(
                total_power_kw * intensity,
                2,
            )
        else:
            # No power data available
            self._attr_native_value = None

        self.async_write_ha_state()

    async def _on_intensity_change(self, event: Any) -> None:
        """Handle intensity change."""
        await self._update_emission()

    async def _on_state_change(self, event: Any) -> None:
        """Handle any state change (update if it's a power sensor)."""
        entity_id = event.data.get("entity_id", "")
        if "power" in entity_id.lower() and entity_id.startswith("sensor."):
            await self._update_emission()

    @property
    def native_value(self) -> StateType:
        """Return the native value of the sensor."""
        return self._attr_native_value


class CarbonTotalTodaySensor(SensorEntity):
    """Sensor for total carbon emissions today.

    DESIGN CHOICE: This sensor sums all historical energy footprint data
    for the current day from the energy store. It queries the store
    every hour (synced with the integration's energy update cycle).

    The value represents total CO2 equivalent emitted by all tracked
    devices combined during today.

    Unit: kgCO2 (kilograms of CO2 equivalent)
    State class: total_increasing (cumulative counter that only increases)
    """

    _attr_unique_id = "carbon_footprint_total_today"
    _attr_name = "Carbon Total Today"
    _attr_icon = "mdi:leaf"
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, energy_store: EnergyStore) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.energy_store = energy_store
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "carbon_footprint")},
            "name": "Carbon Footprint",
            "manufacturer": "Carbon Footprint Integration",
        }
        self._attr_native_value = 0.0
        self._last_date: date | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()

        # Listen for the energy update event
        # We hook into the integration's hourly update
        self.async_on_remove(
            self.hass.bus.async_listen(
                "carbon_footprint_energy_updated",
                self._on_energy_updated,
            )
        )

        # Also update manually every hour to ensure consistency
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._update_total_today,
                interval=timedelta(hours=1),
            )
        )

        # Initial update
        await self._update_total_today(None)

    async def _update_total_today(self, now: Any = None) -> None:
        """Calculate total carbon for today."""
        today = date.today()

        # If we've already calculated for today and the date hasn't changed,
        # don't recalculate (it will only increase with new hourly data)
        if self._last_date == today and self._attr_native_value is not None:
            return  # No need to recalculate

        # Get all energy footprint data for today
        total_today = 0.0
        energy_data = self.energy_store.get_energy_footprint_data()

        for date_key, footprint_value in energy_data.items():
            # Parse date_key format: "dd-mm-yyyy-hh"
            try:
                entry_date = datetime.strptime(date_key, "%d-%m-%Y-%H").date()
                if entry_date == today:
                    # Convert gCO2/kWh to kgCO2
                    # Note: The energy_store stores the intensity value,
                    # so we're summing the hourly intensity values
                    total_today += float(footprint_value) / 1000.0
            except ValueError, IndexError:
                _LOGGER.warning("Could not parse date key: %s", date_key)
                continue

        self._attr_native_value = round(total_today, 4)
        self._last_date = today
        self.async_write_ha_state()

    def _on_energy_updated(self, event: Any) -> None:
        """Handle energy update event from integration."""
        # Reset the date check so we recalculate
        if self._last_date == date.today():
            self._last_date = None  # Force recalculation

        self.hass.async_create_task(self._update_total_today())

    @property
    def native_value(self) -> StateType:
        """Return the native value of the sensor."""
        return self._attr_native_value
