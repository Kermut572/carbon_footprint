"""This file contains general utils functions."""

from datetime import date, datetime, timedelta
from logging import Logger

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.util import dt as dt_util

from .const import DOMAIN
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
) -> tuple[float, str]:
    """Return the total energy consumed by a given device."""
    total_energy = 0.0
    is_sensor = False
    sensor_name = None
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
            sensor_name = entity.entity_id
            is_sensor = True
        except Exception:
            continue

    if not is_sensor:
        return (None, None)

    return (round(total_energy, 4), sensor_name)


def utils_get_device_install_date(hass: HomeAssistant, sensor: str) -> date:
    """Return the date on which the device was installed, by using the first date recorded by the sensors."""
    if not sensor or sensor == "":
        return None

    data_points = statistics_during_period(
        hass,
        dt_util.now() - timedelta(weeks=520),
        None,
        {sensor},
        "day",
        None,
        {"mean"},
    )

    if not data_points or sensor not in data_points:
        return None

    series = data_points[sensor]
    if not series:
        return None

    fp = series[0]
    start_ts = fp.get("start")

    return dt_util.as_local(dt_util.utc_from_timestamp(start_ts))


def utils_fetch_electricity_maps_sensor(hass: HomeAssistant) -> str:
    """Get the sensor name of the Electricity Maps Integration.

    This value is either sensor.electricity_maps_co2_intensity or sensor.electricity_maps_carbon_intensity.
    """

    co2_intensity_state = hass.states.get("sensor.electricity_maps_co2_intensity")
    if not co2_intensity_state or co2_intensity_state in ("unknown", "unavailable"):
        return "sensor.electricity_maps_carbon_intensity"

    return "sensor.electricity_maps_co2_intensity"


async def async_populate_energy_store(
    hass: HomeAssistant, energy_store: EnergyStore, _LOGGER: Logger
) -> None:
    """Populate the energy store with historical data if the energy store is empty."""
    if energy_store.data and len(energy_store.data.keys()) != 0:
        _LOGGER.info("EnergyStore already has data, skipping")
        return

    em_sensor = utils_fetch_electricity_maps_sensor(hass)
    data_points = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.now() - timedelta(weeks=260),
        None,
        {em_sensor},
        "hour",
        None,
        {"mean", "state"},
    )
    if not data_points or em_sensor not in data_points:
        _LOGGER.warning("No historical CO2 intensity statistics found")
        return

    for data_point in data_points[em_sensor]:
        timestamp = dt_util.as_local(dt_util.utc_from_timestamp(data_point["start"]))
        energy_footprint = data_point.get("mean") or data_point.get("state")

        if energy_footprint is None:
            continue

        date_key = timestamp.strftime("%d-%m-%Y-%H")
        await energy_store.async_set_energy_footprint(date_key, float(energy_footprint))

    _LOGGER.info("Populated energy store with historical data!")


def utils_find_energy_entity_for_device(
    hass: HomeAssistant, device_id: str
) -> str | None:
    """Return the entity_id of the energy sensor for a device_id, or None."""
    if not device_id or device_id == "":
        return None

    registry = er.async_get(hass)

    for entry in registry.entities.values():
        if entry.device_id != device_id:
            continue
        state = hass.states.get(entry.entity_id)
        if not state:
            continue
        if (
            state.attributes.get("device_class") == SensorDeviceClass.ENERGY
            and state.attributes.get("state_class") == SensorStateClass.TOTAL_INCREASING
        ):
            return entry.entity_id

    return None


def utils_get_yearly_consumption(hass: HomeAssistant) -> float:
    """Returns the energy consumption (in kWh) of the last year."""

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return 0.0

    entry = entries[0]

    default_ret_value = entry.options.get("yearly_consumption") or 0.0

    energy_meter = entry.options.get("energy_meter")
    energy_meter_entity = utils_find_energy_entity_for_device(hass, energy_meter)
    if not energy_meter_entity:
        return default_ret_value

    state = hass.states.get(energy_meter_entity)
    if not state:
        return default_ret_value

    if not (
        state.attributes.get("device_class") == SensorDeviceClass.ENERGY
        and state.attributes.get("state_class") == SensorStateClass.TOTAL_INCREASING
    ):
        return default_ret_value

    data = statistics_during_period(
        hass,
        dt_util.now() - timedelta(days=365),
        None,
        {energy_meter_entity},
        "day",
        None,
        {"sum"},
    )

    yearly_energy = 0.0
    for day in data.get(energy_meter_entity, []):
        daily_nrg = day.get("sum", 0.0)
        yearly_energy += daily_nrg

    return yearly_energy
