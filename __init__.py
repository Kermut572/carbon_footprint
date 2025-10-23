"""The Carbon Footprint integration."""

from __future__ import annotations

import pathlib

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import web_socket_api
from .const import DOMAIN

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


_PLATFORMS: list[Platform] = []

# TODO Create ConfigEntry type alias with API object
# TODO Rename type alias and update all entry annotations
type CarbonFootprintConfigEntry = ConfigEntry[None]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Carbon Footprint component."""
    web_socket_api.async_register_websocket_handlers(hass)

    static_path_config = StaticPathConfig(
        url_path="/api/carbon_footprint",
        path=str(pathlib.Path(__file__).parent / "www"),
        cache_headers=False,
    )
    await hass.http.async_register_static_paths([static_path_config])

    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path="carbon_footprint",
        webcomponent_name="carbon-footprint-panel",
        sidebar_title="Carbon Footprint",
        sidebar_icon="mdi:leaf",
        js_url="/api/carbon_footprint/panel.js",
        embed_iframe=True,
        require_admin=False,
    )

    return True


# TODO Update entry annotation
async def async_setup_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Set up Carbon Footprint from a config entry."""

    # TODO 1. Create API instance
    # TODO 2. Validate the API connection (and authentication)
    # TODO 3. Store an API object for your platforms to access
    # entry.runtime_data = MyAPI(...)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


# TODO Update entry annotation
async def async_unload_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
