"""Pre-Com number-entiteiten — instelbare waarden."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PreComNotAvailableHours(entry)])


class PreComNotAvailableHours(NumberEntity, RestoreEntity):
    """
    Instelbaar aantal uren voor niet-beschikbaar melden.

    Deze waarde wordt gebruikt door de 'Pre-Com Beschikbaar' schakelaar
    wanneer die wordt uitgeschakeld. Standaard: 8 uur.

    De waarde blijft bewaard na een HA-herstart via RestoreEntity.
    """

    _attr_name = "Pre-Com Niet Beschikbaar Uren"
    _attr_icon = "mdi:clock-remove-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 168     # 7 dagen
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "uur"
    _attr_mode = NumberMode.BOX      # Invoerveld i.p.v. slider

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_not_available_hours"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pre-Com",
            model="Pre-Com",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._value: float = 8.0  # Standaard 8 uur

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        """Sla de nieuwe waarde op."""
        self._value = value
        _LOGGER.debug("Pre-Com niet-beschikbaar uren ingesteld op %d", int(value))
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Herstel de vorige waarde na herstart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            try:
                self._value = float(last_state.state)
                _LOGGER.debug(
                    "Pre-Com niet-beschikbaar uren hersteld: %d uur", int(self._value)
                )
            except ValueError:
                pass
