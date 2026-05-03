"""The Carbon Footprint integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import pathlib

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from . import ws_api
from .const import DOMAIN, TEST_MODE
from .energy_store import EnergyStore
from .periodic import async_export_to_cfdb, async_update_energy_footprint
from .store import CFStore
from .utils import async_populate_energy_store

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)


@dataclass
class CarbonFootprintData:
    """Data for CF integration."""

    cf_store: CFStore
    energy_store: EnergyStore


_PLATFORMS: list[Platform] = [Platform.SENSOR]
type CarbonFootprintConfigEntry = ConfigEntry[CarbonFootprintData]


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
        module_url="/api/carbon_footprint/panel.js?v=3.44",  # change the version if your cache is playing tricks on you :-)
        embed_iframe=False,
        require_admin=False,
    )

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Set up Carbon Footprint from a config entry."""

    if not entry.options and entry.data:
        hass.config_entries.async_update_entry(entry=entry, options=entry.data, data={})

    cf_store = CFStore(hass)
    await cf_store.async_load_data()

    energy_store = EnergyStore(hass)
    await energy_store.async_load_data()

    entry.runtime_data = CarbonFootprintData(
        cf_store=cf_store, energy_store=energy_store
    )

    async def wrapper_async_update_energy_footprint(_now=None) -> None:
        """Wrapper for async_update_energy_footprint, which makes it periodically callable."""
        await async_update_energy_footprint(
            _now=_now, hass=hass, _LOGGER=_LOGGER, energy_store=energy_store
        )

    async def wrapper_async_export_to_cfdb(_now=None) -> None:
        """Wrapper for async_export_to_cfdb, which makes it periodically callable."""
        _LOGGER.debug("Running periodic export to CFDB at %s", _now)
        await async_export_to_cfdb(
            _now=_now, hass=hass, _LOGGER=_LOGGER, cf_store=cf_store
        )

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            wrapper_async_update_energy_footprint,
            timedelta(hours=1),
        )
    )

    entry.async_on_unload(
        async_track_time_interval(hass, wrapper_async_export_to_cfdb, timedelta(days=3))
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    # Generate test data if TEST_MODE is enabled
    if TEST_MODE:
        from .test_data import async_setup_test_data

        await async_setup_test_data(hass, energy_store, cf_store)
    else:
        # Populate with real historical data from Electricity Maps
        await async_populate_energy_store(hass, energy_store, _LOGGER)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
