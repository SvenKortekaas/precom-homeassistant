"""Pre-Com DataUpdateCoordinator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PreComApiError, PreComAuthError, PreComClient
from .const import (
    DATA_ALARM_MESSAGES,
    DATA_AVAILABILITY_OVERRIDE,
    DATA_CAPCODES,
    DATA_OVERRIDE_CLEARED_AT,
    DATA_SCHEDULE,
    DATA_USER_INFO,
    DEFAULT_ALARM_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ALARM_RECEIVED,
)

_LOGGER = logging.getLogger(__name__)

_PENDING_TIMEOUT = timedelta(seconds=30)


@dataclass
class PendingCapcodeWrite:
    capcode_id: int
    expected_enable: bool
    written_at: datetime
    expires_at: datetime


@dataclass
class PendingAvailabilityWrite:
    expected_available: bool
    written_at: datetime
    expires_at: datetime


class PreComCoordinator(DataUpdateCoordinator):
    """
    Coordinator voor Pre-Com data met twee poll-snelheden.

    - Hoofd-poll (standaard 15 s): gebruikersinfo + rooster
    - Snelle poll (standaard 30 s): alarmberichten

    Pending-write systeem:
      Na een schrijfactie (switch on/off) houdt de coordinator de verwachte
      waarde 30 s vast. Zodra de server de waarde bevestigt, of na 30 s,
      wint de server alsnog. Dit voorkomt flip-back door trage server-propagatie.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: PreComClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        alarm_scan_interval: int = DEFAULT_ALARM_SCAN_INTERVAL,
        schedule_scan_interval: int = DEFAULT_SCHEDULE_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._alarm_scan_interval = alarm_scan_interval
        self._schedule_scan_interval = schedule_scan_interval
        self._last_alarm_id: int | None = None
        self._last_schedule_update: datetime | None = None
        self._last_capcodes_update: datetime | None = None
        self._first_update = True
        self.user_id: int | None = None

        # Pending-write tracking
        self._pending_capcodes: dict[int, PendingCapcodeWrite] = {}
        self._pending_availability: PendingAvailabilityWrite | None = None

        # Beschikbaarheids-override voor consumers (coordinator.data)
        self._availability_override: tuple[bool, None] | None = None
        self._override_cleared_at: datetime | None = None

        self._alarm_coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alarms",
            update_interval=timedelta(seconds=alarm_scan_interval),
        )
        self._alarm_coordinator._async_update_data = self._async_update_alarms_only

    # ------------------------------------------------------------------
    # Pending-write API
    # ------------------------------------------------------------------

    def mark_capcode_pending(self, capcode_id: int, enable: bool) -> None:
        """Registreer een verwachte capcode-staat na een geslaagde API-schrijfactie."""
        now = datetime.now()
        self._pending_capcodes[capcode_id] = PendingCapcodeWrite(
            capcode_id=capcode_id,
            expected_enable=enable,
            written_at=now,
            expires_at=now + _PENDING_TIMEOUT,
        )
        _LOGGER.debug(
            "Pre-Com: capcode %s pending write → %s (verloopt %s)",
            capcode_id,
            enable,
            (now + _PENDING_TIMEOUT).strftime("%H:%M:%S"),
        )

    def mark_availability_pending(self, expected: bool) -> None:
        """Registreer een verwachte beschikbaarheidsstaat na een geslaagde API-schrijfactie."""
        now = datetime.now()
        self._pending_availability = PendingAvailabilityWrite(
            expected_available=expected,
            written_at=now,
            expires_at=now + _PENDING_TIMEOUT,
        )
        self._availability_override = (expected, None)
        self._override_cleared_at = None
        _LOGGER.debug(
            "Pre-Com: beschikbaarheid pending write → %s (verloopt %s)",
            "beschikbaar" if expected else "niet-beschikbaar",
            (now + _PENDING_TIMEOUT).strftime("%H:%M:%S"),
        )

    # ------------------------------------------------------------------
    # Hoofd-update: gebruikersinfo + rooster (traag)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Haal volledige data op van de Pre-Com API."""
        try:
            user_info = await self.client.get_user_info()
            if self.user_id is None and user_info:
                self.user_id = user_info.get("UserID") or user_info.get("Id")

            alarm_messages = await self.client.get_alarm_messages()
            await self._check_new_alarms(alarm_messages)

            now = datetime.now()
            schedule = self.data.get(DATA_SCHEDULE, []) if self.data else []
            capcodes = self.data.get(DATA_CAPCODES, []) if self.data else []

            if (
                self._first_update
                or self._last_schedule_update is None
                or (now - self._last_schedule_update).total_seconds() >= self._schedule_scan_interval
            ):
                schedule = await self.client.get_user_schedule()
                self._last_schedule_update = now
                _LOGGER.debug("Rooster bijgewerkt")

            if (
                self._first_update
                or self._last_capcodes_update is None
                or (now - self._last_capcodes_update).total_seconds() >= self._schedule_scan_interval
            ):
                capcodes = await self.client.get_user_capcodes()
                self._last_capcodes_update = now
                _LOGGER.debug("Capcodes bijgewerkt: %d gevonden", len(capcodes))

            if self._first_update:
                self._first_update = False

            # Pending-reconciliatie altijd toepassen (ook bij gecachte capcodes)
            capcodes = self._reconcile_capcodes(capcodes, now)

            # Beschikbaarheids-override bijwerken op basis van server-truth
            self._update_override(user_info)

            return {
                DATA_USER_INFO: user_info,
                DATA_ALARM_MESSAGES: alarm_messages,
                DATA_SCHEDULE: schedule,
                DATA_CAPCODES: capcodes,
                DATA_AVAILABILITY_OVERRIDE: self._availability_override,
                DATA_OVERRIDE_CLEARED_AT: self._override_cleared_at,
            }

        except PreComAuthError as err:
            raise UpdateFailed(f"Authenticatiefout: {err}") from err
        except PreComApiError as err:
            raise UpdateFailed(f"API fout: {err}") from err

    def _reconcile_capcodes(self, capcodes: list[dict], now: datetime) -> list[dict]:
        """
        Pas pending-writes toe op de capcode-lijst.

        Server wint altijd, behalve op waarden die wij net zelf schreven,
        totdat de server onze waarde bevestigt of de 30 s timeout verstreken is.
        """
        if not self._pending_capcodes:
            return capcodes

        result = []
        to_delete: list[int] = []

        for capcode in capcodes:
            cid = capcode.get("CapcodeId")
            server_enable = capcode.get("Enable", False)
            pending = self._pending_capcodes.get(cid)

            if pending is None:
                result.append(capcode)
                continue

            if now >= pending.expires_at:
                _LOGGER.warning(
                    "Pre-Com: pending write voor capcode %s verlopen na 30s "
                    "zonder server-bevestiging — server-state %s gevolgd",
                    cid,
                    server_enable,
                )
                to_delete.append(cid)
                result.append(capcode)
            elif server_enable == pending.expected_enable:
                _LOGGER.debug(
                    "Pre-Com: capcode %s server bevestigt %s — pending opgeheven",
                    cid,
                    server_enable,
                )
                to_delete.append(cid)
                result.append(capcode)
            else:
                _LOGGER.debug(
                    "Pre-Com: capcode %s server=%s maar pending=%s — verwachte waarde aanhouden",
                    cid,
                    server_enable,
                    pending.expected_enable,
                )
                result.append({**capcode, "Enable": pending.expected_enable})

        for cid in to_delete:
            del self._pending_capcodes[cid]

        return result

    def _update_override(self, user_info: dict) -> None:
        """
        Vergelijk de pending availability-write met de server-status.

        Regels:
        - Geen pending → override wissen, server wint direct.
        - Pending verlopen (> 30s) → override wissen, server wint, log warning.
        - Server bevestigt verwachte waarde → pending en override wissen.
        - Server wijkt af binnen 30s → override aanhouden (server-lag overbruggen).
        """
        now = datetime.now()
        server_not_available = bool(user_info.get("NotAvailable")) or bool(
            user_info.get("NotAvailalbeScheduled", user_info.get("NotAvailableScheduled"))
        )
        server_available = not server_not_available

        pending = self._pending_availability
        if pending is None:
            self._availability_override = None
            return

        if now >= pending.expires_at:
            _LOGGER.warning(
                "Pre-Com: pending availability write verlopen na 30s "
                "— server=%s gevolgd",
                "beschikbaar" if server_available else "niet-beschikbaar",
            )
            self._pending_availability = None
            self._availability_override = None
            self._override_cleared_at = now
            return

        if server_available == pending.expected_available:
            _LOGGER.debug(
                "Pre-Com: server bevestigt beschikbaarheid=%s — pending opgeheven",
                pending.expected_available,
            )
            self._pending_availability = None
            self._availability_override = None
            self._override_cleared_at = now
        else:
            _LOGGER.debug(
                "Pre-Com: server=%s maar pending=%s — verwachte waarde aanhouden",
                "beschikbaar" if server_available else "niet-beschikbaar",
                pending.expected_available,
            )
            self._availability_override = (pending.expected_available, None)

    # ------------------------------------------------------------------
    # Snelle alarm-only update
    # ------------------------------------------------------------------

    async def _async_update_alarms_only(self) -> dict[str, Any]:
        """Haal alleen alarmberichten op (snelle cyclus)."""
        try:
            alarm_messages = await self.client.get_alarm_messages()
            await self._check_new_alarms(alarm_messages)
            existing = self.data or {}
            self.async_set_updated_data({**existing, DATA_ALARM_MESSAGES: alarm_messages})
        except (PreComAuthError, PreComApiError) as err:
            _LOGGER.debug("Alarm-poll fout (niet kritiek): %s", err)
        return {}

    # ------------------------------------------------------------------
    # Alarm-detectie via poll
    # ------------------------------------------------------------------

    async def _check_new_alarms(self, messages: list[dict]) -> None:
        """Controleer op nieuwe alarmberichten en stuur HA-event."""
        if not messages:
            return

        latest = max(messages, key=lambda m: m.get("MsgInID", m.get("Id", 0)))
        latest_id = latest.get("MsgInID", latest.get("Id", 0))

        if self._last_alarm_id is None:
            self._last_alarm_id = latest_id
            return

        if latest_id > self._last_alarm_id:
            _LOGGER.info("Nieuw Pre-Com alarm via poll: ID %s", latest_id)
            self._last_alarm_id = latest_id
            self.hass.bus.async_fire(
                EVENT_ALARM_RECEIVED,
                {
                    "alarm_id": latest_id,
                    "text": latest.get("Text", latest.get("Msg", "")),
                    "time": latest.get("ReceivedDateTime", latest.get("DateTime", "")),
                    "group": latest.get("GroupName", ""),
                    "type": latest.get("MsgType", ""),
                    "capcode": latest.get("Capcode", ""),
                    "precom_details": latest,
                },
            )

    async def async_start_alarm_coordinator(self) -> None:
        """Start de snelle alarm-coordinator."""
        if self._alarm_coordinator is not None:
            await self._alarm_coordinator.async_config_entry_first_refresh()
