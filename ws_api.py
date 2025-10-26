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
        vol.Required("entity_id"): str,
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
    # only way to asynchronously call this function
    hass.async_create_task(
        store.async_set_device_info(
            msg["entity_id"],
            msg["device_type"],
            msg["carbon_footprint"],
            msg["metadata"],  # maybe save previous consumption in metadata?
        )
    )

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_device",
        vol.Required("entity_id"): str,
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
    hass.async_create_task(store.async_remove_device_info(msg["entity_id"]))

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
