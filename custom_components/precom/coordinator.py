"""Pre-Com DataUpdateCoordinator."""
from __future__ import annotations

import logging
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


class PreComCoordinator(DataUpdateCoordinator):
    """
    Coordinator voor Pre-Com data met twee poll-snelheden.

    - Hoofd-poll (standaard 15 s): gebruikersinfo + rooster
    - Snelle poll (standaard 30 s): alarmberichten

    Lokale override:
      De override overbrugt de poll-latency direct na een HA-schrijfactie
      (switch on/off). Zodra de server een status retourneert die strijdig
      is met de override, wordt die direct ingetrokken — de server is altijd
      de gezaghebbende bron.
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

        self._availability_override: tuple[bool, datetime | None] | None = None
        self._override_cleared_at: datetime | None = None

        self._alarm_coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alarms",
            update_interval=timedelta(seconds=alarm_scan_interval),
        )
        self._alarm_coordinator._async_update_data = self._async_update_alarms_only

    # ------------------------------------------------------------------
    # Override property — setter reset cleared_at bij nieuwe override
    # ------------------------------------------------------------------

    @property
    def availability_override(self) -> tuple[bool, datetime | None] | None:
        return self._availability_override

    @availability_override.setter
    def availability_override(self, value: tuple[bool, datetime | None] | None) -> None:
        if value is not None:
            # Nieuwe override gezet → wis eventuele oude "ingetrokken op" tijdstempel
            self._override_cleared_at = None
        self._availability_override = value

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

            # ── Override-beheer ────────────────────────────────────────
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

    def _update_override(self, user_info: dict) -> None:
        """
        Vergelijk de lokale override met de server-status en trek de
        override in als de server een andere richting aangeeft.

        Regels:
        - Override verlopen (tijdstempel verstreken) → altijd verwijderen.
        - Override=niet-beschikbaar, server=beschikbaar → server wint
          (extern beschikbaar gemeld via app/pager).
        - Override=beschikbaar, server=niet-beschikbaar → server wint
          (extern niet-beschikbaar gemeld).
        - Override en server consistent → override handhaven.
        """
        # 1. Verlopen override opruimen
        if self._availability_override is not None:
            _, until = self._availability_override
            if until is not None and datetime.now() > until:
                _LOGGER.debug("Override verlopen — API-waarde actief")
                self._availability_override = None
                self._override_cleared_at = datetime.now()

        # 2. Server-truth check
        if self._availability_override is not None:
            override_available, until = self._availability_override
            server_not_available = bool(user_info.get("NotAvailable")) or bool(
                user_info.get("NotAvailalbeScheduled", user_info.get("NotAvailableScheduled"))
            )

            if not override_available and not server_not_available:
                # Override zegt niet-beschikbaar; server zegt beschikbaar → intrekken
                _LOGGER.debug(
                    "Override actief (niet-beschikbaar) tot %s, server=beschikbaar → "
                    "override ingetrokken (extern beschikbaar gemeld via app/pager)",
                    until.isoformat() if until else "onbeperkt",
                )
                self._availability_override = None
                self._override_cleared_at = datetime.now()

            elif override_available and server_not_available:
                # Override zegt beschikbaar; server zegt niet-beschikbaar → intrekken
                _LOGGER.debug(
                    "Override actief (beschikbaar) tot %s, server=niet-beschikbaar → "
                    "override ingetrokken",
                    until.isoformat() if until else "onbeperkt",
                )
                self._availability_override = None
                self._override_cleared_at = datetime.now()

            else:
                _LOGGER.debug(
                    "Override actief tot %s, server consistent → override gevolgd",
                    until.isoformat() if until else "onbeperkt",
                )

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
