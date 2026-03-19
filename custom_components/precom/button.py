"""Pre-Com knoppen — handmatig data vernieuwen."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PreComCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Stel Pre-Com knoppen in."""
    coordinator: PreComCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PreComRefreshButton(coordinator, entry)])


class PreComRefreshButton(ButtonEntity):
    """Knop om handmatig alle Pre-Com data te vernieuwen."""

    _attr_name = "Pre-Com Vernieuwen"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        """Initialiseer."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pre-Com",
            model="Pre-Com",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Haal alle data opnieuw op van de Pre-Com API."""
        _LOGGER.info("Handmatige vernieuwing van Pre-Com data gestart")
        await self._coordinator.async_request_refresh()
        _LOGGER.info("Pre-Com data vernieuwd")
