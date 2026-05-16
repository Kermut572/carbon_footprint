"""This file contains general utils functions."""

from datetime import date, datetime, timedelta
import logging
from logging import Logger
import re

from homeassistant.components import recorder
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
            r"\b(refrigerator|fridge)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Refrigerator",
    ),
    (
        re.compile(
            r"\b(wash(ing)?\smachine|cloth(es)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Washing machine",
    ),
    (
        re.compile(
            r"\b(dishwasher|dish\swasher)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Dishwasher",
    ),
    (
        re.compile(
            r"\b(tele(vision)?|tv|oled|qled|mini\sled)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "TV",
    ),
    (
        re.compile(
            r"\b(light\s(sensor|detection)|luminosity|illuminance|lux|sun)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Luminosity sensor",
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
            r"\b(window|door)\s(sensor|contact|opening|detector)\b|\b(contact\s(sensor)?)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Window/door sensor",
    ),
    (
        re.compile(
            r"\b(thermostat|temp(erature)?\scontrol)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Thermostat",
    ),
    (
        re.compile(
            r"\b(temp(erature)?|humid(ity)?|water|h2o|thermometer|wet|climate|weather)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Temperature/humidity sensor",
    ),
    (
        re.compile(
            r"\b(air\squality|carbon\smonoxide|co\ssensor|oxygen|voc|pm2\.5|pm10)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Air quality sensor",
    ),
    (
        re.compile(
            r"\b(camera|video|doorbell|webcam|cctv)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Camera",
    ),
    (
        re.compile(
            r"\b(speaker|alexa|(home\s)?cinema|music|audio)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Speaker",
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
    # Light bulb after luminosity + TV
    # Avoid matching "light sensor", "light detection", "mini led"
    (
        re.compile(
            r"\b((smart\s)?light\sbulb|bulb|lamp|lightstrip|light\sstrip|hue\sgo|rgb\slight)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Light bulb",
    ),
    (
        re.compile(
            r"\b(switch|relay)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Switch",
    ),
    (
        re.compile(
            r"\b(smoke|carbon dioxide|co2)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Smoke detector",
    ),
    (
        re.compile(
            r"\b(router|wifi|wi-fi|access\spoint|mesh|gateway|connectivity)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Router",
    ),
    (
        re.compile(
            r"\b(energy\s(monitor|control|meter)|power\smeter)\b",
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
        "Energy monitor",
    ),
]

DEVICE_BLACKLIST_RULES = [
    {
        "name": "Mobile phones",
        "description": "Personal phones are detected by Home Assistant but are not tracked as home IoT devices. If you want to add new matches:",
        "match_groups": {
            "Generic": ["phone", "smartphone", "mobile phone", "Android phone"],
            "Apple": ["iPhone"],
            "Google": ["Pixel phone", "Pixel 2+"],
            "Samsung": [
                "Galaxy S",
                "Galaxy Z",
                "Galaxy Note",
                "Galaxy A",
                "Galaxy M",
                "SM-* phone model IDs",
            ],
            "Nokia": ["Lumia", "G series", "X series", "C series", "3/4 digit models"],
            "Huawei": ["P series", "Mate", "Nova", "Y series", "Enjoy"],
            "Honor": ["Magic", "X series", "Play", "numbered models"],
            "Xiaomi": ["Mi", "numbered/T series", "Mix", "Note", "Civi"],
            "Redmi": ["Note", "K series", "numbered models"],
            "Poco": ["F series", "M series", "X series", "C series"],
            "OnePlus": ["One", "numbered/R/T/Pro", "Nord", "Open"],
            "Oppo": ["Find", "Reno", "A series", "F series"],
            "Vivo": ["X series", "Y series", "V series", "Nex", "iQOO"],
            "Realme": ["GT", "C series", "Narzo", "numbered models"],
            "Motorola": [
                "Moto E/G/X/Z",
                "Moto G Power/Play/Stylus/Pure/Fast",
                "Edge",
                "Razr",
                "One",
            ],
            "Sony": ["Xperia"],
            "Fairphone": ["Fairphone"],
            "Nothing": ["Phone"],
            "Asus": ["Zenfone", "ROG Phone"],
            "HTC": ["One", "Desire", "U series"],
            "LG": ["G series", "V series", "Velvet", "Wing", "K series", "Q series"],
            "ZTE": ["Axon", "Blade"],
            "Nubia": ["Z series", "RedMagic"],
            "BlackBerry": ["KeyOne", "Key2", "Priv", "Passport", "Classic", "Bold"],
            "Alcatel": ["OneTouch", "Idol", "numbered models"],
            "TCL": ["Plex", "numbered models"],
            "Wiko": ["View", "Y series", "Sunny", "Lenny"],
        },
        "keywords": [
            "phone",
            "smartphone",
            "mobile phone",
            "iPhone",
            "Android phone",
            "Google Pixel",
            "Pixel phone",
            "Samsung Galaxy S",
            "Samsung Galaxy Z",
            "Samsung Galaxy A",
            "Samsung Galaxy Note",
            "Nokia Lumia/G/X/C",
            "Huawei P/Mate/Nova/Y",
            "Honor Magic/X/Play",
            "Xiaomi Mi/Redmi/Poco",
            "OnePlus",
            "Oppo Find/Reno/A",
            "Vivo X/Y/V",
            "Realme",
            "Motorola Moto/Edge/Razr",
            "Sony Xperia",
            "Fairphone",
            "Nothing Phone",
            "Asus Zenfone/ROG Phone",
            "HTC One/U/Desire",
            "LG G/V/Velvet/Wing",
            "ZTE Axon/Blade",
            "Nubia/RedMagic",
            "BlackBerry",
            "Alcatel/TCL",
            "Wiko",
        ],
        "regex": re.compile(
            r"""
            \b(
                (smart\s?)?phone
                | mobile\sphone
                | android\sphone
                | iphone
                | apple\siphone
                | google\spixel
                | pixel\s(phone|[2-9]\d*(a|pro|xl)?)
                | galaxy\s(
                    s\d{1,2}(\s?(fe|plus|ultra))?
                    | z\s?(flip|fold)\d*
                    | note\s?\d*
                    | a\d{1,2}
                    | m\d{1,2}
                )
                | sm-[a-z]\d{3}[a-z0-9]*
                | nokia\s(
                    lumia\s?\d*
                    | [cgx]\d{1,2}
                    | \d{3,4}
                )
                | huawei\s(
                    p\d{1,2}(\s?(lite|pro|plus))?
                    | mate\s?\d{1,2}(\s?(lite|pro|rs))?
                    | nova\s?\d{1,2}
                    | y\d{1,2}
                    | enjoy\s?\d{1,2}
                )
                | honor\s(
                    magic\s?\d*
                    | x\d{1,2}
                    | play\s?\d*
                    | \d{1,3}(\s?(lite|pro))?
                )
                | xiaomi\s(
                    mi\s?\d{1,2}
                    | \d{1,2}t?(\s?(lite|pro|ultra))?
                    | mix\s?\d*
                    | note\s?\d*
                    | civi\s?\d*
                )
                | redmi\s(
                    note\s?\d{1,2}
                    | k\d{1,2}
                    | \d{1,2}[a-z]?
                )
                | poco\s([fmx]\d{1,2}|c\d{1,2})
                | oneplus\s(
                    one
                    | \d{1,2}(\s?(r|t|pro))?
                    | nord(\s?(ce|n)\s?\d*)?
                    | open
                )
                | oppo\s(
                    find\s?x?\d*
                    | reno\s?\d*
                    | a\d{1,2}
                    | f\d{1,2}
                )
                | vivo\s(
                    x\d{1,3}
                    | y\d{1,3}
                    | v\d{1,3}
                    | nex
                    | iqoo\s?\d*
                )
                | realme\s(
                    gt\s?\d*
                    | c\d{1,2}
                    | narzo\s?\d*
                    | \d{1,2}(\s?(pro|plus))?
                )
                | motorola\s(
                    moto\s?[egxz]\d{1,2}
                    | moto\sg\s?(power|play|stylus|pure|fast)
                    | edge\s?\d*
                    | razr\s?\d*
                    | one\s?(action|fusion|vision|zoom)?
                )
                | moto\s[egxz]\d{1,2}
                | moto\sg\s?(power|play|stylus|pure|fast)
                | sony\sxperia\s?[a-z0-9]+\b
                | xperia\s?[a-z0-9]+\b
                | fairphone\s?\d*
                | nothing\sphone\s?\(?\d*\)?
                | asus\s(
                    zenfone\s?\d*
                    | rog\sphone\s?\d*
                )
                | zenfone\s?\d*
                | rog\sphone\s?\d*
                | htc\s(
                    one\s?[a-z0-9]*
                    | desire\s?\d*
                    | u\d{1,2}
                )
                | lg\s(
                    g\d
                    | v\d{2}
                    | velvet
                    | wing
                    | k\d{1,2}
                    | q\d{1,2}
                )
                | zte\s(
                    axon\s?\d*
                    | blade\s?[a-z0-9]*
                )
                | nubia\s(z\d{1,2}|red\s?magic\s?\d*)
                | red\s?magic\s?\d*
                | blackberry\s(
                    key\s?(one|2)
                    | priv
                    | passport
                    | classic
                    | bold
                )
                | alcatel\s(
                    one\s?touch
                    | idol\s?\d*
                    | \d[svxl]?
                )
                | tcl\s(
                    plex
                    | \d{2,3}[a-z]?
                )
                | wiko\s(
                    view\s?\d*
                    | y\d{2}
                    | sunny\s?\d*
                    | lenny\s?\d*
                )
            )\b
            """,
            flags=re.UNICODE | re.IGNORECASE | re.VERBOSE,
        ),
    },
]


class ProviderError(Exception):
    """Error raised when OpenRouter returns a provider error."""


def utils_get_device_blacklist_rules() -> list[dict[str, object]]:
    """Return the device blacklist rules that are safe to expose to the frontend."""
    return [
        {
            "name": rule["name"],
            "description": rule["description"],
            "keywords": rule["keywords"],
            "match_groups": rule["match_groups"],
        }
        for rule in DEVICE_BLACKLIST_RULES
    ]


def utils_build_custom_blacklist_rules(
    custom_rules: list[dict[str, str]],
) -> list[dict[str, object]]:
    """Build frontend-safe custom ignored device rules."""
    rules = []
    for custom_rule in custom_rules:
        brand = custom_rule.get("brand", "").strip()
        model = custom_rule.get("model", "").strip()
        if not brand or not model:
            continue

        rules.append(
            {
                "name": f"{brand} {model}",
                "description": "Custom ignored device added by the user.",
                "keywords": [brand, model],
                "match_groups": {brand: [model]},
                "brand": brand,
                "model": model,
                "custom": True,
            }
        )

    return rules


def utils_get_device_blacklist_match(
    device_name: str | None,
    device_model: str | None,
    device_manufacturer: str | None,
    custom_rules: list[dict[str, str]] | None = None,
) -> str | None:
    """Return the matching blacklist rule name for a device, if any."""
    device_str = " ".join(
        str(value)
        for value in (device_name, device_model, device_manufacturer)
        if value
    )

    if not device_str:
        return None

    for rule in DEVICE_BLACKLIST_RULES:
        if rule["regex"].search(device_str):
            return str(rule["name"])

    for rule in custom_rules or []:
        brand = rule.get("brand", "").strip()
        model = rule.get("model", "").strip()
        if not brand or not model:
            continue

        if re.search(re.escape(brand), device_str, flags=re.IGNORECASE) and re.search(
            re.escape(model), device_str, flags=re.IGNORECASE
        ):
            return f"{brand} {model}"

    return None


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


async def utils_get_device_install_date(
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
    install_date = lookup_device_metadata.get("install_dt", None)
    if install_date is not None:
        ts = dt_util.parse_datetime(install_date)
        return dt_util.as_local(ts), False

    data_points = await recorder.get_instance(hass).async_add_executor_job(
        statistics_during_period,
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
    lookup_device_metadata["install_dt"] = start_utc.isoformat()

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
    data_points = await recorder.get_instance(hass).async_add_executor_job(
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
) -> tuple[str | None, str | None, bool]:
    """Return the entity_id of the energy sensor for a device_id, or None. Also returns whether the store was updated or not.

    Returns both the PowerCalc energy entity and the device's own energy entity where applicable (e.g. smart plug).
    """
    if not device_id or device_id == "":
        return None, None, False

    registry = er.async_get(hass)
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None, None, False

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    lookup_device = devices.get(device_id, None)
    if lookup_device is None:
        return None, None, False

    energy_entity = lookup_device.get("energy_entity", None)
    appliance_entity = lookup_device.get("appliance_entity", None)
    if energy_entity is not None and hass.states.get(energy_entity):
        return energy_entity, appliance_entity, False

    powercalc_sensor = None
    app_sensors = []
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
            if entry.platform.lower() == "powercalc":
                powercalc_sensor = entry.entity_id
                continue

            app_sensors.append(entry)

    energy_entity = powercalc_sensor
    lookup_device["energy_entity"] = energy_entity

    appliance_entity = None
    if len(app_sensors) == 0:
        return energy_entity, None, True

    appliance_entity = app_sensors[0].entity_id
    for sensor in app_sensors:
        if "today" in sensor.entity_id or "today" in (
            sensor.original_name or sensor.name
        ):
            appliance_entity = sensor.entity_id
            break
    lookup_device["appliance_entity"] = appliance_entity

    return energy_entity, appliance_entity, True


async def utils_get_yearly_consumption(hass: HomeAssistant) -> float:
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

    data = await recorder.get_instance(hass).async_add_executor_job(
        statistics_during_period,
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
    hass: HomeAssistant, device_id: str, granularity: str, is_appliance: bool = False
) -> dict:
    """Return a dictionary mapping a device's energy consumption by the given time granularity.

    The keys are formatted as "%d-%m-%Y-%H".
    """
    energy_entity, appliance_entity, _ = utils_find_energy_entity_for_device(
        hass, device_id
    )

    check_entity = energy_entity if not is_appliance else appliance_entity
    if not check_entity:
        _LOGGER.debug(
            "No %s energy entity found for device id %s, skipping",
            "powercalc" if not is_appliance else "appliance",
            device_id,
        )
        return None

    if is_appliance:
        _LOGGER.debug(
            "Pulling stats for appliance for device id %s, appliance entity %s",
            device_id,
            appliance_entity,
        )

    stats = await recorder.get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.now() - timedelta(days=365),
        dt_util.now(),
        {check_entity},
        granularity,
        None,
        {"sum", "state"},
    )

    result = {}
    for stat in stats.get(check_entity, []):
        start_ts = stat.get("start")
        if not start_ts:
            continue
        dt = dt_util.as_local(dt_util.utc_from_timestamp(start_ts))
        map_key = dt.strftime("%d-%m-%Y-%H")
        reading = stat.get("sum")
        if reading is None:
            reading = stat.get("state")
        if reading is None:
            continue
        result[map_key] = reading

    return result


async def utils_compute_device_consumption_footprint(
    hass: HomeAssistant,
    device_id: str,
    granularity: str,
    start_time: str,
    end_time: str,
    is_appliance: bool = False,
) -> dict:
    """Return a dictionary mapping a device's energy consumption carbon impact by the given time granularity."""
    energy_consumption_map = await utils_get_device_energy_consumption_map(
        hass,
        device_id,
        "hour",  # use hour here because we aggregate afterwards
        is_appliance,
    )
    if not energy_consumption_map:
        _LOGGER.debug("Consumption map is None, returning early")
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
    for key in sorted(
        energy_consumption_map.keys(), key=lambda k: datetime.strptime(k, "%d-%m-%Y-%H")
    ):
        value = energy_consumption_map[key]

        if last_value is None:
            last_value = value
            continue

        delta = value - last_value

        if delta < 0:
            last_value = value
            continue

        delta_energy_dict[key] = max(delta, 0)

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
    is_appliance: bool = False,
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
        _LOGGER.debug(
            "Returning early from building timestamps for device_id %s because device_info is None",
            device_id,
        )
        return None

    if not is_appliance and device_info.get("history_uploaded", False):
        _LOGGER.debug(
            "Returning early from building timestamps for iot device_id %s because history_uploaded is True",
            device_id,
        )
        return None

    if is_appliance and device_info.get("appliance_history_uploaded", False):
        _LOGGER.debug(
            "Returning early from building timestamps for appliance device_id %s because appliance_history_uploaded is True",
            device_id,
        )
        return None

    stamps = await utils_compute_device_consumption_footprint(
        hass, device_id, "hour", start_time, end_time, is_appliance
    )

    stats = []
    total_cf = 0.0
    for item in stamps:
        total_cf += item.get("consumption_footprint", 0.0)
        ts = item.get("timestamp")
        if not ts:
            continue

        stats.append(
            {
                "start": dt_util.as_utc(datetime.fromisoformat(ts)),
                "state": total_cf,
                "sum": total_cf,
            }
        )

    if stats:
        _LOGGER.debug(
            "utils_build_hourly_stamps for device %s (appliance=%s): built %d rows, first sum=%s, last sum=%s",
            device_id,
            is_appliance,
            len(stats),
            stats[0].get("sum"),
            stats[-1].get("sum"),
        )
    else:
        _LOGGER.debug(
            "utils_build_hourly_stamps for device %s (appliance=%s): returned empty stats (input stamps: %s)",
            device_id,
            is_appliance,
            stamps,
        )

    return stats
