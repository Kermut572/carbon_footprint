"""This file contains general utils functions."""

from datetime import date, datetime, timedelta
import logging
from logging import Logger
import re

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .energy_store import EnergyStore

_LOGGER = logging.getLogger(__name__)

# https://regex101.com/codegen?language=python
REGEX_MATCHER = [
    (
        re.compile(
            r"\b(temp(erature)?|humid(ity)?|water|h2o|thermometer|wet|climate|weather)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Temperature/humidity sensor",
    ),
    (
        re.compile(
            r"\b(motion|movement|wildlife|occupancy|radar|presence)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Motion sensor",
    ),
    (
        re.compile(
            r"\b(luminosity|sun)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Luminosity sensor",
    ),
    (
        re.compile(
            r"\b(air|smoke|carbon dioxide|carbon monoxide|oxygen)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Air quality sensor",
    ),
    (
        re.compile(
            r"\b(camera|video|doorbell|webcam|cctv)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "camera",
    ),
    (
        re.compile(
            r"\b(speaker|alexa|(home\s)?cinema|music|audio)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "speaker",
    ),
    (
        re.compile(
            r"\b(light((\s)?bulb)?|lamp|bulb|led|rgb)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "light bulb",
    ),
    (
        re.compile(
            r"\b((smart\s)?plug|outlet|socket)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Smart plug",
    ),
    (
        re.compile(
            r"\b(lock|(dead)?bolt)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Smart lock",
    ),
    (
        re.compile(
            r"\b(window(\ssensor)?|door(\ssensor)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Window/door sensor",
    ),
    (
        re.compile(
            r"\b(thermostat|temp(erature)?\scontrol)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "thermostat",
    ),
    (
        re.compile(
            r"\b(energy(\smonitor|\scontrol)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "energy monitor",
    ),
    (
        re.compile(
            r"\b(wash(ing)?\smachine|cloth(es)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "washing machine",
    ),
    (
        re.compile(
            r"\b(tele(vision)?|tv)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "TV",
    ),
    (
        re.compile(
            r"\b(refrigerator)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "refrigerator",
    ),
    (
        re.compile(
            r"\b(dish(washer)?|dish(es)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "dishwasher",
    ),
]


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


def utils_get_device_install_date(
    hass: HomeAssistant, sensor: str, device_id: str
) -> tuple[date, bool]:
    """Return the date on which the device was installed, by using the first date recorded by the sensors.

    Also returns whether the cf_store was updated or not.
    """
    if not sensor or sensor == "":
        return None, False

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None, False

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    lookup_device = devices.get(device_id, None)
    if lookup_device is None:
        return None, False

    lookup_device_metadata = lookup_device.get("metadata", {})
    install_date = lookup_device_metadata.get("install_date", None)
    if install_date is not None:
        ts = dt_util.parse_datetime(install_date)
        return dt_util.as_local(ts), False

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
        return None, False

    series = data_points[sensor]
    if not series:
        return None, False

    fp = series[0]
    start_ts = fp.get("start")
    start_utc = dt_util.utc_from_timestamp(start_ts)
    lookup_device_metadata["install_date"] = start_utc.isoformat()

    return dt_util.as_local(start_utc), True


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
) -> tuple[str | None, bool]:
    """Return the entity_id of the energy sensor for a device_id, or None. Also returns whether the store was updated or not.

    Prioritizes the PowerCalc entity in order to have the energy consumption of the IoT device itself
    and not of the devices connected to it (in case of Smart Plugs).
    """
    if not device_id or device_id == "":
        return None, False

    registry = er.async_get(hass)
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None, False

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    lookup_device = devices.get(device_id, None)
    if lookup_device is None:
        return None, False

    energy_entity = lookup_device.get("energy_entity", None)
    if energy_entity is not None and hass.states.get(energy_entity):
        return energy_entity, False

    sensors = []
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
            sensors.append(entry)

    if not sensors:
        return None, False

    sensors.sort(key=lambda entry: entry.platform.lower() != "powercalc")
    energy_entity = sensors[0].entity_id
    lookup_device["energy_entity"] = energy_entity

    return energy_entity, True


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
        {"change"},
    )

    yearly_energy = 0.0
    for day in data.get(energy_meter_entity, []):
        daily_nrg = day.get("change", 0.0)
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


async def utils_get_device_energy_consumption_map(
    hass: HomeAssistant, device_id: str, granularity: str
) -> dict:
    """Return a dictionary mapping a device's energy consumption by the given time granularity.

    The keys are formatted as "%d-%m-%Y-%H".
    """
    energy_entity, _ = utils_find_energy_entity_for_device(hass, device_id)
    _LOGGER.debug("No energy entity found for device id %s, skipping", device_id)
    if not energy_entity:
        return None

    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.now() - timedelta(days=365),
        dt_util.now(),
        {energy_entity},
        granularity,
        None,
        {"sum"},
    )

    result = {}
    for stat in stats.get(energy_entity, []):
        start_ts = stat.get("start")
        if not start_ts:
            continue
        dt = dt_util.as_local(dt_util.utc_from_timestamp(start_ts))
        map_key = dt.strftime("%d-%m-%Y-%H")
        result[map_key] = stat.get("sum", 0)

    return result


async def utils_compute_device_consumption_footprint(
    hass: HomeAssistant,
    device_id: str,
    granularity: str,
    start_time: str,
    end_time: str,
) -> dict:
    """Return a dictionary mapping a device's energy consumption carbon impact by the given time granularity."""
    energy_consumption_map = await utils_get_device_energy_consumption_map(
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
    delta_energy_dict = {}
    for key, value in energy_consumption_map.items():
        if last_value:
            delta = value - last_value
            delta_energy_dict[key] = max(delta, 0)

        # if delta and delta < 0:
        #    last_value = 0
        #    continue

        last_value = value

    results = []
    match granularity:
        case "hour":
            for key, value in delta_energy_dict.items():
                data_time = dt_util.as_local(datetime.strptime(key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                consumption_cf = value * energy_store.get(key, 150.0)
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

                consumption_cf = value * energy_store.get(key, 150.0)

                if curr_date and curr_date.date() != data_time.date():
                    results.append(
                        {
                            "timestamp": curr_date.isoformat(),
                            "consumption_footprint": cumulated_fp,
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
                        "consumption_footprint": cumulated_fp,
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

                consumption_cf = value * energy_store.get(key, 150.0)

                if curr_date and curr_date.month != data_time.month:
                    results.append(
                        {
                            "timestamp": data_time.isoformat(),
                            "consumption_footprint": cumulated_fp,
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
                        "consumption_footprint": cumulated_fp,
                    }
                )

    return results


def utils_round_to_day(dt: datetime):
    """Round a date to the next day at midnight.

    Source: https://www.statology.org/how-to-round-dates-to-the-nearest-day-hour-or-minute-in-python/
    """
    return dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def utils_local_type_matching(devices: dict) -> tuple[dict, dict]:
    """Try to infer device type using regular expressions.

    `devices`: dictionary containing device info in the following format
        {
            `device_name`: {
                    `model`: "x",
                    `manufacturer`: "y"
            },
            ...
        }

    Outputs a tuple of two dictionaries: the first containing matched devices, and the second devices for which no match was found.
    """

    matched_devices = {}
    no_match_devices = {}
    for device_name, device_meta in devices.items():
        device_model = device_meta.get("model", "")
        device_manufacturer = device_meta.get("manufacturer", "")
        if device_model and device_manufacturer:
            device_model = device_model.lower()
            device_manufacturer = device_manufacturer.lower()

        device_str = f"{device_name} {device_model} {device_manufacturer}"

        matched = False
        match_type = ""
        for regex, device_type in REGEX_MATCHER:
            if not regex.search(device_str):
                continue

            matched = True
            match_type = device_type
            break

        if not matched:
            no_match_devices[device_name] = device_meta
            continue

        _LOGGER.debug("Device %s could be matched to type %s", device_name, match_type)
        matched_devices[device_name] = match_type

    return (matched_devices, no_match_devices)


async def utils_build_hourly_stamps(
    hass: HomeAssistant,
    device_id: str,
    start_time: str,
    end_time: str,
) -> list:
    """Build a device's carbon usage sensor historical data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.exception("No config entry found")
        return None

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    device_info = devices.get(device_id, None)
    if not device_info:
        return None

    if device_info.get("history_uploaded", False):
        return None

    stamps = await utils_compute_device_consumption_footprint(
        hass, device_id, "hour", start_time, end_time
    )

    stats = []
    total_cf = 0.0
    for item in stamps:
        total_cf += item.get("consumption_footprint", 0.0)
        ts = item.get("timestamp")
        if not ts:
            continue

        stats.append(
            {"start": dt_util.as_utc(datetime.fromisoformat(ts)), "sum": total_cf}
        )

    return stats
