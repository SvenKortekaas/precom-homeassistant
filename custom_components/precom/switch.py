"""Pre-Com schakelaar-platform: beschikbaarheid en capcodes."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import PreComApiError
from .const import DATA_AVAILABILITY_OVERRIDE, DATA_CAPCODES, DATA_USER_INFO, DOMAIN
from .coordinator import PreComCoordinator
from .helpers import _clean_description

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Pre-Com",
        model="Pre-Com",
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PreComCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PreComAvailabilitySwitch(coordinator, entry)])

    known_ids: set[int] = set()

    def _add_new_capcodes() -> None:
        capcodes = coordinator.data.get(DATA_CAPCODES, []) if coordinator.data else []
        new_entities: list[PreComCapcodeSwitch] = []
        for capcode in capcodes:
            cid = capcode.get("CapcodeId")
            if cid is None:
                _LOGGER.debug("Capcode overgeslagen — geen CapcodeId: %s", capcode)
                continue
            if cid not in known_ids:
                known_ids.add(cid)
                desc = _clean_description(capcode.get("Description", ""))
                new_entities.append(PreComCapcodeSwitch(coordinator, entry, cid, desc))
                _LOGGER.debug(
                    "Pre-Com: nieuwe capcode switch aangemaakt voor %s (%s)", cid, desc
                )
        if new_entities:
            async_add_entities(new_entities)

    _add_new_capcodes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_capcodes))


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

        # 2. API-waarde: directe vlag én actief roosterblok tellen als niet-beschikbaar
        info = self.coordinator.data.get(DATA_USER_INFO, {})
        not_available = info.get("NotAvailable")
        scheduled = info.get("NotAvailalbeScheduled", info.get("NotAvailableScheduled"))
        if not_available is None and scheduled is None:
            return None
        return not (bool(not_available) or bool(scheduled))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Meld beschikbaar — pending-write zorgt dat de switch niet terugklapt."""
        _LOGGER.info("Schakelaar: beschikbaar melden")
        try:
            result = await self.coordinator.client.set_available()
            self.coordinator.mark_availability_pending(True)
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.info(
                "Beschikbaar gemeld — Pre-Com %s",
                "bevestigd" if result else "geen bevestiging (controleer app)",
            )
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Beschikbaar melden mislukt: %s", err)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """
        Meld niet-beschikbaar via roosterblok.

        De pending-write zorgt dat de switch UIT blijft staan totdat de
        server het roosterblok bevestigt (of na 30 s: server wint).
        """
        hours = self._get_not_available_hours()
        _LOGGER.info("Schakelaar: niet beschikbaar melden voor %d uur", hours)
        try:
            result = await self.coordinator.client.set_not_available(hours)
            self.coordinator.mark_availability_pending(False)
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.info(
                "Niet beschikbaar gemeld voor %d uur — Pre-Com %s",
                hours,
                "bevestigd" if result else "geen bevestiging (controleer app)",
            )
            await self.coordinator.async_request_refresh()
        except Exception as err:
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


class PreComCapcodeSwitch(CoordinatorEntity[PreComCoordinator], SwitchEntity):
    """Schakelaar voor één Pre-Com capcode (inschakelen/uitschakelen op de server)."""

    _attr_icon = "mdi:radio-tower"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: PreComCoordinator,
        entry: ConfigEntry,
        capcode_id: int,
        description: str,
    ) -> None:
        super().__init__(coordinator)
        self._capcode_id = capcode_id
        user_id = coordinator.user_id or entry.entry_id
        self._attr_unique_id = f"precom_{user_id}_capcode_{capcode_id}"
        self._attr_name = (
            f"Pre-Com Capcode {description}" if description else f"Pre-Com Capcode {capcode_id}"
        )
        self._attr_device_info = _device_info(entry)
        self._was_available = True

    def _get_capcode(self) -> dict | None:
        capcodes = self.coordinator.data.get(DATA_CAPCODES, []) if self.coordinator.data else []
        return next((c for c in capcodes if c.get("CapcodeId") == self._capcode_id), None)

    @property
    def available(self) -> bool:
        return self._get_capcode() is not None and super().available

    def _handle_coordinator_update(self) -> None:
        capcode = self._get_capcode()
        now_available = capcode is not None
        if not now_available and self._was_available:
            _LOGGER.debug(
                "Pre-Com: capcode %s niet meer gevonden in API-response — switch op unavailable gezet",
                self._capcode_id,
            )
        self._was_available = now_available
        if capcode is not None:
            self._attr_is_on = capcode.get("Enable", False)
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_enable(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_enable(False)

    async def _set_enable(self, enable: bool) -> None:
        try:
            await self.coordinator.client.update_user_capcode(self._capcode_id, enable)
        except PreComApiError as err:
            raise HomeAssistantError(
                f"Capcode {self._capcode_id} kon niet worden "
                f"{'ingeschakeld' if enable else 'uitgeschakeld'}: {err}"
            ) from err
        self.coordinator.mark_capcode_pending(self._capcode_id, enable)
        self._attr_is_on = enable
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
