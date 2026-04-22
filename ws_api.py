"""WebSocket API for Carbon Footprint integration.

Basically, we will use this to send data to the frontend. A command is separated into two parts:
* The command definition, including the route and the additional data we may need
* The function executed whenever we make a call to this route

According to the function definition, the latter has access to both the hass object and the message
data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
from openrouter import OpenRouter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import _LOGGER, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util

from .const import BLOCKS_FOOTPRINTS, DOMAIN
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
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_register_websocket_handlers(hass: HomeAssistant) -> None:
    """Register WebSocket handlers."""
    websocket_api.async_register_command(hass, ws_get_carbon_data)
    websocket_api.async_register_command(hass, ws_set_device)
    websocket_api.async_register_command(hass, ws_remove_device)
    websocket_api.async_register_command(hass, ws_compute_footprint)
    websocket_api.async_register_command(hass, ws_get_devices_to_add)
    websocket_api.async_register_command(hass, ws_get_all_devices_energy)
    websocket_api.async_register_command(hass, ws_update_devices_energy)
    websocket_api.async_register_command(hass, ws_get_energy_footprint_time_interval)
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

    updated_name = False
    for device_id, device_info in devices.items():
        device_entry = device_reg.devices.get(device_id)
        if not device_entry:
            continue

        updated_device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )
        curr_device_name = device_info.get("metadata", {}).get("display_name", "")
        if updated_device_name != curr_device_name:
            updated_name = True
            device_info.get("metadata", {})["display_name"] = updated_device_name

    if updated_name:
        hass.async_create_task(cf_store.async_save_data())

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "co2_intensity": co2_intensity,
            "co2_intensity_status": status,
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

        total_energy, sensor_name = await hass.async_add_executor_job(
            utils_get_device_total_energy_consumption, hass, device_entities
        )

        if total_energy:
            metadata["total_energy"] = total_energy

        if sensor_name:
            metadata["install_date"] = await hass.async_add_executor_job(
                utils_get_device_install_date, hass, sensor_name
            )

    hass.async_create_task(
        cf_store.async_set_device_info(
            device_id,
            msg["device_type"],
            msg["carbon_footprint"],
            metadata,
        )
    )

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

    device_name_map = {}
    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()
    devices_consumptions = {}
    for device_id in devices:
        consumption_timestamps = await hass.async_add_executor_job(
            utils_compute_device_consumption_footprint,
            hass,
            device_id,
            granularity,
            msg["start_time"],
            msg["end_time"],
        )

        if (
            consumption_timestamps is None or len(consumption_timestamps) == 0
        ):  # ignore devices that have no consumption
            continue

        devices_consumptions[device_id] = consumption_timestamps
        device_name_map[device_id] = (
            devices.get(device_id, {}).get("metadata", {}).get("display_name", "err")
        )

    _LOGGER.debug("PROCESSED DEVICES")
    _LOGGER.debug(devices_consumptions)

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
        vol.Required("type"): f"{DOMAIN}/get_energy_footprint_time_interval",
        vol.Required("start_time"): str,
        vol.Required("end_time"): str,
        vol.Required("granularity"): str,
    }
)
@websocket_api.async_response
async def ws_get_energy_footprint_time_interval(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the history of the energy footprint for a given time interval."""

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

    entry = _get_loaded_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_entry_not_loaded", "Uh oh, no loaded entry found :-("
        )
        return

    energy_store = entry.runtime_data.energy_store

    results = []

    match granularity:
        case "hour":
            for date_key, energy_footprint in energy_store.data.items():
                data_time = dt_util.as_local(datetime.strptime(date_key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                results.append(
                    {
                        "timestamp": data_time.isoformat(),
                        "energy_footprint": energy_footprint,
                    }
                )
        case "day":
            curr_date = None
            cumulated_fp = 0
            days = 0

            for date_key, energy_footprint in energy_store.data.items():
                data_time = dt_util.as_local(datetime.strptime(date_key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                if curr_date and curr_date.date() != data_time.date():
                    results.append(
                        {
                            "timestamp": curr_date.isoformat(),
                            "energy_footprint": cumulated_fp / days,
                        }
                    )
                    days = 0
                    cumulated_fp = 0

                curr_date = data_time
                cumulated_fp += energy_footprint
                days += 1

            if curr_date and days > 0:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "energy_footprint": cumulated_fp / days,
                    }
                )

        case "month":
            curr_date = None
            cumulated_fp = 0
            days = 0

            for date_key, energy_footprint in energy_store.data.items():
                data_time = dt_util.as_local(datetime.strptime(date_key, "%d-%m-%Y-%H"))
                if data_time > end_time or data_time < start_time:
                    continue

                if curr_date and curr_date.month != data_time.month:
                    results.append(
                        {
                            "timestamp": data_time.isoformat(),
                            "energy_footprint": cumulated_fp / days,
                        }
                    )
                    days = 0
                    cumulated_fp = 0

                curr_date = data_time
                cumulated_fp += energy_footprint
                days += 1

            if curr_date and days > 0:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "energy_footprint": cumulated_fp / days,
                    }
                )

    connection.send_result(msg["id"], {"energy_footprints": results})

    return


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

    devices = entry.runtime_data.cf_store.get_devices_data()
    response = {}
    for device_id, device_info in devices.items():
        carbon_footprint = (
            device_info.get("carbon_footprint", 0) * 1000
        )  # by default it is in kgCO2eq
        lifetime_years = device_info.get("lifetime_years", 5)

        energy_entity = await hass.async_add_executor_job(
            utils_find_energy_entity_for_device, hass, device_id
        )
        if not energy_entity:
            _LOGGER.debug("Could not find energy entity for device %s", device_id)
            continue

        install_date = await hass.async_add_executor_job(
            utils_get_device_install_date, hass, energy_entity
        )
        if not install_date:
            _LOGGER.debug("Could not find install date for device %s", device_id)
            continue

        HOURS_IN_YEAR = 8766

        cf_per_hour = (carbon_footprint / lifetime_years) / HOURS_IN_YEAR
        curr_date = install_date

        results = []
        while curr_date < end_time:
            embodied_footprint = 0
            next_date = curr_date
            match granularity:
                case "hour":
                    embodied_footprint = cf_per_hour
                    next_date += timedelta(hours=1)
                    break
                case "day":
                    embodied_footprint = cf_per_hour * 24
                    next_date += timedelta(days=1)
                    break
                case "month":
                    days_in_month = (
                        curr_date.replace(month=curr_date.month % 12 + 1, day=1)
                        - timedelta(days=1)
                    ).day
                    embodied_footprint = cf_per_hour * 24 * days_in_month
                    next_date += timedelta(days=days_in_month)
                    break

            if curr_date >= install_date:
                results.append(
                    {
                        "timestamp": curr_date.isoformat(),
                        "embodied_footprint": embodied_footprint,
                    }
                )

            curr_date = next_date

        response[device_id] = results
        _LOGGER.debug("PROCESSED DEVICES EMBODIED CARBON: %s", device_id)
        _LOGGER.debug(results)

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
    {vol.Required("type"): f"{DOMAIN}/get_carbon_by_room_with_usage"}
)
@callback
def ws_get_carbon_by_room_with_usage(
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
        usage_carbon = 0.0
        metadata = device_info.get("metadata", {})

        device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )

        total_energy = metadata.get("total_energy", None)
        if total_energy is not None:
            usage_carbon = (total_energy * co2_intensity) / 1000

        predicted_usage_carbon_value = 0.0
        install_date = metadata.get("install_date", None)
        if install_date is not None:
            install_dt = dt_util.parse_datetime(
                str(install_date)
            )  # weirdly, install_date is neither a str neither a datetime??
            datetime_from_installation = datetime.now().replace(
                tzinfo=None
            ) - install_dt.replace(tzinfo=None)
            days_from_installation = max(datetime_from_installation.days, 1)
            predicted_usage_carbon_value = (
                usage_carbon / days_from_installation
            ) * 1825  # 1825 days for five years

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
        device_total = embodied_carbon + usage_carbon
        rooms_dict[room_name]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "embodied_carbon": round(embodied_carbon, 2),
                "usage_carbon": round(usage_carbon, 2),
                "predicted_carbon": round(predicted_usage_carbon_value, 2),
                "total_carbon": round(device_total, 2),
            }
        )
        rooms_dict[room_name]["embodied_carbon"] += embodied_carbon
        rooms_dict[room_name]["usage_carbon"] += usage_carbon
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
        device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )
        carbon_value = device_info.get("carbon_footprint", 0)
        device_type = device_info.get("type", "Unknown")

        if device_type not in type_dict:
            type_dict[device_type] = {
                "type": device_type,
                "total_carbon": 0,
                "devices": [],
            }

        type_dict[device_type]["devices"].append(
            {
                "id": device_id,
                "name": device_name,
                "carbon": carbon_value,
            }
        )
        type_dict[device_type]["total_carbon"] += carbon_value

    type_list = list(type_dict.values())
    type_list.sort(key=lambda x: x["total_carbon"], reverse=True)

    connection.send_result(msg["id"], {"types": type_list})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_carbon_by_type_with_usage"}
)
@callback
def ws_get_carbon_by_type_with_usage(
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

    type_dict: dict[str, dict] = {}

    for device_id, device_info in devices.items():
        metadata = device_info.get("metadata", {})
        device_name = (
            device_reg.devices.get(device_id).name_by_user
            or device_reg.devices.get(device_id).name
        )

        usage_carbon_value = 0.0
        total_energy = metadata.get("total_energy", None)
        if total_energy is not None:
            usage_carbon_value = (total_energy * co2_intensity) / 1000

        predicted_usage_carbon_value = 0.0
        install_date = metadata.get("install_date", None)
        if install_date is not None:
            install_dt = dt_util.parse_datetime(str(install_date))
            datetime_from_installation = datetime.now().replace(
                tzinfo=None
            ) - install_dt.replace(tzinfo=None)
            days_from_installation = max(datetime_from_installation.days, 1)
            predicted_usage_carbon_value = (
                usage_carbon_value / days_from_installation
            ) * 1825  # 1825 days for five years

        embodied_carbon_value = device_info.get("carbon_footprint", 0)
        device_type = device_info.get("type", "Unknown")

        device_total = embodied_carbon_value + usage_carbon_value

        if device_type not in type_dict:
            type_dict[device_type] = {
                "type": device_type,
                "embodied_carbon": 0,
                "usage_carbon": 0,
                "total_carbon": 0,
                "predicted_carbon": 0,
                "devices": [],
            }

        type_dict[device_type]["devices"].append(
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
        type_dict[device_type]["embodied_carbon"] += embodied_carbon_value
        type_dict[device_type]["usage_carbon"] += usage_carbon_value
        type_dict[device_type]["predicted_carbon"] += predicted_usage_carbon_value
        type_dict[device_type]["total_carbon"] += device_total

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

    api_key = entry.options.get("api_key")
    if not api_key or len(api_key) == 0:
        _LOGGER.error(
            "No OpenRouter API Key set. This can be set in the integration settings"
        )
        connection.send_error(
            msg["id"],
            "api_key_not_set",
            "No API key was set. You can set it in the integration's settings.",
        )
        return

    devices = msg["devices"]
    device_types = [
        "Temperature/humidity sensor",
        "Motion sensor",
        "Luminosity sensor",
        "Air quality sensor",
        "Smart camera",
        "Smart speaker",
        "Smart light bulb",
        "Smart plug",
        "Smart lock",
        "Window/door sensor",
        "Smart thermostat",
        "Smart energy monitor",
        "Smart washing machine",
        "Smart TV",
        "Smart refrigerator",
        "Smart dishwasher",
    ]

    def _openrouter_call():
        try:
            with OpenRouter(api_key=api_key) as client:
                response = client.chat.send(
                    model="google/gemma-3-12b-it:free",
                    messages=[
                        {
                            "role": "user",
                            "content": f"You are given a dictionary mapping device names to their model and manufacturer. Return ONLY a valid JSON object (no explanation, no markdown, no code blocks) mapping each device name to its device type category (and limit yourself to these devices types: {device_types}). Input devices: {devices}",
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
        connection.send_result(msg["id"], {"device_types": result})

    try:
        _LOGGER.debug("Running OpenRouter detection, call %d/10", i + 1)
        await _run_job()
        i += 1
    except ProviderError as err:
        _LOGGER.error("OpenRouter provider error after retries: %s", err)
        connection.send_error(
            msg["id"],
            "openrouter_call_error",
            "Device type detection failed due to a provider error, please try again later.",
        )
    except Exception as err:
        _LOGGER.exception("Error occured during OpenRouter detection")
        connection.send_error(
            msg["id"], "openrouter_call_error", f"Device type detection failed: {err}"
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
    yearly_energy = await hass.async_add_executor_job(
        utils_get_yearly_consumption, hass
    )

    total_energy_consumed = 1.0
    for device_id, device_stats in devices.items():
        if energy_meter and device_id == energy_meter:
            continue
        device_metadata = device_stats.get("metadata", {})
        total_energy_consumed += device_metadata.get("total_energy", 1.0)

    connection.send_result(
        msg["id"],
        {
            "yearly_contribution": round(
                (total_energy_consumed / (yearly_energy if yearly_energy != 0.0 else 1))
                * 100,
                2,
            )
        },
    )
