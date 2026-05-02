"""WebSocket API for Carbon Footprint integration.

Basically, we will use this to send data to the frontend. A command is separated into two parts:
* The command definition, including the route and the additional data we may need
* The function executed whenever we make a call to this route

According to the function definition, the latter has access to both the hass object and the message
data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from typing import Any

import aiohttp
from dateutil.relativedelta import relativedelta
from openrouter import OpenRouter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
import voluptuous as vol

from homeassistant.components import recorder, websocket_api
from homeassistant.components.recorder import statistics
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import _LOGGER, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import BLOCKS_FOOTPRINTS, DEVICE_ADDED_SIGNAL, DOMAIN
from .recommendations import build_recommendations
from .utils import (
    ProviderError,
    utils_build_cfdb_device,
    utils_compute_device_consumption_footprint,
    utils_fetch_electricity_maps_sensor,
    utils_find_energy_entity_for_device,
    utils_get_device_classes,
    utils_get_device_install_date,
    utils_get_device_total_energy_consumption,
    utils_get_yearly_consumption,
    utils_local_type_matching,
    utils_round_to_day,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_device_type(device_type: str | None) -> tuple[str, str]:
    display_type = (device_type or "Unknown").strip() or "Unknown"
    return display_type.lower(), display_type[:1].upper() + display_type[1:].lower()


@callback
def async_register_websocket_handlers(hass: HomeAssistant) -> None:
    """Register WebSocket handlers."""
    websocket_api.async_register_command(hass, ws_get_device_autocomp)
    websocket_api.async_register_command(hass, ws_get_carbon_data)
    websocket_api.async_register_command(hass, ws_get_type_embodied_footprint)
    websocket_api.async_register_command(hass, ws_set_device)
    websocket_api.async_register_command(hass, ws_remove_device)
    websocket_api.async_register_command(hass, ws_compute_footprint)
    websocket_api.async_register_command(hass, ws_get_devices_to_add)
    websocket_api.async_register_command(hass, ws_get_all_devices_energy)
    websocket_api.async_register_command(hass, ws_update_devices_energy)
    websocket_api.async_register_command(hass, ws_get_embodied_carbon_time_interval)
    websocket_api.async_register_command(
        hass, ws_get_consumption_footprint_time_interval
    )
    websocket_api.async_register_command(hass, ws_get_carbon_by_room)
    websocket_api.async_register_command(hass, ws_get_carbon_by_type)
    websocket_api.async_register_command(hass, ws_get_carbon_by_room_with_usage)
    websocket_api.async_register_command(hass, ws_get_carbon_by_type_with_usage)
    websocket_api.async_register_command(hass, ws_llm_detection)
    websocket_api.async_register_command(hass, ws_db_matching)
    websocket_api.async_register_command(hass, ws_export_json)
    websocket_api.async_register_command(hass, ws_get_yearly_contribution)
    websocket_api.async_register_command(hass, ws_get_annual_consumption_summary)
    websocket_api.async_register_command(hass, ws_get_recommendations)
    websocket_api.async_register_command(hass, ws_reset_sensors)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_device_autocomp",
        vol.Required("device_id"): str,
    }
)
@callback
def ws_get_device_autocomp(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get a device's information to autocomplete the form."""
    device_id = msg["device_id"]
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    devices = entry.runtime_data.cf_store.get_devices_data()
    device_reg = dr.async_get(hass)
    device_entry = device_reg.async_get(device_id)
    device_info = devices.get(device_id, {})
    if len(device_info.keys()) == 0:
        if device_entry is None:
            connection.send_result(msg["id"], {"cf": 0.0, "type": ""})
            return

        model = device_entry.model
        manufacturer = device_entry.manufacturer
        name = device_entry.name_by_user or device_entry.name
        device_dict = {
            name: {
                "manufacturer": manufacturer,
                "model": model,
            }
        }
        match, _ = utils_local_type_matching(device_dict)
        device_info["type"] = match.get(name, "")

        # cf lookup
        for device in devices.values():
            if device_info["type"] != device.get("type", ""):
                continue

            device_info["carbon_footprint"] = device.get("carbon_footprint", 0.0)
            break

    connection.send_result(
        msg["id"],
        {
            "cf": device_info.get("carbon_footprint", 0.0),
            "type": device_info.get("type", ""),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_devices_to_add"})
@callback
def ws_get_devices_to_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns all relevant devices' names (and their related models and manufacturers) the user could track. As of now, all devices with empty classes are removed."""
    device_ids = []
    device_names = []
    device_manufacturers = []
    device_models = []
    registry = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    for device in registry.devices.values():
        device_entities = er.async_entries_for_device(entity_reg, device.id)
        device_classes = utils_get_device_classes(hass, device_entities)

        # The type of entry. Possible values are None and DeviceEntryType enum members (only service). <- we don't care about services
        if device.entry_type is not None:
            continue

        if device.model is None:  # most integrations/services do not have a model
            continue

        # TODO check stuff agains blacklist here

        device_name = (
            device.name_by_user or device.name
        )  # just in case device.name_by_user is not defined, which can happen quite a lot

        device_id = device.id

        device_ids.append(device_id)
        device_names.append(device_name)
        device_manufacturers.append(device.manufacturer)
        device_models.append(device.model)

    connection.send_result(
        msg["id"],
        {
            "device_ids": device_ids,
            "device_names": device_names,
            "device_manufacturers": device_manufacturers,
            "device_models": device_models,
        },
    )


def _get_loaded_entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return next(
        (entry for entry in entries if entry.state is ConfigEntryState.LOADED),
        None,
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_type_embodied_footprint",
        vol.Required("device_type"): str,
    }
)
@callback
def ws_get_type_embodied_footprint(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns the embodied footprint for a given device type."""
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    req_device_type = msg["device_type"].lower()
    devices = entry.runtime_data.cf_store.get_devices_data()
    for device_info in devices.values():
        if device_info.get("type", "").lower() != req_device_type:
            continue

        cf = device_info.get("carbon_footprint", 0.0)

        if cf != 0.0:
            connection.send_result(msg["id"], {"carbon_footprint": cf})
            return

    connection.send_result(msg["id"], {"carbon_footprint": 0.0})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_data",
    }
)
@callback
def ws_get_carbon_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get carbon data command."""
    # CO_2 intensity in gCO2/kWh
    em_sensor = utils_fetch_electricity_maps_sensor(hass)
    co2_intensity_state = hass.states.get(em_sensor)

    co2_intensity = 150.0  # arbitrary
    status = "fallback"

    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        co2_intensity = float(co2_intensity_state.state)
        status = "available"

    # entries = hass.config_entries.async_entries(DOMAIN)
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    device_reg = dr.async_get(hass)
    devices = cf_store.get_devices_data()

    updated_metadata = False
    area_reg = ar.async_get(hass)
    for device_id, device_info in devices.items():
        device_entry = device_reg.devices.get(device_id)
        if not device_entry:
            continue

        metadata = device_info.setdefault("metadata", {})

        updated_device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )
        curr_device_name = metadata.get("display_name", "")
        if updated_device_name != curr_device_name:
            updated_metadata = True
            metadata["display_name"] = updated_device_name

        updated_area_id = device_entry.area_id or "undefined"
        if metadata.get("area_id") != updated_area_id:
            updated_metadata = True
            metadata["area_id"] = updated_area_id

        updated_area_name = "N/A"
        if device_entry.area_id and (
            area_entry := area_reg.async_get_area(device_entry.area_id)
        ):
            updated_area_name = area_entry.name

        if metadata.get("area_name") != updated_area_name:
            updated_metadata = True
            metadata["area_name"] = updated_area_name

    if updated_metadata:
        hass.async_create_task(cf_store.async_save_data())

    intensity_history = []
    energy_store = getattr(entry.runtime_data, "energy_store", None)
    if energy_store is not None:
        for (
            date_key,
            intensity_value,
        ) in energy_store.get_energy_footprint_data().items():
            try:
                timestamp = datetime.strptime(date_key, "%d-%m-%Y-%H")
            except ValueError:
                continue

            try:
                intensity_history.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "intensity": float(intensity_value),
                    }
                )
            except Exception:
                continue

        intensity_history.sort(key=lambda item: item["timestamp"])

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "co2_intensity": co2_intensity,
            "co2_intensity_status": status,
            "intensity_history": intensity_history,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_device",
        vol.Optional("device_name"): str,
        vol.Optional("device_id"): str,
        vol.Required("device_type"): str,
        vol.Required("carbon_footprint"): vol.Coerce(float),
        vol.Optional("metadata", default={}): dict,
    }
)
@websocket_api.async_response
async def ws_set_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set the device's data."""

    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store

    metadata = msg["metadata"]

    # config_entries might be an interesting key of register: Config entries that are linked to this device.
    registry = dr.async_get(hass)
    device_name = msg.get("device_name")
    device_id = msg.get("device_id")

    register = None
    if device_id:
        register = registry.devices.get(device_id)

    if not register and device_name:
        for device in registry.devices.values():
            if device_name not in (device.name_by_user, device.name):
                continue

            register = device
            break

    # all metadata we can add: https://developers.home-assistant.io/docs/device_registry_index/
    if register:
        metadata["area_id"] = register.area_id or "undefined"
        metadata["area_name"] = "N/A"
        area_entry = ar.async_get(hass).async_get_area(register.area_id)
        if register.area_id and area_entry:
            metadata["area_name"] = area_entry.name
        metadata["manufacturer"] = register.manufacturer
        metadata["model"] = register.model
        metadata["model_id"] = register.model_id
        metadata["register_id"] = register.id
        metadata["display_name"] = register.name_by_user or register.name
        device_id = register.id

        entity_reg = er.async_get(hass)
        device_entities = er.async_entries_for_device(entity_reg, register.id)
        metadata["device_classes"] = utils_get_device_classes(
            hass=hass, device_entities=device_entities
        )

        total_energy, _ = await hass.async_add_executor_job(
            utils_get_device_total_energy_consumption, hass, device_entities
        )

        if total_energy:
            metadata["total_energy"] = total_energy

    hass.async_create_task(
        cf_store.async_set_device_info(
            device_id,
            msg["device_type"],
            msg["carbon_footprint"],
            metadata,
        )
    )

    async_dispatcher_send(hass, DEVICE_ADDED_SIGNAL, device_id)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_device",
        vol.Required("device_name"): str,
    }
)
@callback
def ws_remove_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a device's data."""
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    hass.async_create_task(cf_store.async_remove_device_info(msg["device_name"]))

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/compute_footprint",
        vol.Optional("hsl_values", default={}): dict[str, str],
    }
)
@callback
def ws_compute_footprint(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Compute footprint of a device using all of the HSL."""
    blocks_hsl = msg["hsl_values"]
    values = [0.0, 0.0, 0.0]

    for key in blocks_hsl:
        idx = blocks_hsl.get(key)

        tmp = BLOCKS_FOOTPRINTS.get(key).get(idx)
        if tmp[0] is not None:
            values = [round(v + t, 2) for v, t in zip(values, tmp, strict=False)]

    connection.send_result(msg["id"], {"success": True, "values": values})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_all_devices_energy"}
)
@callback
def ws_get_all_devices_energy(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns all the devices and their total energy consumption."""
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    results = []

    for devices in device_reg.devices.values():
        device_entities = er.async_entries_for_device(entity_reg, devices.id)
        total_energy, _ = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )

        if total_energy is None:
            continue

        device_name = devices.name_by_user or devices.name
        results.append(
            {
                "device_id": devices.id,
                "device_name": device_name,
                "total_energy_kwh": round(total_energy, 2),
            }
        )

    connection.send_result(msg["id"], {"devices_energy": results})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/update_devices_energy"}
)
@callback
def ws_update_devices_energy(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update the total energy consumed of all registered devices."""
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()
    device_updated = False
    for device_data in devices.values():
        metadata = device_data.get("metadata")

        register_id = metadata.get("register_id")
        if not register_id:
            continue

        entity_reg = er.async_get(hass)
        device_entities = er.async_entries_for_device(entity_reg, register_id)
        total_energy, _ = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )

        if not total_energy:
            continue

        metadata["total_energy"] = total_energy
        device_data["metadata"] = metadata
        device_updated = True

    if device_updated:
        _LOGGER.debug("Updating cf_store from ws_update_energy call")
        hass.async_create_task(cf_store.async_save_data())

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_consumption_footprint_time_interval",
        vol.Required("start_time"): str,
        vol.Required("end_time"): str,
        vol.Required("granularity"): str,
        vol.Optional("is_appliance", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_get_consumption_footprint_time_interval(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the history of the consumption footprint for a given time interval."""
    start_time = dt_util.parse_datetime(msg["start_time"])
    end_time = dt_util.parse_datetime(msg["end_time"])

    if not start_time or not end_time:
        _LOGGER.error(
            "No start_date or date_time set for call to ws_get_energy_footprint_time_interval"
        )
        connection.send_error(msg["id"], "invalid_format", "Invalid date format")
        return

    if end_time < start_time:
        _LOGGER.error(
            "Invalid time interval for call to ws_get_energy_footprint_time_interval"
        )
        connection.send_error(msg["id"], "invalid_interval", "Invalid time interval")
        return

    granularity = msg["granularity"]
    if granularity not in ("hour", "day", "month"):
        _LOGGER.error(
            "Invalid granularity for call to ws_get_energy_footprint_time_interval"
        )
        connection.send_error(msg["id"], "invalid_granularity", "Invalid granularity")
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.exception("No config entry found")
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    is_appliance = msg.get("is_appliance", False)

    device_name_map = {}
    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    devices_consumptions = {}

    device_cu_map = {}
    for device_id, device_info in devices.items():
        cu_entity = (
            device_info.get("cu_entity", None)
            if not is_appliance
            else device_info.get("cu_app_entity", None)
        )
        if not cu_entity:
            continue

        device_cu_map[device_id] = cu_entity
        device_name_map[device_id] = device_info.get("metadata", {}).get(
            "display_name", "err"
        )

    stats = await recorder.get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.as_utc(start_time),
        dt_util.as_utc(end_time),
        set(device_cu_map.values()),
        granularity,
        None,
        {"change"},
    )

    for device_id, cu_entity in device_cu_map.items():
        data = stats.get(cu_entity, None)
        if not data:
            continue

        data_points = []
        last_reading = None
        for dp in data:
            start_ts = dp.get("start", None)
            if not start_ts:
                continue

            reading = dp.get("change", None)
            if not reading:
                continue

            # if not last_reading:
            #    last_reading = reading
            #    continue

            # delta_reading = max(reading - last_reading, 0.0)
            ts_local = dt_util.as_local(dt_util.utc_from_timestamp(start_ts))
            data_points.append(
                {
                    "timestamp": ts_local.replace(tzinfo=None).isoformat(),
                    "consumption_footprint": reading,  # delta_reading,
                }
            )
            last_reading = reading

        if data_points:
            devices_consumptions[device_id] = data_points

    # _LOGGER.debug("PROCESSED DEVICES")
    # _LOGGER.debug(devices_consumptions)

    # response format: {"device_1": [{"ts_1": cf_1, "ts_2":cf_2,...}], "device_2": [], ...}
    connection.send_result(
        msg["id"],
        {
            "devices_consumptions": devices_consumptions,
            "device_name_map": device_name_map,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_embodied_carbon_time_interval",
        vol.Required("start_time"): str,
        vol.Required("end_time"): str,
        vol.Required("granularity"): str,
    }
)
@websocket_api.async_response
async def ws_get_embodied_carbon_time_interval(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the repartition of the embodied carbon footprint over a given time interval."""

    start_time = dt_util.parse_datetime(msg["start_time"])
    end_time = dt_util.parse_datetime(msg["end_time"])

    if not start_time or not end_time:
        _LOGGER.error(
            "No start_date or date_time set for call to ws_get_embodied_carbon_time_interval"
        )
        connection.send_error(msg["id"], "invalid_format", "Invalid date format")
        return

    if end_time < start_time:
        _LOGGER.error(
            "Invalid time interval for call to ws_get_embodied_carbon_time_interval"
        )
        connection.send_error(msg["id"], "invalid_interval", "Invalid time interval")
        return

    granularity = msg["granularity"]
    if granularity not in ("hour", "day", "month"):
        _LOGGER.error(
            "Invalid granularity for call to ws_get_embodied_carbon_time_interval"
        )
        connection.send_error(msg["id"], "invalid_granularity", "Invalid granularity")
        return

    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return
    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()
    response = {}
    for device_id, device_info in devices.items():
        carbon_footprint = (
            device_info.get("carbon_footprint", 0) * 1000
        )  # by default it is in kgCO2eq
        lifetime_years = device_info.get("lifetime_years", 5)

        (
            energy_entity,
            appliance_entity,
            en_store_updated,
        ) = await hass.async_add_executor_job(
            utils_find_energy_entity_for_device, hass, device_id
        )
        if not energy_entity:
            # _LOGGER.debug("Could not find energy entity for device %s", device_id)
            continue

        install_date, id_store_updated = (
            await utils_get_device_install_date(hass, energy_entity, device_id)
            if appliance_entity is None
            else await utils_get_device_install_date(hass, appliance_entity, device_id)
        )  # favor appliance_entity if it exists because it was 100% installed before powercalc
        if not install_date:
            # _LOGGER.debug("Could not find install date for device %s", device_id)
            continue

        if en_store_updated or id_store_updated:
            hass.async_create_task(cf_store.async_save_data())

        cf_per_hour = (carbon_footprint / lifetime_years) / 8766  # nb hours in a year
        curr_date = start_time

        results = []
        while curr_date < utils_round_to_day(end_time):
            embodied_footprint = 0
            next_date = curr_date
            match granularity:
                case "hour":
                    embodied_footprint = cf_per_hour
                    next_date += timedelta(hours=1)
                case "day":
                    embodied_footprint = cf_per_hour * 24
                    next_date += timedelta(days=1)
                case "month":
                    days_in_month = (
                        curr_date.replace(month=curr_date.month % 12 + 1, day=1)
                        - timedelta(days=1)
                    ).day
                    embodied_footprint = cf_per_hour * 24 * days_in_month
                    next_date += relativedelta(months=1)

            if curr_date >= install_date:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "embodied_footprint": embodied_footprint,
                    }
                )

            curr_date = next_date

        response[device_id] = results
        # _LOGGER.debug("PROCESSED DEVICES EMBODIED CARBON: %s", device_id)
        # _LOGGER.debug(results)

    connection.send_result(
        msg["id"],
        {
            "embodied_carbon": response,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_carbon_by_room"})
@callback
def ws_get_carbon_by_room(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get carbon footprint grouped by room/area.

    Groups all configured devices by their Home Assistant room/area and sums
    their carbon footprints. Returns data suitable for pie/bar chart visualization.

    Response format:
    {
        "rooms": [
            {
                "room": "Living Room",
                "room_id": "area_id_123",
                "total_carbon": 45.23,
                "devices": [
                    {"name": "TV", "carbon": 20.5},
                    {"name": "Heater", "carbon": 24.73}
                ]
            },
            ...
        ]
    }
    """
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()

    # Get device and area registries
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)

    # Group devices by room
    rooms_dict: dict[str, dict] = {}

    for device_id, device_info in devices.items():
        # Get carbon footprint for this device
        carbon_value = device_info.get("carbon_footprint", 0)

        # Try to find the device in the registry
        device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )
        room_name = "Unknown Room"
        room_id = None

        if device_id and device_id in device_reg.devices:
            device_entry = device_reg.devices[device_id]
            area_id = device_entry.area_id

            if area_id:
                room_id = area_id
                # Get area registry to get the human-readable name
                area_ent = area_reg.async_get_area(area_id)
                if area_ent:
                    room_name = area_ent.name

        # Initialize room if not seen before
        if room_name not in rooms_dict:
            rooms_dict[room_name] = {
                "room": room_name,
                "room_id": room_id,
                "total_carbon": 0,
                "devices": [],
            }

        # Add device to room
        rooms_dict[room_name]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "carbon": carbon_value,
            }
        )
        rooms_dict[room_name]["total_carbon"] += carbon_value

    # Convert to list and sort by total carbon (descending)
    rooms_list = list(rooms_dict.values())
    rooms_list.sort(key=lambda x: x["total_carbon"], reverse=True)

    connection.send_result(msg["id"], {"rooms": rooms_list})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_carbon_by_room_with_usage",
        vol.Optional("is_appliance", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_get_carbon_by_room_with_usage(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get carbon footprint by room with both embodied and usage breakdown.

    Returns embodied carbon (manufacturing/transport) and estimated usage carbon
    (power consumption × CO2 intensity) for each room.

    Response format:
    {
        "rooms": [
            {
                "room": "Living Room",
                "room_id": "area_id_123",
                "embodied_carbon": 45.0,
                "usage_carbon": 12.5,
                "total_carbon": 57.5,
                "devices": [
                    {
                        "name": "TV",
                        "embodied_carbon": 15.5,
                        "usage_carbon": 0.5,
                        "total_carbon": 16.0
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()

    # Get device and area registries
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    is_appliance = msg.get("is_appliance", False)

    # Get current CO2 intensity
    em_sensor = utils_fetch_electricity_maps_sensor(hass)
    co2_intensity_state = hass.states.get(em_sensor)
    co2_intensity = 150.0  # default fallback
    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        try:
            co2_intensity = float(co2_intensity_state.state)
        except ValueError | TypeError:
            _LOGGER.warning("No ElectricityMaps sensor found, defaulting to 150gCO2/eq")
            co2_intensity = 150.0

    # Group devices by room
    rooms_dict: dict[str, dict] = {}

    for device_id, device_info in devices.items():
        # Get embodied carbon for this device
        embodied_carbon = device_info.get("carbon_footprint", 0)

        # Get usage carbon: prefer metadata value (for test data), fall back to power sensor calculation
        metadata = device_info.get("metadata", {})

        device = device_reg.async_get(device_id)
        if device is None:
            continue
        device_name = device.name_by_user or device.name

        usage_carbon_value = 0.0
        cu_entity = (
            device_info.get("cu_entity")
            if not is_appliance
            else device_info.get("cu_app_entity")
        )
        _LOGGER.debug("USING %s for device %s", cu_entity, device_name)
        if cu_entity:
            state = hass.states.get(cu_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    usage_carbon_value = float(state.state) / 1000.0
                except Exception:
                    usage_carbon_value = 0.0

        predicted_usage_carbon_value = 0.0
        lifetime_days = device_info.get("lifetime_years", 5) * 365
        install_date_str = metadata.get("install_dt", None)
        install_dt = None
        if install_date_str:
            install_dt = dt_util.parse_datetime(install_date_str)

        if install_dt:
            if install_dt.tzinfo is None:
                install_dt = dt_util.as_local(install_dt)
            days_elapsed = max((dt_util.now() - install_dt).days, 1)
            predicted_usage_carbon_value = (
                usage_carbon_value / days_elapsed
            ) * lifetime_days

        # Try to find the room
        room_name = "Unknown Room"
        room_id = None

        device_id = metadata.get("register_id")
        if device_id and device_id in device_reg.devices:
            device_entry = device_reg.devices[device_id]
            area_id = device_entry.area_id

            if area_id:
                room_id = area_id
                area_ent = area_reg.async_get_area(area_id)
                if area_ent:
                    room_name = area_ent.name

        # Initialize room if not seen before
        if room_name not in rooms_dict:
            rooms_dict[room_name] = {
                "room": room_name,
                "room_id": room_id,
                "embodied_carbon": 0,
                "usage_carbon": 0,
                "predicted_carbon": 0,
                "total_carbon": 0,
                "devices": [],
            }
        # Add device to room
        device_total = embodied_carbon + usage_carbon_value
        rooms_dict[room_name]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "embodied_carbon": round(embodied_carbon, 2),
                "usage_carbon": round(usage_carbon_value, 2),
                "predicted_carbon": round(predicted_usage_carbon_value, 2),
                "total_carbon": round(device_total, 2),
            }
        )
        rooms_dict[room_name]["embodied_carbon"] += embodied_carbon
        rooms_dict[room_name]["usage_carbon"] += usage_carbon_value
        rooms_dict[room_name]["predicted_carbon"] += predicted_usage_carbon_value
        rooms_dict[room_name]["total_carbon"] += device_total

    # Convert to list, round values, and sort by total carbon
    rooms_list = []
    for room_data in rooms_dict.values():
        room_data["embodied_carbon"] = round(room_data["embodied_carbon"], 2)
        room_data["usage_carbon"] = round(room_data["usage_carbon"], 2)
        room_data["predicted_carbon"] = round(room_data["predicted_carbon"], 2)
        room_data["total_carbon"] = round(room_data["total_carbon"], 2)
        rooms_list.append(room_data)

    rooms_list.sort(key=lambda x: x["total_carbon"], reverse=True)

    connection.send_result(msg["id"], {"rooms": rooms_list})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_carbon_by_type"})
@callback
def ws_get_carbon_by_type(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get carbon footprint grouped by type.

    Groups all configured devices by their type (e.g. smart plug, camera,...) room/area and sums
    their carbon footprints. Returns data suitable for pie/bar chart visualization.

    Response format:
    {
        "types": [
            {
                "type": "Smart Plug",
                "total_carbon": 41.0,
                "devices": [
                    {"name": "Fridge plug", "carbon": 20.5},
                    {"name": "Server plug", "carbon": 20.5}
                ]
            },
            ...
        ]
    }
    """

    device_reg = dr.async_get(hass)
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()

    type_dict: dict[str, dict] = {}

    for device_id, device_info in devices.items():
        metadata = device_info.get("metadata", {})
        device_entry = device_reg.async_get(device_id)
        device_name = (
            (device_entry.name_by_user or device_entry.name)
            if device_entry
            else metadata.get("display_name", device_id)
        )
        carbon_value = device_info.get("carbon_footprint", 0)
        device_type_key, device_type_label = _normalize_device_type(
            device_info.get("type", "Unknown")
        )

        if device_type_key not in type_dict:
            type_dict[device_type_key] = {
                "type": device_type_label,
                "total_carbon": 0,
                "devices": [],
            }

        type_dict[device_type_key]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "carbon": carbon_value,
            }
        )
        type_dict[device_type_key]["total_carbon"] += carbon_value

    type_list = list(type_dict.values())
    type_list.sort(key=lambda x: x["total_carbon"], reverse=True)

    connection.send_result(msg["id"], {"types": type_list})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_carbon_by_type_with_usage",
        vol.Optional("is_appliance", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_get_carbon_by_type_with_usage(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get carbon footprint by type with both embodied and usage breakdown.

    Returns embodied carbon (manufacturing/transport) and estimated usage carbon
    (power consumption × CO2 intensity) for each device type.

    Response format:
    {
        "types": [
            {
                "type": "Smart plug",
                "embodied_carbon": 20.5,
                "usage_carbon": 10.0,
                "total_carbon": 30.5,
                "devices": [
                    {
                        "name": "Fridge plug",
                        "embodied_carbon": 20.5,
                        "usage_carbon": 10.0,
                        "total_carbon": 30.5
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """

    em_sensor = utils_fetch_electricity_maps_sensor(hass)
    co2_intensity_state = hass.states.get(em_sensor)
    co2_intensity = 150.0  # default fallback
    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        try:
            co2_intensity = float(co2_intensity_state.state)
        except ValueError | TypeError:
            _LOGGER.warning(
                "No Electricity Maps sensor found, defaulting to 150gCO2/eq"
            )
            co2_intensity = 150.0

    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    device_reg = dr.async_get(hass)
    devices = cf_store.get_devices_data()

    is_appliance = msg.get("is_appliance", False)

    type_dict: dict[str, dict] = {}

    for device_id, device_info in devices.items():
        metadata = device_info.get("metadata", {})
        device_entry = device_reg.async_get(device_id)
        device_name = (
            (device_entry.name_by_user or device_entry.name)
            if device_entry
            else metadata.get("display_name", device_id)
        )

        usage_carbon_value = 0.0
        cu_entity = (
            device_info.get("cu_entity")
            if not is_appliance
            else device_info.get("cu_app_entity")
        )
        if cu_entity:
            state = hass.states.get(cu_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    usage_carbon_value = float(state.state) / 1000.0
                except Exception:
                    usage_carbon_value = 0.0

        predicted_usage_carbon_value = 0.0
        lifetime_days = device_info.get("lifetime_years", 5) * 365
        install_date_str = metadata.get("install_dt", None)
        install_dt = None
        if install_date_str:
            install_dt = dt_util.parse_datetime(install_date_str)

        if install_dt:
            if install_dt.tzinfo is None:
                install_dt = dt_util.as_local(install_dt)
            days_elapsed = max((dt_util.now() - install_dt).days, 1)
            predicted_usage_carbon_value = (
                usage_carbon_value / days_elapsed
            ) * lifetime_days

        embodied_carbon_value = device_info.get("carbon_footprint", 0)
        device_type_key, device_type_label = _normalize_device_type(
            device_info.get("type", "Unknown")
        )

        device_total = embodied_carbon_value + usage_carbon_value

        if device_type_key not in type_dict:
            type_dict[device_type_key] = {
                "type": device_type_label,
                "embodied_carbon": 0,
                "usage_carbon": 0,
                "total_carbon": 0,
                "predicted_carbon": 0,
                "devices": [],
            }

        type_dict[device_type_key]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "embodied_carbon": round(embodied_carbon_value, 2),
                "usage_carbon": round(usage_carbon_value, 2),
                "total_carbon": round(device_total, 2),
                "predicted_carbon": round(predicted_usage_carbon_value, 2),
                "carbon": embodied_carbon_value,
            }
        )
        type_dict[device_type_key]["embodied_carbon"] += embodied_carbon_value
        type_dict[device_type_key]["usage_carbon"] += usage_carbon_value
        type_dict[device_type_key]["predicted_carbon"] += predicted_usage_carbon_value
        type_dict[device_type_key]["total_carbon"] += device_total

    type_list = []
    for type_data in type_dict.values():
        type_data["embodied_carbon"] = round(type_data["embodied_carbon"], 2)
        type_data["usage_carbon"] = round(type_data["usage_carbon"], 2)
        type_data["predicted_carbon"] = round(type_data["predicted_carbon"], 2)
        type_data["total_carbon"] = round(type_data["total_carbon"], 2)
        type_list.append(type_data)

    type_list.sort(key=lambda x: x["total_carbon"], reverse=True)

    connection.send_result(msg["id"], {"types": type_list})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/llm_detection", vol.Required("devices"): dict}
)
@websocket_api.async_response
async def ws_llm_detection(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Calls an OpenAI model to determine the type of the user's devices."""

    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    devices = msg["devices"]
    device_types = [
        "Temperature/humidity sensor",
        "Motion sensor",
        "Luminosity sensor",
        "Air quality sensor",
        "Camera",
        "Speaker",
        "Light bulb",
        "Smart plug",
        "Smart lock",
        "Window/door sensor",
        "Thermostat",
        "Energy monitor",
        "Washing machine",
        "TV",
        "Refrigerator",
        "Dishwasher",
        "Switch",
        "Smoke detector",
        "Router",
    ]

    matched_device_types, devices_to_match = utils_local_type_matching(devices)
    if len(devices_to_match.keys()) == 0:
        _LOGGER.debug("All devices could be matched locally, returning early")
        connection.send_result(
            msg["id"],
            {
                "device_types": json.dumps(matched_device_types),
                "unmatched_devices": json.dumps({}),
            },
        )
        return

    _LOGGER.debug("Could not detect device types for %s", devices_to_match)

    api_key = entry.options.get("api_key")
    if not api_key or len(api_key) == 0:
        _LOGGER.warning(
            "No OpenRouter API Key set. This can be set in the integration settings. Defaulting to local regex matching (might not infer types for all devices)"
        )
        connection.send_result(
            msg["id"],
            {
                "device_types": json.dumps(matched_device_types),
                "unmatched_devices": json.dumps(devices_to_match),
            },
        )
        return

    def _openrouter_call():
        try:
            with OpenRouter(api_key=api_key) as client:
                response = client.chat.send(
                    model="google/gemma-3-12b-it:free",
                    messages=[
                        {
                            "role": "user",
                            "content": f"You are given a dictionary mapping device names to their model and manufacturer. Return ONLY a valid JSON object (no explanation, no markdown, no code blocks) mapping each device name to its device type category (and limit yourself to these devices types: {device_types}). Input devices: {devices_to_match}",
                        }
                    ],
                    response_format={"type": "json_object"},
                )
        except Exception as err:
            msg_err = str(err)
            if "Provider returned error" in msg_err:
                raise ProviderError from err
            raise

        return response.choices[0].message.content

    i = 1

    @retry(
        wait=wait_fixed(45),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(ProviderError),
        reraise=True,
    )
    async def _run_job():
        result = await hass.async_add_executor_job(_openrouter_call)
        connection.send_result(
            msg["id"],
            {
                "device_types": json.dumps(json.loads(result) | matched_device_types),
                "unmatched_devices": json.dumps({}),
            },
        )

    try:
        _LOGGER.debug("Running OpenRouter detection, call %d/10", i + 1)
        await _run_job()
        i += 1
    except ProviderError as err:
        _LOGGER.error(
            "OpenRouter provider error after retries: %s\nDefaulting to local regex matching (might not infer types for all devices)",
            err,
        )
        connection.send_result(
            msg["id"],
            {
                "device_types": json.dumps(matched_device_types),
                "unmatched_devices": json.dumps(devices_to_match),
            },
        )
    except Exception:
        _LOGGER.exception(
            "Error occured during OpenRouter detection. Defaulting to local regex matching (might not infer types for all devices)"
        )
        connection.send_result(
            msg["id"],
            {
                "device_types": json.dumps(matched_device_types),
                "unmatched_devices": json.dumps(devices_to_match),
            },
        )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/db_matching", vol.Required("device_types"): dict}
)
@websocket_api.async_response
async def ws_db_matching(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Calls the DB REST API in order to match carbon values."""
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    db_ip = entry.options.get("db_ip")
    if not db_ip or len(db_ip) == 0:
        _LOGGER.error("No CFDB domain set. You can set it in the integration settings")
        connection.send_error(
            msg["id"],
            "db_ip_not_set",
            "No API endpoint (db_ip) was set. You can set it in the integration's settings.",
        )
        return

    device_db = None
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(db_ip.rstrip("/") + "/api/devices/approved") as resp,
        ):
            device_db = await resp.json()
    except Exception as e:
        _LOGGER.exception("An error occured while fetching CFDB information")
        connection.send_error(
            msg["id"],
            "db_http_error",
            f"An error occured while fetching CFDB information: {e}",
        )
        return

    devices_carbon = {}
    for device in device_db:
        device_id = device.get("id").lower()
        device_carbon = device.get("carbon_footprint")[0]["mid"]
        if not device_id or not device_carbon:
            continue

        devices_carbon[device_id] = device_carbon

    types_carbon = {}
    for device in device_db:
        device_type = device.get("type", "").lower()
        device_carbon = device.get("carbon_footprint")[0]["mid"]
        if not device_type or not device_carbon:
            continue

        if device_type in types_carbon:
            continue

        types_carbon[device_type] = device_carbon

    devices_matched = {}
    device_types: dict = msg["device_types"]
    for d_name, values in device_types.items():
        d_type = values.get("device_type").lower()
        d_model = values.get("model")
        d_manufacturer = values.get("manufacturer")
        d_id = (
            d_model.lower().strip() + "-" + d_manufacturer.lower().strip()
            if d_model and d_manufacturer
            else "none"
        )
        d_footprint = (
            devices_carbon.get(d_id)
            if d_id in devices_carbon
            else types_carbon.get(d_type, 0.0)
        )
        devices_matched[d_name] = {
            "device_type": f"{d_type}",
            "carbon_footprint": d_footprint,
        }

    connection.send_result(msg["id"], {"devices_matched": devices_matched})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/export_json"})
@websocket_api.async_response
async def ws_export_json(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Export the added devices to a JSON array to upload them on the interface."""
    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()

    json_array = []
    for device in devices.values():
        device_dict = utils_build_cfdb_device(device)

        json_array.append(device_dict)

    cfdb_token = entry.options.get("cfdb_token")
    if not cfdb_token or len(cfdb_token) == 0:
        # no token defined so we just return the json_array
        _LOGGER.error("No CFDB token set, check integration settings to set one")
        connection.send_result(msg["id"], {"json_array": json_array, "uploaded": "no"})
        return

    db_ip = entry.options.get("db_ip")
    if not db_ip or len(db_ip) == 0:
        _LOGGER.error("No CFDB domain set, check integration settings to set one")
        connection.send_result(msg["id"], {"json_array": json_array, "uploaded": "no"})
        return

    url = db_ip.rstrip("/") + "/ha/devices"
    headers = {
        "Authorization": f"Bearer {cfdb_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(url=url, headers=headers, json=json_array) as resp,
        ):
            text = await resp.text()
            if resp.status >= 400:
                _LOGGER.error("HTTP error %d when uploading devices", resp.status)
                connection.send_result(
                    msg["id"], {"json_array": json_array, "uploaded": "no"}
                )

    except Exception as e:
        _LOGGER.exception("Error when uploading devices to CFDB")
        connection.send_result(msg["id"], {"json_array": json_array, "uploaded": "no"})
        return

    _LOGGER.debug("Successfully uploaded devices to CFDB interface")
    connection.send_result(msg["id"], {"json_array": json_array, "uploaded": "yes"})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_yearly_contribution"}
)
@websocket_api.async_response
async def ws_get_yearly_contribution(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns the yearly carbon/energy contribution of HA devices."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.exception("No config entry found")
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    energy_meter = entries[0].options.get("energy_meter")
    yearly_energy = await utils_get_yearly_consumption(hass)

    total_energy_consumed = 1.0
    for device_id, device_stats in devices.items():
        if energy_meter and device_id == energy_meter:
            continue

        device_energy_entity = device_stats.get("energy_entity", None)
        if device_energy_entity is None:
            continue

        device_metadata = device_stats.get("metadata", {})
        total_energy_consumed += device_metadata.get("total_energy", 1.0)

    yearly_contrib = round(
        (total_energy_consumed / (yearly_energy if yearly_energy != 0.0 else 1)) * 100,
        2,
    )

    if yearly_contrib > 100:
        _LOGGER.warning(
            "Incoherent value of %d calculated for yearly contribution. Make sure a valid energy meter or a fallback energy value is set",
            yearly_contrib,
        )

    connection.send_result(
        msg["id"],
        {"yearly_contribution": yearly_contrib},
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_annual_consumption_summary"}
)
@websocket_api.async_response
async def ws_get_annual_consumption_summary(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return annual/available-period carbon consumption summary for dashboard cards."""
    entry = _get_loaded_entry(hass)
    if not entry:
        _LOGGER.exception("No config entry found")
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    end_time = dt_util.now()
    start_time = end_time - relativedelta(years=1)

    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()
    carbon_usage_entities = {
        device_info.get("cu_entity")
        for device_info in devices.values()
        if device_info.get("cu_entity")
    }

    if not carbon_usage_entities:
        connection.send_result(
            msg["id"],
            {
                "kgCO2eq": 0,
                "carKm": 0,
                "rangeText": "No carbon consumption data available yet.",
            },
        )
        return

    stats = await recorder.get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.as_utc(start_time),
        dt_util.as_utc(end_time),
        carbon_usage_entities,
        "day",
        None,
        {"change"},
    )

    total_grams = 0.0
    first_data_time = None
    for entity_stats in stats.values():
        for datapoint in entity_stats:
            reading = datapoint.get("change")
            start_ts = datapoint.get("start")
            if not reading or not start_ts:
                continue

            total_grams += float(reading)
            datapoint_time = dt_util.as_local(dt_util.utc_from_timestamp(start_ts))
            if first_data_time is None or datapoint_time < first_data_time:
                first_data_time = datapoint_time

    if first_data_time is None:
        connection.send_result(
            msg["id"],
            {
                "kgCO2eq": 0,
                "carKm": 0,
                "rangeText": "No carbon consumption data available yet.",
            },
        )
        return

    has_full_year = first_data_time <= start_time
    range_text = (
        "Based on the last 12 months of available data."
        if has_full_year
        else (
            f"This data is from {first_data_time.date().isoformat()} to today; "
            "no further data available."
        )
    )

    connection.send_result(
        msg["id"],
        {
            "kgCO2eq": total_grams / 1000,
            "carKm": total_grams / 218,
            "rangeText": range_text,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_recommendations",
        vol.Optional("room_data", default=[]): list,
        vol.Optional("yearly_contribution", default=0): vol.Any(float, int, str, None),
        vol.Optional("usage_history", default={}): dict,
        vol.Optional("intensity_history", default=[]): list,
        vol.Optional("current_intensity", default=None): vol.Any(float, int, str, None),
    }
)
@websocket_api.async_response
async def ws_get_recommendations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return dashboard recommendations computed by the backend."""
    try:
        _LOGGER.debug(
            "Computing recommendations: rooms=%d, usage_devices=%d, intensity_points=%d, current_intensity=%s",
            len(msg.get("room_data") or []),
            len(msg.get("usage_history") or {}),
            len(msg.get("intensity_history") or []),
            msg.get("current_intensity"),
        )
        recommendations = build_recommendations(
            msg.get("room_data") or [],
            msg.get("yearly_contribution"),
            msg.get("usage_history") or {},
            msg.get("intensity_history") or [],
            msg.get("current_intensity"),
        )
    except Exception as err:
        _LOGGER.exception("Failed to compute recommendations")
        connection.send_error(
            msg["id"],
            "recommendation_error",
            f"Failed to compute recommendations: {err}",
        )
        return

    connection.send_result(msg["id"], recommendations)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/reset_sensors", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_reset_sensors(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reset and rebuild a sensor's history."""
    entry = _get_loaded_entry(hass)
    if not entry:
        _LOGGER.exception("No config entry found")
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    entity_reg = er.async_get(hass)

    device_id = msg["device_id"]
    cf_store = entry.runtime_data.cf_store
    devices = cf_store.get_devices_data()
    device_info = devices.get(device_id, None)
    if device_info is None:
        _LOGGER.warning(
            "Device with id %s is not in the carbon footprint store", device_id
        )
        connection.send_error(
            msg["id"],
            "err_no_device_found",
            f"Device with id {device_id} does not exist in the CF store",
        )
        return

    device_name = device_info.get("metadata", {}).get("display_name", "err")
    iot_sensor = device_info.get("cu_entity", "cf_err_no_device")
    app_sensor = device_info.get("cu_app_entity", "cf_err_no_device")

    _LOGGER.debug("Resetting sensor %s for device %s", iot_sensor, device_name)

    sensors_remove = []
    iot_sensor_entry = entity_reg.async_get(iot_sensor)
    if iot_sensor_entry is not None:
        iot_sensor_entity = iot_sensor_entry.entity_id
        if iot_sensor_entity is not None:
            _LOGGER.debug(
                "Queuing %s sensor and history from device %s for removal",
                iot_sensor,
                device_name,
            )

            sensors_remove.append(iot_sensor_entity)
            device_info["cu_entity"] = ""

    app_sensor_entry = entity_reg.async_get(app_sensor)
    if app_sensor_entry is not None:
        app_sensor_entity = app_sensor_entry.entity_id
        if app_sensor_entity is not None:
            _LOGGER.debug(
                "Queuing %s sensor and history from device %s for removal",
                app_sensor,
                device_name,
            )

            sensors_remove.append(app_sensor_entity)
            device_info["cu_app_entity"] = ""

    device_info["history_uploaded"] = False
    device_info["appliance_history_uploaded"] = False
    hass.async_create_task(cf_store.async_save_data())

    recorder.get_instance(hass).async_clear_statistics(sensors_remove)
    for sensor_id in sensors_remove:
        entity_reg.async_remove(sensor_id)

    async_dispatcher_send(
        hass, DEVICE_ADDED_SIGNAL, device_id
    )  # fire device added event to force sensor(s) recreation

    connection.send_result(msg["id"], {"success": True})
