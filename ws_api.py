"""WebSocket API for Carbon Footprint integration.

Basically, we will use this to send data to the frontend. A command is separated into two parts:
* The command definition, including the route and the additional data we may need
* The function executed whenever we make a call to this route

According to the function definition, the latter has access to both the hass object and the message
data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import aiohttp
from openrouter import OpenRouter
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util

from .const import BLOCKS_FOOTPRINTS, DOMAIN
from .utils import (
    utils_get_device_classes,
    utils_get_device_install_date,
    utils_get_device_total_energy_consumption,
)


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
    websocket_api.async_register_command(hass, ws_get_carbon_by_room)
    websocket_api.async_register_command(hass, ws_get_carbon_by_type)
    websocket_api.async_register_command(hass, ws_get_carbon_by_room_with_usage)
    websocket_api.async_register_command(hass, ws_get_carbon_by_type_with_usage)
    websocket_api.async_register_command(hass, ws_llm_detection)
    websocket_api.async_register_command(hass, ws_db_matching)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_devices_to_add"})
@callback
def ws_get_devices_to_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns all relevant devices' names (and their related models and manufacturers) the user could track. As of now, all devices with empty classes are removed."""
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

        device_names.append(device_name)
        device_manufacturers.append(device.manufacturer)
        device_models.append(device.model)

    connection.send_result(
        msg["id"],
        {
            "device_names": device_names,
            "device_manufacturers": device_manufacturers,
            "device_models": device_models,
        },
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
    co2_intensity_state = hass.states.get("sensor.electricity_maps_co2_intensity")

    co2_intensity = 200.0  # arbitrary

    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        co2_intensity = float(co2_intensity_state.state)

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "co2_intensity": co2_intensity,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_device",
        vol.Required("device_name"): str,
        vol.Required("device_type"): str,
        vol.Required("carbon_footprint"): vol.Coerce(float),
        vol.Optional("metadata", default={}): dict,
    }
)
@callback
async def ws_set_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set the device's data."""

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    cf_store = entries[0].runtime_data.cf_store

    metadata = msg["metadata"]

    # config_entries might be an interesting key of register: Config entries that are linked to this device.
    registry = dr.async_get(hass)
    device_name = msg["device_name"]
    register = None  # should always be found, but just in case

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

        entity_reg = er.async_get(hass)
        device_entities = er.async_entries_for_device(entity_reg, register.id)
        metadata["device_classes"] = utils_get_device_classes(
            hass=hass, device_entities=device_entities
        )

        total_energy, sensor_name = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )
        if total_energy:
            metadata["total_energy"] = total_energy

        if sensor_name:
            metadata["install_date"] = await hass.async_add_executor_job(
                utils_get_device_install_date, hass, sensor_name
            )

    hass.async_create_task(
        cf_store.async_set_device_info(
            device_name,
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    cf_store = entries[0].runtime_data.cf_store
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    cf_store = entries[0].runtime_data.cf_store
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
        hass.async_create_task(cf_store.async_save_data())

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_energy_footprint_time_interval",
        vol.Required("start_time"): str,
        vol.Required("end_time"): str,
        vol.Required("granularity"): str,
    }
)
@callback
def ws_get_energy_footprint_time_interval(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the history of the energy footprint for a given time interval."""

    start_time = dt_util.parse_datetime(msg["start_time"])
    end_time = dt_util.parse_datetime(msg["end_time"])

    if not start_time or not end_time:
        connection.send_error(msg["id"], "invalid_format", "Invalid date format")
        return

    if end_time < start_time:
        connection.send_error(msg["id"], "invalid_interval", "Invalid time interval")
        return

    granularity = msg["granularity"]
    if granularity not in ("hour", "day", "month"):
        connection.send_error(msg["id"], "invalid_granularity", "Invalid granularity")
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "Uh oh, no config entry found :-("
        )
        return

    energy_store = entries[0].runtime_data.energy_store

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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    # Get device and area registries
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)

    # Group devices by room
    rooms_dict: dict[str, dict] = {}

    for device_name, device_info in devices.items():
        # Get carbon footprint for this device
        carbon_value = device_info.get("carbon_footprint", 0)

        # Try to find the device in the registry
        device_id = device_info.get("metadata", {}).get("register_id")
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

        """
        # Fallback: Try to extract room name from device name (for test data)
        # e.g., "Living Room TV" -> "Living Room"
        if room_name == "Unknown Room":
            parts = device_name.split()
            if len(parts) >= 2:
                # Try to detect room name patterns
                potential_room = " ".join(parts[:-1])
                # Check if it looks like a room (contains common room keywords)
                if any(
                    keyword in potential_room.lower()
                    for keyword in [
                        "room",
                        "kitchen",
                        "bathroom",
                        "garage",
                        "hallway",
                        "living",
                        "bed",
                        "dining",
                    ]
                ):
                    room_name = potential_room
        """
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    # Get device and area registries
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    # Get current CO2 intensity
    co2_intensity_state = hass.states.get("sensor.electricity_maps_co2_intensity")
    co2_intensity = 200.0  # default fallback
    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        try:
            co2_intensity = float(co2_intensity_state.state)
        except ValueError | TypeError:
            co2_intensity = 200.0

    # Group devices by room
    rooms_dict: dict[str, dict] = {}

    for device_name, device_info in devices.items():
        # Get embodied carbon for this device
        embodied_carbon = device_info.get("carbon_footprint", 0)

        # Get usage carbon: prefer metadata value (for test data), fall back to power sensor calculation
        usage_carbon = 0.0
        metadata = device_info.get("metadata", {})

        total_energy = metadata.get("total_energy", None)
        if total_energy is not None:
            usage_carbon = (total_energy * co2_intensity) / 1000
        """
        # Check if there's pre-defined usage carbon in metadata (e.g., from test data)
        if "usage_carbon_kg" in metadata:
            try:
                usage_carbon = float(metadata["usage_carbon_kg"])
            except ValueError | TypeError:
                usage_carbon = 0.0
        else:
            # Try to estimate from power sensors if no metadata value
            entity_id = None
            if "register_id" in metadata:
                # Try to find the entity
                device_id = metadata["register_id"]
                if device_id in device_reg.devices:
                    device_entry = device_reg.devices[device_id]
                    # Get entities for this device
                    device_entities = er.async_entries_for_device(entity_reg, device_id)
                    # Find power sensor
                    for ent in device_entities:
                        if "power" in ent.entity_id.lower():
                            entity_id = ent.entity_id
                            break

            # If we found a power sensor, calculate usage carbon (simplified: assuming 1 hour)
            if entity_id:
                power_state = hass.states.get(entity_id)
                if power_state and power_state.state not in ("unknown", "unavailable"):
                    try:
                        power_w = float(power_state.state)
                        # Usage carbon = (power_W * co2_intensity_gCO2/kWh) / 1_000_000
                        # Simplified: hour of usage at current power
                        usage_carbon = (power_w * co2_intensity) / 1_000_000
                    except ValueError | TypeError:
                        usage_carbon = 0.0
        """
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

        # Fallback: Try to extract room name from device name
        """
        if room_name == "Unknown Room":
            parts = device_name.split()
            if len(parts) >= 2:
                potential_room = " ".join(parts[:-1])
                if any(
                    keyword in potential_room.lower()
                    for keyword in [
                        "room",
                        "kitchen",
                        "bathroom",
                        "garage",
                        "hallway",
                        "living",
                        "bed",
                        "dining",
                    ]
                ):
                    room_name = potential_room
        """

        # Initialize room if not seen before
        if room_name not in rooms_dict:
            rooms_dict[room_name] = {
                "room": room_name,
                "room_id": room_id,
                "embodied_carbon": 0,
                "usage_carbon": 0,
                "total_carbon": 0,
                "devices": [],
            }
        # Add device to room
        device_total = embodied_carbon + usage_carbon
        rooms_dict[room_name]["devices"].append(
            {
                "name": device_name,
                "embodied_carbon": round(embodied_carbon, 2),
                "usage_carbon": round(usage_carbon, 2),
                "total_carbon": round(device_total, 2),
            }
        )
        rooms_dict[room_name]["embodied_carbon"] += embodied_carbon
        rooms_dict[room_name]["usage_carbon"] += usage_carbon
        rooms_dict[room_name]["total_carbon"] += device_total

    # Convert to list, round values, and sort by total carbon
    rooms_list = []
    for room_data in rooms_dict.values():
        room_data["embodied_carbon"] = round(room_data["embodied_carbon"], 2)
        room_data["usage_carbon"] = round(room_data["usage_carbon"], 2)
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    type_dict: dict[str, dict] = {}

    for device_name, device_info in devices.items():
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    co2_intensity_state = hass.states.get("sensor.electricity_maps_co2_intensity")
    co2_intensity = 200.0  # default fallback
    if co2_intensity_state and co2_intensity_state.state not in (
        "unknown",
        "unavailable",
    ):
        try:
            co2_intensity = float(co2_intensity_state.state)
        except ValueError | TypeError:
            co2_intensity = 200.0

    cf_store = entries[0].runtime_data.cf_store
    devices = cf_store.get_devices_data()

    type_dict: dict[str, dict] = {}

    for device_name, device_info in devices.items():
        metadata = device_info.get("metadata", {})

        usage_carbon_value = 0.0
        total_energy = metadata.get("total_energy", None)
        if total_energy is not None:
            usage_carbon_value = (total_energy * co2_intensity) / 1000

        embodied_carbon_value = device_info.get("carbon_footprint", 0)
        device_type = device_info.get("type", "Unknown")

        device_total = embodied_carbon_value + usage_carbon_value

        if device_type not in type_dict:
            type_dict[device_type] = {
                "type": device_type,
                "embodied_carbon": 0,
                "usage_carbon": 0,
                "total_carbon": 0,
                "devices": [],
            }

        type_dict[device_type]["devices"].append(
            {
                "name": device_name,
                "embodied_carbon": round(embodied_carbon_value, 2),
                "usage_carbon": round(usage_carbon_value, 2),
                "total_carbon": round(device_total, 2),
                "carbon": embodied_carbon_value,
            }
        )
        type_dict[device_type]["embodied_carbon"] += embodied_carbon_value
        type_dict[device_type]["usage_carbon"] += usage_carbon_value
        type_dict[device_type]["total_carbon"] += device_total

    type_list = []
    for type_data in type_dict.values():
        type_data["embodied_carbon"] = round(type_data["embodied_carbon"], 2)
        type_data["usage_carbon"] = round(type_data["usage_carbon"], 2)
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

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    entry = entries[0]
    api_key = entry.options.get("api_key")
    if not api_key or len(api_key) == 0:
        connection.send_error(
            msg["id"],
            "api_key_not_set",
            "No API key was set. You can set it in the integration's settings.",
        )
        return

    devices = msg["devices"]

    # TODO set a list of device types.
    def _openrouter_call():
        with OpenRouter(api_key=api_key) as client:
            response = client.chat.send(
                model="google/gemma-3-12b-it:free",
                messages=[
                    {
                        "role": "user",
                        "content": f"You are given a dictionary mapping device names to their model and manufacturer. Return ONLY a valid JSON object (no explanation, no markdown, no code blocks) mapping each device name to its device type category (e.g., 'Smart Plug', 'Temperature Sensor', 'Light', 'Camera'). Input devices: {devices}",
                    }
                ],
                response_format={"type": "json_object"},
            )

        return response.choices[0].message.content

    try:
        result = await hass.async_add_executor_job(_openrouter_call)
        connection.send_result(msg["id"], {"device_types": result})
    except Exception as err:
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg["id"], "config_entry_not_found", "No config entry found"
        )
        return

    entry = entries[0]
    db_ip = entry.options.get("db_ip")
    if not db_ip or len(db_ip) == 0:
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
            session.get(db_ip + "/api/devices/approved") as resp,
        ):
            device_db = await resp.json()
    except Exception as e:
        connection.send_error(
            msg["id"],
            "db_http_error",
            f"An error occured while fetching database information: {e}",
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
            d_model.lower() + "-" + d_manufacturer.lower()
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
