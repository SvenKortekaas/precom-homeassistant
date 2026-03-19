"""Pre-Com beschikbaarheidsschakelaar."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_AVAILABILITY_OVERRIDE, DATA_USER_INFO, DOMAIN
from .coordinator import PreComCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PreComCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PreComAvailabilitySwitch(coordinator, entry)])


class PreComAvailabilitySwitch(CoordinatorEntity[PreComCoordinator], SwitchEntity):
    """
    Schakelaar voor Pre-Com beschikbaarheid.

    AAN  → POST SetAvailable              (beschikbaar, direct effect op NotAvailable)
    UIT  → POST UpdateUserSchedulerPeriod (roosterblok niet-beschikbaar)
           + lokale override in coordinator zodat de switch niet terugspringt

    Pre-Com heeft geen directe "niet beschikbaar" toggle zonder geofence.
    De lokale override zorgt dat de switch de juiste staat toont totdat
    het roosterblok verlopen is of tot de volgende handmatige vernieuwing.
    """

    _attr_name = "Pre-Com Beschikbaar"
    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_available_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Pre-Com",
            model="Pre-Com",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool | None:
        """
        Geef beschikbaarheidsstatus terug.

        Prioriteit:
        1. Lokale override (actief na niet-beschikbaar melden)
        2. NotAvailable uit GetUserInfo
        """
        if not self.coordinator.data:
            return None

        # 1. Lokale override
        override = self.coordinator.data.get(DATA_AVAILABILITY_OVERRIDE)
        if override is not None:
            available, until = override
            if until is None or datetime.now() <= until:
                return available

        # 2. API-waarde
        info = self.coordinator.data.get(DATA_USER_INFO, {})
        not_available = info.get("NotAvailable")
        if not_available is None:
            return None
        return not bool(not_available)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Meld beschikbaar — verwijder het agenda-blok en de lokale override."""
        _LOGGER.info("Schakelaar: beschikbaar melden")
        try:
            result = await self.coordinator.client.set_available()
            # Verwijder de lokale override — API-waarde is nu leidend
            self.coordinator.availability_override = None
            _LOGGER.info(
                "Beschikbaar gemeld — Pre-Com %s",
                "bevestigd" if result else "geen bevestiging (controleer app)",
            )
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Beschikbaar melden mislukt: %s", err)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """
        Meld niet-beschikbaar via roosterblok + lokale override.

        De override zorgt dat de switch UIT blijft staan ook al geeft
        GetUserInfo nog NotAvailable: false terug.
        """
        hours = self._get_not_available_hours()
        _LOGGER.info("Schakelaar: niet beschikbaar melden voor %d uur", hours)
        try:
            # Zet de lokale override VOOR de API-call zodat de switch
            # direct omschakelt en niet terugspringt na de refresh
            until = datetime.now() + timedelta(hours=hours)
            self.coordinator.availability_override = (False, until)
            self.async_write_ha_state()

            result = await self.coordinator.client.set_not_available(hours)
            _LOGGER.info(
                "Niet beschikbaar gemeld voor %d uur (tot %s) — Pre-Com %s",
                hours,
                until.strftime("%H:%M"),
                "bevestigd" if result else "geen bevestiging (controleer app)",
            )
            # Korte vertraging zodat Pre-Com de wijziging kan verwerken,
            # daarna refresh — de override blijft actief dus switch blijft UIT
            await self.coordinator.async_request_refresh()

        except Exception as err:
            # API-fout: verwijder de optimistische override
            self.coordinator.availability_override = None
            self.async_write_ha_state()
            _LOGGER.error("Niet beschikbaar melden mislukt: %s", err)

    def _get_not_available_hours(self) -> int:
        """Lees het aantal uren uit de bijbehorende number-entiteit."""
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
        registry = er.async_get(self.hass)
        entry_id = self._attr_unique_id.replace("_available_switch", "")
        number_uid = f"{entry_id}_not_available_hours"
        entity_entry = registry.async_get_entity_id("number", DOMAIN, number_uid)
        if entity_entry:
            state = self.hass.states.get(entity_entry)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return int(float(state.state))
                except ValueError:
                    pass
        _LOGGER.debug("Aantal uren niet gevonden — standaard 8 uur gebruikt")
        return 8
