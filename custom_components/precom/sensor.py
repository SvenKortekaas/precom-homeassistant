"""Pre-Com sensoren."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_ALARM_MESSAGES,
    DATA_SCHEDULE,
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
    coordinator: PreComCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PreComLatestAlarmSensor(coordinator, entry),
        PreComAlarmCountSensor(coordinator, entry),
        PreComNextShiftSensor(coordinator, entry),
        PreComUserInfoSensor(coordinator, entry),
    ])


class _BaseSensor(CoordinatorEntity[PreComCoordinator], SensorEntity):
    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id  = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)


class PreComLatestAlarmSensor(_BaseSensor):
    _attr_name = "Pre-Com Laatste Alarm"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "latest_alarm")

    @property
    def native_value(self) -> str | None:
        messages = self._messages()
        if not messages:
            return "Geen alarmen"
        latest = max(messages, key=lambda m: m.get("MsgInID", m.get("Id", 0)))
        return latest.get("Text", latest.get("Msg", "Onbekend alarm"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        messages = self._messages()
        if not messages:
            return {}
        latest = max(messages, key=lambda m: m.get("MsgInID", m.get("Id", 0)))
        return {
            "alarm_id":  latest.get("MsgInID", latest.get("Id")),
            "tijd":      latest.get("ReceivedDateTime", latest.get("DateTime", "")),
            "groep":     latest.get("GroupName", ""),
            "type":      latest.get("MsgType", ""),
            "capcode":   latest.get("Capcode", ""),
            "gereageerd": latest.get("IsReplied", False),
        }

    def _messages(self) -> list[dict]:
        return self.coordinator.data.get(DATA_ALARM_MESSAGES, []) if self.coordinator.data else []


class PreComAlarmCountSensor(_BaseSensor):
    _attr_name = "Pre-Com Alarm Aantal"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "alarmen"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alarm_count")

    @property
    def native_value(self) -> int:
        messages = self.coordinator.data.get(DATA_ALARM_MESSAGES, []) if self.coordinator.data else []
        return len(messages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        messages = self.coordinator.data.get(DATA_ALARM_MESSAGES, []) if self.coordinator.data else []
        return {
            "alarmen": [
                {
                    "id":    m.get("MsgInID", m.get("Id")),
                    "tekst": m.get("Text", m.get("Msg", "")),
                    "tijd":  m.get("ReceivedDateTime", m.get("DateTime", "")),
                    "groep": m.get("GroupName", ""),
                }
                for m in sorted(
                    messages,
                    key=lambda x: x.get("MsgInID", x.get("Id", 0)),
                    reverse=True,
                )[:10]
            ]
        }


class PreComNextShiftSensor(_BaseSensor):
    _attr_name = "Pre-Com Volgende Dienst"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_shift")

    @property
    def native_value(self) -> str | None:
        schedule = self.coordinator.data.get(DATA_SCHEDULE, []) if self.coordinator.data else []
        nxt = self._next(schedule)
        if not nxt:
            return "Geen geplande diensten"
        start = nxt.get("Start", nxt.get("From", ""))
        return start[:16].replace("T", " ") if start else "Onbekend"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self.coordinator.data.get(DATA_SCHEDULE, []) if self.coordinator.data else []
        upcoming = self._upcoming(schedule)
        if not upcoming:
            return {}
        nxt = upcoming[0]
        return {
            "start":       nxt.get("Start", nxt.get("From", "")),
            "einde":       nxt.get("End",   nxt.get("To", "")),
            "omschrijving": nxt.get("Subject", nxt.get("Title", "")),
            "groep":       nxt.get("GroupName", ""),
            "functie":     nxt.get("FunctionName", ""),
            "komende_diensten": [
                {
                    "start": s.get("Start", s.get("From", "")),
                    "einde": s.get("End",   s.get("To", "")),
                    "omschrijving": s.get("Subject", s.get("Title", "")),
                }
                for s in upcoming[:5]
            ],
        }

    def _next(self, schedule: list[dict]) -> dict | None:
        u = self._upcoming(schedule)
        return u[0] if u else None

    def _upcoming(self, schedule: list[dict]) -> list[dict]:
        now = datetime.now().isoformat()
        return sorted(
            [i for i in schedule if i.get("Start", i.get("From", "")) >= now],
            key=lambda x: x.get("Start", x.get("From", "")),
        )


class PreComUserInfoSensor(_BaseSensor):
    _attr_name = "Pre-Com Gebruiker"
    _attr_icon = "mdi:account"

    def __init__(self, coordinator: PreComCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "user_info")

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.data.get(DATA_USER_INFO, {}) if self.coordinator.data else {}
        return info.get("FullName") or info.get("Name") or info.get("UserName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.data.get(DATA_USER_INFO, {}) if self.coordinator.data else {}
        return {
            "e_mail":         info.get("Email", ""),
            "telefoonnummer": info.get("PhoneNumber", ""),
            "gebruikersnaam": info.get("UserName", ""),
            "id":             info.get("UserID", info.get("Id")),
        }
