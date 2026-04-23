"""This file contains all the functions that must be executed periodically.

Those functions include the ones saving the energy footprint or energy usage every x minutes.
Note that for each of those functions a wrapper must be defined in __init.py__, as async_track_time_interval takes no additional argument.
"""

import datetime
from logging import Logger

import aiohttp

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .energy_store import EnergyStore
from .store import CFStore
from .utils import utils_build_cfdb_device, utils_fetch_electricity_maps_sensor


async def async_update_energy_footprint(
    _now=None,
    hass: HomeAssistant = None,
    _LOGGER: Logger | None = None,
    energy_store: EnergyStore = None,
) -> None:
    """Update the current hourly energy footprint."""
    date = datetime.datetime.now()
    date_key = date.strftime("%d-%m-%Y-%H")

    em_sensor = utils_fetch_electricity_maps_sensor(hass)
    co2_intensity_state = hass.states.get(em_sensor)
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


async def async_export_to_cfdb(
    _now=None,
    hass: HomeAssistant = None,
    _LOGGER: Logger | None = None,
    cf_store: CFStore = None,
) -> None:
    """Export local device data to CFDB if user consents to data sharing."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return

    share_data = entries[0].options.get("share_data", False)
    if not share_data:
        return

    devices = cf_store.get_devices_data()
    json_array = []
    updated_devices = []
    update_required = False
    for device in devices.values():
        if device.get("uploaded", False):
            continue

        device_dict = utils_build_cfdb_device(device)
        updated_devices.append(device)
        update_required = True

        json_array.append(device_dict)

    db_ip = entries[0].options.get("db_ip")
    if not db_ip or len(db_ip) == 0:
        _LOGGER.warning(
            "No CFDB IP set. If you wish to upload your data set this parameter in your settings"
        )
        return

    cfdb_token = entries[0].options.get("cfdb_token")
    if not cfdb_token or len(cfdb_token) == 0:
        _LOGGER.warning(
            "No CFDB token set. If you wish to upload your data set this parameter in your settings"
        )
        return

    if not update_required:
        _LOGGER.info("No new info to upload, skipping")
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
                _LOGGER.warning(
                    "Could not upload data to CFDB interface %d", resp.status
                )
                return

    except Exception as e:
        _LOGGER.warning("Could not upload data to CFDB interface %s", e)
        return

    _LOGGER.info("Successfully uploaded data")
    for device in updated_devices:
        device["uploaded"] = True

    hass.async_create_task(cf_store.async_save_data())
