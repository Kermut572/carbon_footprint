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

from . import ws_api
from .const import DOMAIN
from .store import CFStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


_PLATFORMS: list[Platform] = []
type CarbonFootprintConfigEntry = ConfigEntry[CFStore]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Carbon Footprint component."""
    ws_api.async_register_websocket_handlers(hass)

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
        module_url="/api/carbon_footprint/panel.js?v=1.37",  # change the version if your cache is playing tricks on you :-) (I hate js)
        embed_iframe=False,
        require_admin=False,
    )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Set up Carbon Footprint from a config entry."""

    cf_store = CFStore(hass)
    await cf_store.async_load_data()
    entry.runtime_data = cf_store

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
