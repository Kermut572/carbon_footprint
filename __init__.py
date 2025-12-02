"""The Carbon Footprint integration."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
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
from .const import DOMAIN
from .energy_store import EnergyStore
from .store import CFStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)


@dataclass
class CarbonFootprintData:
    """Data for CF integration."""

    cf_store: CFStore
    energy_store: EnergyStore


_PLATFORMS: list[Platform] = []
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
        module_url="/api/carbon_footprint/panel.js?v=1.63",  # change the version if your cache is playing tricks on you :-) (I hate js)
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

    energy_store = EnergyStore(hass)
    await energy_store.async_load_data()

    entry.runtime_data = CarbonFootprintData(
        cf_store=cf_store, energy_store=energy_store
    )

    async def async_update_energy_footprint(_now=None) -> None:
        """Update the current hourly energy footprint."""
        date = datetime.datetime.now()
        date_key = date.strftime("%d-%m-%Y-%H")

        co2_intensity_state = hass.states.get("sensor.electricity_maps_co2_intensity")
        if not co2_intensity_state:
            _LOGGER.warning("Could not get Electrity Maps integration")
            return

        if co2_intensity_state and co2_intensity_state.state in (
            "unknown",
            "unavailable",
        ):
            _LOGGER.warning("Could not get energy footprint from Electricity Maps")
            return

        energy_footprint = float(co2_intensity_state.state)
        hass.async_create_task(
            energy_store.async_set_energy_footprint(date_key, energy_footprint)
        )
        _LOGGER.debug("Stored %s gCO₂eq in the EnergyStore", energy_footprint)

    await async_update_energy_footprint()

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            async_update_energy_footprint,
            timedelta(hours=1),
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CarbonFootprintConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
