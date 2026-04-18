"""This file contains general utils functions."""

from datetime import date, datetime, timedelta
import logging
from logging import Logger

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .energy_store import EnergyStore

_LOGGER = logging.getLogger(__name__)


class ProviderError(Exception):
    """Error raised when OpenRouter returns a provider error."""


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

    Three default values are first tested. If they are not an EM sensor, the entity registry is queried.
    """

    probable_entities = [
        "sensor.electricity_maps_co2_intensity",
        "sensor.electricity_maps_carbon_intensity",
        "sensor.co2_intensity",
    ]

    for entity in probable_entities:
        state = hass.states.get(entity)
        if state and state.state not in ("unknown", "unavailable"):
            return entity

    _LOGGER = logging.getLogger(__name__)
    # search for any possible sensor with the right unit of measurement, in case the user renamed it
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        state = hass.states.get(entry.entity_id)
        if not state:
            continue

        if state.attributes.get("unit_of_measurement") == "gCO2eq/kWh":
            return entry.entity_id

    _LOGGER.warning("No Electricity Maps sensor found :-(")
    return "sensor.electricity_maps_co2_intensity"  # it's not this in this case but what else can a man return


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
    """Returns the energy consumption (in kWh) of the last year from either the energy meter either the fallback value."""

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return 0.0

    entry = entries[0]

    default_ret_value = entry.options.get("yearly_consumption") or 0.0

    energy_meter_entity = entry.options.get("energy_meter")
    if not energy_meter_entity or energy_meter_entity == "":
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


def utils_build_cfdb_device(device: dict) -> dict:
    """Builds the device dictionary following the format for the CFDB interface."""
    device_dict = {}

    metadata = device.get("metadata", {})
    model = metadata.get("model", "unknown")
    manufacturer = metadata.get("manufacturer", "unknown")

    carbon_footprint = device.get("carbon_footprint", 0)
    d_type = device.get("type", "unknown")
    d_id = (
        model.lower().strip() + "-" + manufacturer.lower().strip()
        if model and manufacturer
        else "demoObj-nullType"
    )

    device_dict["id"] = d_id
    device_dict["model"] = model
    device_dict["manufacturer"] = manufacturer
    device_dict["type"] = d_type
    device_dict["carbon_footprint"] = [
        {"low": carbon_footprint, "mid": carbon_footprint, "high": carbon_footprint}
    ]

    return device_dict


def utils_get_device_energy_consumption_map(
    hass: HomeAssistant, device_id: str, granularity: str
) -> dict:
    """Return a dictionary mapping a device's energy consumption by the given time granularity.

    The keys are formatted as "%d-%m-%Y-%H".
    """
    energy_entity = utils_find_energy_entity_for_device(hass, device_id)
    _LOGGER.debug("No energy entity found for device id %s, skipping", device_id)
    if not energy_entity:
        return None

    stats = statistics_during_period(
        hass,
        dt_util.now() - timedelta(days=1825),
        dt_util.now(),
        {energy_entity},
        granularity,
        None,
        {"sum", "mean"},
    )

    result = {}
    for stat in stats.get(energy_entity, []):
        start_ts = stat.get("start")
        if not start_ts:
            continue
        dt = dt_util.as_local(dt_util.utc_from_timestamp(start_ts))
        map_key = dt.strftime("%d-%m-%Y-%H")
        result[map_key] = stat.get("mean", 0)

    return result


def utils_compute_device_consumption_footprint(
    hass: HomeAssistant,
    device_id: str,
    granularity: str,
    start_time: str,
    end_time: str,
) -> dict:
    """Return a dictionary mapping a device's energy consumption carbon impact by the given time granularity."""
    energy_consumption_map = utils_get_device_energy_consumption_map(
        hass,
        device_id,
        "hour",  # use hour here because we aggregate afterwards
    )
    if not energy_consumption_map:
        return None

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.exception("No config entry found")
        return None

    start_time = dt_util.parse_datetime(start_time)
    end_time = dt_util.parse_datetime(end_time)

    energy_store = entries[0].runtime_data.energy_store.data

    last_value = None
    delta = None
    delta_energy_dict = {}
    for key, value in energy_consumption_map.items():
        if last_value:
            delta = value - last_value
            delta_energy_dict[key] = max(delta, 0)

        if delta and delta < 0:
            last_value = 0
            continue

        last_value = value

    results = []
    match granularity:
        case "hour":
            for key, value in delta_energy_dict.items():
                data_time = dt_util.as_local(datetime.strptime(key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                consumption_cf = (value * energy_store.get(key, 150.0)) / 1000
                _LOGGER.debug(
                    "At %s: energy=%.4f kWh, intensity=%.2f gCO2eq/kWh, footprint=%.4f kgCO2eq",
                    key,
                    value,
                    energy_store.get(key, 150.0),
                    value * energy_store.get(key, 150.0) / 1000,
                )

                results.append(
                    {
                        "timestamp": data_time.isoformat(),
                        "consumption_footprint": consumption_cf,
                    }
                )
        case "day":
            curr_date = None
            cumulated_fp = 0
            days = 0

            for key, value in delta_energy_dict.items():
                data_time = dt_util.as_local(datetime.strptime(key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                consumption_cf = value * energy_store.get(key, 150.0) / 1000

                if curr_date and curr_date.date() != data_time.date():
                    results.append(
                        {
                            "timestamp": curr_date.isoformat(),
                            "consumption_footprint": cumulated_fp / days,
                        }
                    )
                    days = 0
                    cumulated_fp = 0

                curr_date = data_time
                cumulated_fp += consumption_cf
                days += 1

            if curr_date and days > 0:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "consumption_footprint": cumulated_fp / days,
                    }
                )

        case "month":
            curr_date = None
            cumulated_fp = 0
            days = 0

            for key, value in delta_energy_dict.items():
                data_time = dt_util.as_local(datetime.strptime(key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                consumption_cf = value * energy_store.get(key, 150.0) / 1000

                if curr_date and curr_date.month != data_time.month:
                    results.append(
                        {
                            "timestamp": data_time.isoformat(),
                            "consumption_footprint": cumulated_fp / days,
                        }
                    )
                    days = 0
                    cumulated_fp = 0

                curr_date = data_time
                cumulated_fp += consumption_cf
                days += 1

            if curr_date and days > 0:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "consumption_footprint": cumulated_fp / days,
                    }
                )

    return results
