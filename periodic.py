"""This file contains all the functions that must be executed periodically.

Those functions include the ones saving the energy footprint or energy usage every x minutes.
Note that for each of those functions a wrapper must be defined in __init.py__, as async_track_time_interval takes no additional argument.
"""

import datetime
from logging import Logger

from homeassistant.core import HomeAssistant

from . import EnergyStore


async def async_update_energy_footprint(
    _now=None,
    hass: HomeAssistant = None,
    _LOGGER: Logger | None = None,
    energy_store: EnergyStore = None,
) -> None:
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

    # Emit event so sensors can react to the update
    hass.bus.async_fire("carbon_footprint_energy_updated")

