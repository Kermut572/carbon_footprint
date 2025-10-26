"""Store class to manage data related to the carbon footprint."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"


# First time I write such documented and clean code, thank the linter I guess ¯\_(ツ)_/¯
class CFStore:
    """Store for carbon footprint related data.

    A CFStore object has two fields:
    * store: Store object from HomeAssistant
    * data: dictionary in the following format:
        * data[entity_id] = entity_data
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
        """Asynchronously load data."""
        await self.store.async_save(data=self.data)

    async def async_set_device_info(
        self, entity_id: str, type: str, carbon_footprint: float, metadata: dict
    ) -> None:
        """Add a device to the store, or overwrite its info if it exists."""
        entity_info = {
            "type": type,
            "carbon_footprint": carbon_footprint,
            "metadata": metadata,
        }
        self.data[entity_id] = entity_info
        await self.async_save_data()

    def get_devices_data(self) -> dict[str, dict]:
        """Get the data from the store."""
        return self.data
