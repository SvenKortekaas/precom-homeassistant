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

    - Trage poll (standaard 5 min): gebruikersinfo + rooster
    - Snelle poll (standaard 30 sec): alarmberichten
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: PreComClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        alarm_scan_interval: int = DEFAULT_ALARM_SCAN_INTERVAL,
        schedule_scan_interval: int = DEFAULT_SCHEDULE_SCAN_INTERVAL,
    ) -> None:
        """Initialiseer de coordinator."""
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
        self._first_update = True
        self.user_id: int | None = None
        # Lokale beschikbaarheidsoverride: (available: bool, until: datetime | None)
        self.availability_override: tuple[bool, datetime | None] | None = None

        # Snelle alarm-coordinator
        self._alarm_coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alarms",
            update_interval=timedelta(seconds=alarm_scan_interval),
        )
        self._alarm_coordinator._async_update_data = self._async_update_alarms_only

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

            # Update schedule only if enough time has passed or it's the first update
            now = datetime.now()
            schedule = self.data.get(DATA_SCHEDULE, []) if self.data else []
            if (
                self._first_update
                or self._last_schedule_update is None
                or (now - self._last_schedule_update).total_seconds() >= self._schedule_scan_interval
            ):
                schedule = await self.client.get_user_schedule()
                self._last_schedule_update = now
                _LOGGER.debug("Rooster bijgewerkt")

            if self._first_update:
                self._first_update = False

            # Verwijder een verlopen override automatisch
            if self.availability_override is not None:
                _, until = self.availability_override
                if until is not None and datetime.now() > until:
                    _LOGGER.debug("Beschikbaarheidsoverride verlopen — API-waarde actief")
                    self.availability_override = None

            return {
                DATA_USER_INFO: user_info,
                DATA_ALARM_MESSAGES: alarm_messages,
                DATA_SCHEDULE: schedule,
                DATA_AVAILABILITY_OVERRIDE: self.availability_override,
            }

        except PreComAuthError as err:
            raise UpdateFailed(f"Authenticatiefout: {err}") from err
        except PreComApiError as err:
            raise UpdateFailed(f"API fout: {err}") from err

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
