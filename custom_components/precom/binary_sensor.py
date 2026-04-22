"""Pre-Com binary sensoren — beschikbaarheid en alarmstatus."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_ALARM_MESSAGES,
    DATA_AVAILABILITY_OVERRIDE,
    DATA_OVERRIDE_CLEARED_AT,
    DATA_USER_INFO,
    DOMAIN,
)
from .coordinator import PreComCoordinator

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
    """Stel Pre-Com binary sensoren in."""
    coordinator: PreComCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PreComAvailabilitySensor(coordinator, entry),
        PreComOutsideRegionSensor(coordinator, entry),
        PreComAlarmActiveSensor(coordinator, entry),
    ])


class _BaseBinarySensor(CoordinatorEntity[PreComCoordinator], BinarySensorEntity):
    """Basis klasse."""

    def __init__(
        self, coordinator: PreComCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)

    def _user_info(self) -> dict:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get(DATA_USER_INFO) or {}


# ---------------------------------------------------------------------------
# 1. Beschikbaarheidssensor — ben ik beschikbaar bij Pre-Com?
# ---------------------------------------------------------------------------

class PreComAvailabilitySensor(_BaseBinarySensor):
    """
    Binary sensor: ben ik beschikbaar bij Pre-Com?

    Aan  = beschikbaar
    Uit  = niet beschikbaar

    Attributen tonen ook 'tot wanneer' als Pre-Com een verloopdatum teruggeeft.
    """

    _attr_name = "Pre-Com Beschikbaar"
    _attr_icon = "mdi:account-check"
    # Geen device_class zodat de sensor neutraal groen/grijs kleurt
    # (connectivity zou blauw zijn, presence is ook een optie)
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "availability")

    @property
    def is_on(self) -> bool | None:
        """
        Geef True terug als de gebruiker beschikbaar is.

        Prioriteit:
        1. Lokale override (actief na niet-beschikbaar melden via switch)
        2. NotAvailable uit GetUserInfo (omgekeerde logica)
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
        info = self._user_info()
        if not info:
            return None
        not_available = info.get("NotAvailable")
        scheduled = info.get("NotAvailalbeScheduled", info.get("NotAvailableScheduled"))
        if not_available is None and scheduled is None:
            return None
        return not (bool(not_available) or bool(scheduled))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self._user_info()
        attrs: dict[str, Any] = {}

        if self.coordinator.data:
            override = self.coordinator.data.get(DATA_AVAILABILITY_OVERRIDE)
            cleared_at: datetime | None = self.coordinator.data.get(DATA_OVERRIDE_CLEARED_AT)

            if override is not None:
                available, until = override
                if until is None or datetime.now() <= until:
                    attrs["bron"] = "lokale override (roosterblok)"
                    if until:
                        attrs["niet_beschikbaar_tot"] = until.isoformat()
                        attrs["niet_beschikbaar_tot_leesbaar"] = _format_until(
                            until.isoformat()
                        )
            else:
                attrs["bron"] = "server"
                if cleared_at is not None:
                    attrs["override_ingetrokken_om"] = cleared_at.isoformat()

        # Niet-beschikbaar timestamp uit de API (als die niet de null-datum is)
        timestamp = info.get("NotAvailableTimestamp", "")
        if timestamp and not timestamp.startswith("0001-01-01"):
            attrs["api_niet_beschikbaar_tot"] = timestamp
            attrs["api_niet_beschikbaar_tot_leesbaar"] = _format_until(timestamp)

        scheduled = info.get("NotAvailalbeScheduled", info.get("NotAvailableScheduled"))
        if scheduled is not None:
            attrs["gepland_niet_beschikbaar"] = bool(scheduled)

        geofence = info.get("Geofence", {})
        if geofence and geofence.get("Selectable"):
            attrs["geofence_adres"] = geofence.get("Address", "")
            attrs["geofence_afstand"] = geofence.get("Distance", 0)

        return attrs


# ---------------------------------------------------------------------------
# 2. Buiten-regio sensor
# ---------------------------------------------------------------------------

class PreComOutsideRegionSensor(_BaseBinarySensor):
    """Binary sensor: ben ik buiten mijn regio gemeld bij Pre-Com?"""

    _attr_name = "Pre-Com Buiten Regio"
    _attr_icon = "mdi:map-marker-off"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "outside_region")

    @property
    def is_on(self) -> bool:
        """
        Geef True terug als de gebruiker buiten regio is.

        Pre-Com heeft geen apart OutsideRegion veld in GetUserInfo.
        De buiten-regio status wordt geregistreerd via de Available/SetOutsideRegion
        API-call maar is niet terug te lezen in de userinfo.
        Deze sensor geeft daarom altijd False totdat Pre-Com dit veld toevoegt.
        """
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "opmerking": (
                "Buiten-regio status is niet beschikbaar via de Pre-Com API. "
                "Gebruik de service precom.set_outside_region om dit in te stellen."
            )
        }


# ---------------------------------------------------------------------------
# 3. Alarm-actief sensor — ongewijzigd, maar nu in hetzelfde bestand
# ---------------------------------------------------------------------------

class PreComAlarmActiveSensor(_BaseBinarySensor):
    """Binary sensor: is het laatste alarm nog niet beantwoord?"""

    _attr_name = "Pre-Com Alarm Actief"
    _attr_icon = "mdi:alarm-light-outline"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alarm_active")

    @property
    def is_on(self) -> bool:
        messages = (
            self.coordinator.data.get(DATA_ALARM_MESSAGES, [])
            if self.coordinator.data
            else []
        )
        if not messages:
            return False
        latest = max(
            messages,
            key=lambda m: m.get("MsgInID", m.get("Id", 0)),
            default=None,
        )
        if latest is None:
            return False
        return not latest.get("IsReplied", True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        messages = (
            self.coordinator.data.get(DATA_ALARM_MESSAGES, [])
            if self.coordinator.data
            else []
        )
        if not messages:
            return {}
        latest = max(messages, key=lambda m: m.get("MsgInID", m.get("Id", 0)))
        return {
            "alarm_id": latest.get("MsgInID", latest.get("Id")),
            "tekst": latest.get("Text", latest.get("Msg", "")),
            "tijd": latest.get("ReceivedDateTime", latest.get("DateTime", "")),
            "gereageerd": latest.get("IsReplied", False),
        }


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------

def _parse_datetime(value: str) -> datetime | None:
    """Probeer een datum/tijdstring te parsen in gangbare Pre-Com formaten."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%m-%Y %H:%M",
    ):
        try:
            return datetime.strptime(value[:19], fmt[:len(value[:19])])
        except ValueError:
            continue
    return None


def _format_until(value: str) -> str:
    """Formatteer een datum/tijdstring naar een leesbare Nederlandse weergave."""
    dt = _parse_datetime(value)
    if dt is None:
        return value

    now = datetime.now()
    diff = dt - now

    if diff.total_seconds() < 0:
        return f"verlopen ({dt.strftime('%d %b %H:%M')})"

    total_minutes = int(diff.total_seconds() / 60)
    hours, minutes = divmod(total_minutes, 60)
    days = diff.days

    if days >= 1:
        return f"nog {days}d {hours % 24}u ({dt.strftime('%d %b %H:%M')})"
    if hours >= 1:
        return f"nog {hours}u {minutes}m ({dt.strftime('%H:%M')})"
    return f"nog {minutes} minuten ({dt.strftime('%H:%M')})"
