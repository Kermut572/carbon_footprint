"""Store class to manage data related to the carbon footprint."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_energy.data"


class EnergyStore:
    """Store for electricity maps related data.

    Basically, there is no way to query historical data from HA itself, so we either:
        - Ask an API key when installing the integration and populate this store with a query.
        - Populate the store hour by hour, day by day and someday we will have enough data.

    An EnergyStore object has two fields:
    * store: Store object from HomeAssistant
    * data: dictionary in the following format:
        * data[dd-mm-yyyy-hh] = energy_footprint

    In case we want to empty the data, everything is saved in json format in config/.storage/carbon_footprint_energy.data
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Init EnergyStore object."""
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, dict] = {}

    async def async_load_data(self) -> None:
        """Asynchronously load data."""
        data = await self.store.async_load()
        self.data = data if data is not None else {}

    async def async_save_data(self) -> None:
        """Asynchronously save data."""
        await self.store.async_save(data=self.data)

    async def async_set_energy_footprint(
        self, date_key: str, energy_footprint: int
    ) -> None:
        """Add or average an energy footprint reading to the store."""
        if self.data.get(date_key):
            energy_footprint = int((self.data[date_key] + energy_footprint) / 2)

        self.data[date_key] = energy_footprint
        await self.async_save_data()

    async def async_remove_energy_footprint(self, date_key: str) -> None:
        """Remove a device from the store."""
        del self.data[date_key]
        await self.async_save_data()

    def get_energy_footprint_data(self) -> dict[str, dict]:
        """Get the data from the store."""
        return self.data
