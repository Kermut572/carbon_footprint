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
from homeassistant.helpers import device_registry

from .const import BLOCKS_FOOTPRINTS, DOMAIN


@callback
def async_register_websocket_handlers(hass: HomeAssistant) -> None:
    """Register WebSocket handlers."""
    websocket_api.async_register_command(hass, ws_get_carbon_data)
    websocket_api.async_register_command(hass, ws_set_device)
    websocket_api.async_register_command(hass, ws_remove_device)
    websocket_api.async_register_command(hass, ws_compute_footprint)


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
    registry = device_registry.async_get(hass)
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
