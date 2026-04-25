"""Store class to manage data related to the carbon footprint."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"


class CFStore:
    """Store for carbon footprint related data.

    A CFStore object has two fields:
    * store: Store object from HomeAssistant
    * data: dictionary in the following format:
        * data[device_id] = entity_data
          * where entity_data is a dict containing the following keys: type, carbon_footprint, metadata
            * metadata is a dict that contains eventual arbitrary information about the device

    Basically, whenever we want to integrate/store new data for our plugin we will modify this class.

    In case we want to empty the data, everything is saved in json format in config/.storage/carbon_footprint.data
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Init CFStore object."""
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, dict] = {}

    async def async_load_data(self) -> None:
        """Asynchronously load data."""
        data = await self.store.async_load()
        self.data = data if data is not None else {}

    async def async_save_data(self) -> None:
        """Asynchronously save data."""
        await self.store.async_save(data=self.data)

    async def async_set_device_info(
        self, device_id: str, type: str, carbon_footprint: float, metadata: dict
    ) -> None:
        """Add a device to the store, or overwrite its info if it exists."""
        entity_info = {
            "type": type,
            "carbon_footprint": carbon_footprint,
            "metadata": metadata,
        }

        # just keep cu_entity, energy_entity and history_uploaded if it exists so it doesn't f up the entire logic
        curr_device_info = self.data.get(device_id, None)
        if curr_device_info is not None:
            cu_entity = curr_device_info.get("cu_entity", None)
            if cu_entity is not None:
                entity_info["cu_entity"] = cu_entity

            energy_entity = curr_device_info.get("energy_entity", None)
            if energy_entity is not None:
                entity_info["energy_entity"] = energy_entity

            history_uploaded = curr_device_info.get("history_uploaded", False)
            entity_info["history_uploaded"] = history_uploaded

        self.data[device_id] = entity_info
        await self.async_save_data()

    async def async_remove_device_info(self, device_id: str) -> None:
        """Remove a device from the store."""
        del self.data[device_id]
        await self.async_save_data()

    def get_devices_data(self) -> dict[str, dict]:
        """Get the data from the store."""
        return self.data
