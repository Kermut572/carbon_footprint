"""This file contains general utils functions."""

from datetime import timedelta
from logging import Logger

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.util import dt as dt_util

from .energy_store import EnergyStore


def utils_get_device_classes(
    hass: HomeAssistant, device_entities: list[RegistryEntry]
) -> list[str]:
    """Returns all of the entity classes associated to a device."""
    device_classes = []
    for entity in device_entities:
        state = hass.states.get(entity.entity_id)
        if not state:
            continue

        entity_device_class = state.attributes.get("device_class")
        if not entity_device_class:
            continue

        device_classes.append(entity_device_class)

    return device_classes


def utils_get_device_total_energy_consumption(
    hass: HomeAssistant, device_entities: list[RegistryEntry]
) -> float:
    """Return the total energy consumed by a given device."""
    total_energy = 0.0
    is_sensor = False
    for entity in device_entities:
        state = hass.states.get(entity.entity_id)
        if not state:
            continue

        if not (
            state.attributes.get("device_class") == SensorDeviceClass.ENERGY
            and state.attributes.get("state_class") == SensorStateClass.TOTAL_INCREASING
        ):
            continue

        try:
            total_energy += float(state.state)
            is_sensor = True
        except ValueError | TypeError:
            continue

    return round(total_energy, 4) if is_sensor else None


async def async_populate_energy_store(
    hass: HomeAssistant, energy_store: EnergyStore, _LOGGER: Logger
) -> None:
    """Populate the energy store with historical data if the energy store is empty."""
    if energy_store.data and len(energy_store.data.keys()) != 0:
        _LOGGER.info("EnergyStore already has data, skipping")
        return

    data_points = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.now() - timedelta(weeks=260),
        None,
        {"sensor.electricity_maps_co2_intensity"},
        "hour",
        None,
        {"mean", "state"},
    )
    if not data_points or "sensor.electricity_maps_co2_intensity" not in data_points:
        _LOGGER.warning("No historical CO2 intensity statistics found")
        return

    for data_point in data_points["sensor.electricity_maps_co2_intensity"]:
        timestamp = dt_util.as_local(dt_util.utc_from_timestamp(data_point["start"]))
        energy_footprint = data_point.get("mean") or data_point.get("state")

        if energy_footprint is None:
            continue

        date_key = timestamp.strftime("%d-%m-%Y-%H")
        await energy_store.async_set_energy_footprint(date_key, float(energy_footprint))

    _LOGGER.info("Populated energy store with historical data!")
