"""Sensors for the Carbon Footprint integration.

This module provides sensor entities that track:
- Current CO2 intensity of the grid
- Current carbon emissions (calculated from power consumption)
- Daily total carbon emissions

These sensors follow Home Assistant best practices for sensor implementation.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components import recorder
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.sensor import (
    RestoreEntity,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import DEVICE_ADDED_SIGNAL, DOMAIN
from .utils import (
    utils_build_hourly_stamps,
    utils_fetch_electricity_maps_sensor,
    utils_find_energy_entity_for_device,
)

_LOGGER = logging.getLogger(__name__)

_STATISTICS_RESYNC_INTERVAL = timedelta(minutes=2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Carbon Footprint."""
    # Get the data stores from the integration
    cf_store = entry.runtime_data.cf_store

    # Create sensor entities
    entities = []

    async def setup_devices_sensors(_hass: HomeAssistant) -> None:
        # setup entries for registered devices
        dev_entities = []
        devices = cf_store.get_devices_data()
        em_sensor = utils_fetch_electricity_maps_sensor(hass)
        for device_id, device_info in devices.items():
            device_meta = device_info.get("metadata", {})
            device_name = device_meta.get("display_name", "err")
            # _LOGGER.info("Creating sensor for %s", device_name)

            energy_entity, appliance_entity, _ = utils_find_energy_entity_for_device(
                hass, device_id
            )
            if not energy_entity:
                # _LOGGER.warning("No energy entity found for %s, skipping", device_name)
                continue

            dev_entities.append(
                CarbonUsageImpactSensor(
                    hass=hass,
                    device_id=device_id,
                    device_name=device_name,
                    energy_entity_id=energy_entity,
                    em_entity_id=em_sensor,
                )
            )

            if appliance_entity:
                dev_entities.append(
                    CarbonUsageImpactSensor(
                        hass=hass,
                        device_id=device_id,
                        device_name=device_name,
                        energy_entity_id=appliance_entity,
                        em_entity_id=em_sensor,
                        is_appliance=True,
                    )
                )
        async_add_entities(dev_entities)

    async def add_device_from_event(device_id: str):
        entity_reg = er.async_get(hass)
        uuid = f"{device_id}_carbon_usage"

        device_reg = dr.async_get(hass)
        device_entry = device_reg.devices.get(device_id)
        device_name = (device_entry.name_by_user or device_entry.name) or "err"

        existing_entity_id = entity_reg.async_get_entity_id("sensor", DOMAIN, uuid)
        if existing_entity_id is not None:
            _LOGGER.info(
                "Did not add a sensor for %s because one already exists (%s)",
                device_name,
                existing_entity_id,
            )
            existing_entry = entity_reg.async_get(existing_entity_id)
            if existing_entry:
                entity_reg.async_update_entity(existing_entity_id, device_id=device_id)
                _LOGGER.info(
                    "Re-linked %s to device %s", existing_entity_id, device_name
                )

                devices = cf_store.get_devices_data()
                curr_device = devices.get(device_id, None)
                if curr_device is not None:
                    curr_device["cu_entity"] = existing_entity_id
                    hass.async_create_task(cf_store.async_save_data())
            return

        energy_entity, appliance_entity, _ = utils_find_energy_entity_for_device(
            hass, device_id
        )

        if not energy_entity:
            _LOGGER.info(
                "Could not add sensor for %s because it has no energy sensor",
                device_name,
            )
            return

        em_sensor = utils_fetch_electricity_maps_sensor(hass)
        if not em_sensor:
            _LOGGER.warning(
                "Could not add sensor for %s because no Electricity Maps sensor was found, make sure it is installed"
            )
            return
        entities = [
            CarbonUsageImpactSensor(
                hass, device_id, device_name, energy_entity, em_sensor
            )
        ]

        if appliance_entity:
            entities.append(
                CarbonUsageImpactSensor(
                    hass, device_id, device_name, appliance_entity, em_sensor, True
                )
            )

        async_add_entities(entities)

    async_add_entities(entities)
    entry.async_on_unload(async_at_started(hass, setup_devices_sensors))

    entry.async_on_unload(
        async_dispatcher_connect(hass, DEVICE_ADDED_SIGNAL, add_device_from_event)
    )


