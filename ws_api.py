"""WebSocket API for Carbon Footprint integration.

Basically, we will use this to send data to the frontend. A command is separated into two parts:
* The command definition, including the route and the additional data we may need
* The function executed whenever we make a call to this route

According to the function definition, the latter has access to both the hass object and the message
data.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import BLOCKS_FOOTPRINTS, DOMAIN
from .utils import utils_get_device_classes, utils_get_device_total_energy_consumption


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


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_devices_to_add"})
@callback
def ws_get_devices_to_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns all relevant devices' names the user could track. As of now, all devices with empty classes are removed."""
    device_names = []
    registry = dr.async_get(hass)
    entity_reg = er.async_get(hass)
    for device in registry.devices.values():
        device_entites = er.async_entries_for_device(entity_reg, device.id)
        device_classes = utils_get_device_classes(hass, device_entites)
        if len(device_classes) == 0:
            continue

        device_name = (
            device.name_by_user if device.name_by_user else device.name
        )  # just in case device.name_by_user is not defined, which can happen quite a lot
        device_names.append(device_name)

    connection.send_result(msg["id"], {"device_names": device_names})


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

    co2_intensity = 45.0
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

    store = entries[0].runtime_data
    devices = store.get_devices_data()

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
def ws_set_device(
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

    store = entries[0].runtime_data

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
        metadata["manufacturer"] = register.manufacturer
        metadata["model"] = register.model
        metadata["model_id"] = register.model_id
        metadata["register_id"] = register.id

        entity_reg = er.async_get(hass)
        device_entities = er.async_entries_for_device(entity_reg, register.id)
        metadata["device_classes"] = utils_get_device_classes(
            hass=hass, device_entities=device_entities
        )

        total_energy = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )
        if total_energy:
            metadata["total_energy"] = total_energy

    # only way to asynchronously call this function
    hass.async_create_task(
        store.async_set_device_info(
            device_name,
            msg["device_type"],
            msg["carbon_footprint"],
            metadata,  # maybe save previous consumption in metadata?
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

    store = entries[0].runtime_data
    hass.async_create_task(store.async_remove_device_info(msg["device_name"]))

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
        total_energy = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )

        if total_energy is None:
            continue

        device_name = devices.name_by_user if devices.name_by_user else devices.name
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

    store = entries[0].runtime_data
    devices = store.get_devices_data()
    device_updated = False
    for device_data in devices.values():
        metadata = device_data.get("metadata")

        register_id = metadata.get("register_id")
        total_energy = metadata.get("total_energy")
        if not register_id or not total_energy:
            continue

        entity_reg = er.async_get(hass)
        device_entities = er.async_entries_for_device(entity_reg, register_id)
        total_energy = utils_get_device_total_energy_consumption(
            hass=hass, device_entities=device_entities
        )

        if not total_energy:
            continue

        metadata["total_energy"] = total_energy
        device_data["metadata"] = metadata
        device_updated = True

    if device_updated:
        hass.async_create_task(store.async_save_data())

    connection.send_result(msg["id"], {"success": True})