class CarbonUsageImpactSensor(SensorEntity, RestoreEntity):
    """Reports the cumulated carbon footprint of device at usage in gCO2eq."""

    _attr_native_unit_of_measurement = "gCO2eq"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        device_name: str,
        energy_entity_id: str,
        em_entity_id: str,
        is_appliance: bool = False,
    ) -> None:
        """Init a carbon usage impact sensor."""
        self.hass = hass
        self._device_id = device_id
        self._device_name = device_name
        self._energy_entity_id = energy_entity_id
        self._em_entity_id = em_entity_id

        self._last_energy_reading = None
        self._total_carbon_impact = 0.0
        self._last_em_reading = None
        self._statistic_id = None

        self._attr_unique_id = (
            f"{device_id}_carbon_usage"
            if not is_appliance
            else f"{device_id}_appliance_carbon_usage"
        )
        self._attr_name = (
            "Carbon impact of usage"
            if not is_appliance
            else "Carbon impact of connected appliance"
        )
        self._attr_has_entity_name = True
        self.is_appliance = is_appliance

        device_entry = dr.async_get(hass).async_get(device_id)
        if device_entry:
            self._attr_device_info = DeviceInfo(
                identifiers=device_entry.identifiers,
                connections=device_entry.connections,
            )

    # @property
    # def available(self) -> bool:
    #    """Return True if entity is available."""
    #    state = self.hass.states.get(self._energy_entity_id)
    #    return state is not None and state.state not in ("unknown", "unavailable")

    @property
    def native_value(self) -> float:
        """Return rounded carbon impact."""
        return round(self._total_carbon_impact, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        return {
            "device_id": self._device_id,
            "device_name": self._device_name,
            "energy_entity_id": self._energy_entity_id,
            "em_entity_id": self._em_entity_id,
            "statistic_id": self._statistic_id,
            "last_energy_reading": self._last_energy_reading,
            "last_em_reading": self._last_em_reading,
        }

    async def async_refresh_total_from_statistics(self) -> None:
        """Refresh internal total from the latest recorder sum value."""
        if self._statistic_id is None:
            return

        last_stats = await recorder.get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self._statistic_id,
            False,
            {"sum"},
        )
        stats_rows = last_stats.get(self._statistic_id)
        if not stats_rows:
            return

        latest_sum = stats_rows[0].get("sum")
        if latest_sum is None:
            return

        _LOGGER.debug(
            "Latest recorded sum for %s is %s (previous in-memory total: %s), start: %s",
            self._device_name,
            latest_sum,
            self._total_carbon_impact,
            stats_rows[0].get("start"),
        )

        with contextlib.suppress(ValueError, TypeError):
            new_total = float(latest_sum)
            if new_total > self._total_carbon_impact:
                self._total_carbon_impact = new_total
                self.async_write_ha_state()
            elif new_total == 0 and self._total_carbon_impact > 0:
                _LOGGER.warning(
                    "Rejecting statistics update to 0 for %s (current: %f)",
                    self._device_name,
                    self._total_carbon_impact,
                )

    async def async_added_to_hass(self):
        """Register callback events."""
        await super().async_added_to_hass()
        self._statistic_id = self.entity_id

        async def _statistics_resync_listener(_now: datetime) -> None:
            """Keep the sensor state aligned with recorder stat edits."""
            await self.async_refresh_total_from_statistics()

        self.async_on_remove(
            async_track_time_interval(
                self.hass, _statistics_resync_listener, _STATISTICS_RESYNC_INTERVAL
            )
        )

        last_state = await self.async_get_last_state()
        if last_state is not None:
            with contextlib.suppress(ValueError, TypeError):
                self._total_carbon_impact = max(
                    self._total_carbon_impact, float(last_state.state)
                )

            restored_last = last_state.attributes.get("last_energy_reading")
            if isinstance(restored_last, (int, float)):
                self._last_energy_reading = float(restored_last)

        if self.is_appliance:
            _LOGGER.debug("Building appliance stats for %s", self._device_name)

        now = dt_util.now()
        end_ts = now.replace(
            minute=0, second=0, microsecond=0
        )  # prevent reset to 0 ?? god's plan
        stats = await utils_build_hourly_stamps(
            self.hass,
            self._device_id,
            (now - timedelta(days=180)).isoformat(),
            end_ts.isoformat(),
            self.is_appliance,
        )

        if self.is_appliance:
            _LOGGER.debug(
                "Found stats %s for appliance from device %s", stats, self._device_name
            )

        entries = self.hass.config_entries.async_entries(DOMAIN)
        cf_store = None
        if entries:
            cf_store = entries[0].runtime_data.cf_store
            devices = cf_store.get_devices_data()
            curr_device = devices.get(self._device_id, None)
            if curr_device:
                if not self.is_appliance:
                    curr_device["cu_entity"] = self._statistic_id
                else:
                    curr_device["cu_app_entity"] = self._statistic_id
                self.hass.async_create_task(cf_store.async_save_data())

        if stats:
            metadata = {
                "statistic_id": self._statistic_id,
                "source": "recorder",
                "name": f"{self._device_name} carbon impact of usage"
                if not self.is_appliance
                else f"{self._device_name} carbon impact of connected appliance",
                "unit_of_measurement": "gCO2eq",
                "unit_class": None,
                "has_sum": True,
                "mean_type": StatisticMeanType.NONE,
            }
            try:
                _LOGGER.debug(
                    "Importing %d stats for %s, last sum=%s",
                    len(stats),
                    self._device_name,
                    stats[-1].get("sum") if stats else None,
                )
                async_import_statistics(self.hass, metadata, stats)
                if cf_store and (
                    device_info := cf_store.get_devices_data().get(self._device_id)
                ):
                    if not self.is_appliance:
                        device_info["history_uploaded"] = True
                    else:
                        device_info["appliance_history_uploaded"] = True
                    self.hass.async_create_task(cf_store.async_save_data())

                with contextlib.suppress(ValueError, TypeError):
                    self._total_carbon_impact = max(
                        self._total_carbon_impact,
                        float(stats[-1].get("sum", 0.0)),
                    )

                state = self.hass.states.get(self._energy_entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    with contextlib.suppress(ValueError, TypeError):
                        self._last_energy_reading = float(state.state)

                self.async_write_ha_state()
            except Exception:
                _LOGGER.exception(
                    "Failed to import historical statistics for %s",
                    self.entity_id,
                )

        async def energy_state_listener(event: Event[EventStateChangedData]) -> None:
            """Handler for state changes of energy sensor."""
            new_state = event.data.get("new_state")
            if new_state is None:
                return

            new_energy_reading = None
            with contextlib.suppress(ValueError):
                new_energy_reading = float(new_state.state)
            if new_energy_reading is None:
                self.async_write_ha_state()
                return

            em_state = self.hass.states.get(self._em_entity_id)
            em_value = None
            with contextlib.suppress(ValueError):
                em_value = float(em_state.state)
            if em_value is None:
                em_value = 150.0

            _LOGGER.debug(
                "Last energy reading for %s was %f, VS current reading which is %f",
                self._device_name,
                self._last_energy_reading,
                new_energy_reading,
            )

            self._last_em_reading = em_value
            if self._last_energy_reading is None:
                self._last_energy_reading = new_energy_reading
                self.async_write_ha_state()
                return

            delta_nrj = new_energy_reading - self._last_energy_reading
            _LOGGER.debug("Computed a delta of %f for %s", delta_nrj, self._device_name)
            _LOGGER.debug(
                "Current total carbon value for %s is %f",
                self._device_name,
                self._total_carbon_impact,
            )
            if delta_nrj <= 0:
                self._last_energy_reading = new_energy_reading
                self.async_write_ha_state()
                return

            _LOGGER.debug(
                "Writing %f total carbon impact to %s",
                delta_nrj * em_value,
                self._device_name,
            )
            metadata = {
                "statistic_id": self._statistic_id,
                "source": "recorder",
                "name": f"{self._device_name} carbon impact of usage"
                if not self.is_appliance
                else f"{self._device_name} carbon impact of connected appliance",
                "unit_of_measurement": "gCO2eq",
                "unit_class": None,
                "has_sum": True,
                "mean_type": StatisticMeanType.NONE,
            }

            now = dt_util.now()
            str_dt = now.strftime("%d-%m-%Y-%H")
            dt_local = dt_util.as_local(datetime.strptime(str_dt, "%d-%m-%Y-%H"))

            start_utc = dt_util.as_utc(
                now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
            )

            self._total_carbon_impact += delta_nrj * em_value
            self._last_energy_reading = new_energy_reading

            # existing_stats = await recorder.get_instance(
            #    self.hass
            # ).async_add_executor_job(
            #    statistics_during_period,
            #    self.hass,
            #    start_utc,
            #    start_utc + timedelta(hours=1),
            #    {self._statistic_id},
            #    "hour",
            #    None,
            #    {"sum"},
            # )
            #
            # if not existing_stats.get(self._statistic_id):
            #    stats = [
            #        {
            #            "start": start_utc + timedelta(hours=1),
            #            "state": self._total_carbon_impact,
            #            "sum": self._total_carbon_impact,
            #        }
            #    ]
            #    try:
            #        async_import_statistics(self.hass, metadata, stats)
            #        _LOGGER.debug("Imported current stat for %s", self._device_name)
            #    except Exception:
            #        _LOGGER.debug(
            #            "Failed to import current statistics for %s, tag probably already exists",
            #            self._device_name,
            #        )

            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._energy_entity_id, energy_state_listener
            )
        )

        if self._last_energy_reading is None:
            state = self.hass.states.get(self._energy_entity_id)
            val = None
            with contextlib.suppress(ValueError):
                val = float(state.state)
            self._last_energy_reading = val

        await self.async_refresh_total_from_statistics()

        self.async_write_ha_state()
