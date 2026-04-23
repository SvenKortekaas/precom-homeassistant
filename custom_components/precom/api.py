"""
Pre-Com API client.

Base URL : https://app.pre-com.nl/
Token    : POST /Token  →  platte tekst (geen JSON)
Auth     : Bearer <token> header

Beschikbaarheid:
  Niet beschikbaar : POST   api/v2/SchedulerAppointment/AddUserSchedulerAppointment
                     params : date=YYYY-MM-DD & from=HH:MM & to=HH:MM
  Beschikbaar      : DELETE api/v2/SchedulerAppointment/DeleteUserSchedulerAppointment
                     params : date=YYYY-MM-DD & from=HH:MM & to=HH:MM

Alarmen / rooster / userinfo via api/User/* (zelfde base URL).

Response-formaten SchedulerAppointment (defensief parsen, beide ondersteund):
  Oud  : {"Date": "YYYY-MM-DD", "From": "HH:MM", "To": "HH:MM", ...}
  Nieuw: {"Start": "YYYY-MM-DDTHH:MM:SS", "Duration": "HH:MM:SS", ...}
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_V1, API_V2, TOKEN_URL

_LOGGER = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset({"authorization", "set-cookie", "cookie", "x-access-token"})


def _scrub(data: Any) -> Any:
    """Verwijder auth-material uit dicts voor logging."""
    if isinstance(data, dict):
        return {
            k: "***" if k.lower() in _SENSITIVE_KEYS else _scrub(v)
            for k, v in data.items()
        }
    return data


class PreComAuthError(Exception):
    """Authenticatie fout."""


class PreComApiError(Exception):
    """API fout."""


class PreComClient:
    """Client voor de Pre-Com API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._token_expires: datetime | None = None
        self._last_not_available: tuple[str, str, str] | None = None

    # ------------------------------------------------------------------ #
    # Authenticatie                                                        #
    # ------------------------------------------------------------------ #

    async def authenticate(self) -> None:
        """Haal een Bearer-token op via OAuth2 password grant."""
        _LOGGER.debug("Pre-Com: authenticeren als '%s'", self._username)
        body = (
            f"grant_type=password"
            f"&username={quote(self._username)}"
            f"&password={quote(self._password)}"
        )
        try:
            t0 = time.monotonic()
            async with self._session.post(
                TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                duration_ms = (time.monotonic() - t0) * 1000
                _LOGGER.debug(
                    "POST %s → HTTP %s in %.0fms", TOKEN_URL, resp.status, duration_ms
                )
                if resp.status == 400 or not resp.ok:
                    raise PreComAuthError(
                        f"Authenticatie mislukt (HTTP {resp.status}): {text[:200]}"
                    )
                token = text.strip()
                if not token:
                    raise PreComAuthError("Lege tokenrespons ontvangen")
                self._access_token = token
                self._token_expires = datetime.utcnow() + timedelta(seconds=3540)
                _LOGGER.info("Pre-Com: authenticatie geslaagd (%d tekens)", len(token))
        except aiohttp.ClientError as err:
            raise PreComApiError(f"Verbindingsfout bij authenticatie: {err}") from err

    async def _ensure_token(self) -> None:
        """Vernieuw het token als het ontbreekt of verlopen is."""
        if self._access_token is None or (
            self._token_expires and datetime.utcnow() >= self._token_expires
        ):
            await self.authenticate()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Basis HTTP-methodes                                                  #
    # ------------------------------------------------------------------ #

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> Any:
        """
        Voer een authenticatied HTTP-request uit.

        Logt method, URL, params, body-preview, response-status, body-preview
        en duration in ms. Authorization-headers worden niet gelogd.
        """
        await self._ensure_token()
        _LOGGER.debug(
            "%s %s | params=%s | body=%s",
            method, url, params,
            str(json_body)[:500] if json_body else None,
        )

        kwargs: dict[str, Any] = {
            "headers": self._auth_headers(),
            "params": params,
            "timeout": aiohttp.ClientTimeout(total=10),
        }
        if json_body is not None:
            kwargs["json"] = json_body

        try:
            t0 = time.monotonic()
            async with self._session.request(method, url, **kwargs) as resp:
                text = await resp.text()
                duration_ms = (time.monotonic() - t0) * 1000

                if resp.status == 401:
                    _LOGGER.warning("Pre-Com: 401 — opnieuw authenticeren")
                    await self.authenticate()
                    kwargs["headers"] = self._auth_headers()
                    t0 = time.monotonic()
                    async with self._session.request(method, url, **kwargs) as resp2:
                        text2 = await resp2.text()
                        duration_ms = (time.monotonic() - t0) * 1000
                        if not resp2.ok:
                            raise PreComApiError(
                                f"HTTP {resp2.status} na herauth: {text2[:300]}"
                            )
                        _LOGGER.debug(
                            "%s %s → HTTP %s in %.0fms (na herauth): %s",
                            method, url, resp2.status, duration_ms, text2[:500],
                        )
                        return self._parse(text2)

                if not resp.ok:
                    raise PreComApiError(f"HTTP {resp.status}: {text[:300]}")

                _LOGGER.debug(
                    "%s %s → HTTP %s in %.0fms: %s",
                    method, url, resp.status, duration_ms, text[:500],
                )
                return self._parse(text)

        except aiohttp.ClientError as err:
            _LOGGER.error("%s %s — verbindingsfout: %s", method, url, err)
            raise PreComApiError(f"Verbindingsfout {method} {url}: {err}") from err

    @staticmethod
    def _parse(text: str) -> Any:
        """Parseer JSON of geef None terug voor lege/null responses."""
        stripped = text.strip() if text else ""
        if not stripped or stripped == "null":
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped

    # ------------------------------------------------------------------ #
    # User info                                                            #
    # ------------------------------------------------------------------ #

    async def get_user_info(self) -> dict:
        """Haal gebruikersinformatie op inclusief NotAvailable status."""
        result = await self._request("GET", f"{API_V1}/User/GetUserInfo")
        return result or {}

    async def get_alarm_messages(
        self, msg_in_id: int = 0, previous_or_next: int = 0
    ) -> list[dict]:
        """Haal alarmberichten op."""
        result = await self._request(
            "GET",
            f"{API_V1}/User/GetAlarmMessages",
            params={
                "msgInID": str(msg_in_id),
                "previousOrNext": str(previous_or_next),
            },
        )
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    async def get_user_schedule(self) -> list[dict]:
        """Haal roosterafspraken op voor de komende 30 dagen."""
        now = datetime.now()
        result = await self._request(
            "GET",
            f"{API_V2}/SchedulerAppointment/GetUserSchedulerAppointments",
            params={
                "from": now.strftime("%Y-%m-%d"),
                "to": (now + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
        )
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------ #
    # Beschikbaarheid                                                      #
    # ------------------------------------------------------------------ #

    async def set_not_available(self, hours: int) -> bool:
        """Meld niet-beschikbaar door een blokkade in de agenda te plaatsen."""
        now = datetime.now()
        end_time = now + timedelta(hours=hours)
        date_str = now.strftime("%Y-%m-%d")
        from_str = now.strftime("%H:%M")
        to_str = end_time.strftime("%H:%M")

        _LOGGER.info(
            "Pre-Com: niet beschikbaar melden — %s van %s tot %s (%d uur)",
            date_str, from_str, to_str, hours,
        )
        await self._request(
            "POST",
            f"{API_V2}/SchedulerAppointment/AddUserSchedulerAppointment",
            params={"date": date_str, "from": from_str, "to": to_str},
        )
        _LOGGER.info(
            "Pre-Com: agenda-blok aangemaakt (%s %s–%s)", date_str, from_str, to_str
        )
        self._last_not_available = (date_str, from_str, to_str)
        return True

    async def get_active_appointments(self) -> list[dict]:
        """
        Haal actieve en toekomstige agenda-afspraken op.

        Ruimere periode (gisteren t/m 7 dagen vooruit) zodat extern geplande
        blokken en blokken die over middernacht lopen ook gevonden worden.
        """
        now = datetime.now()
        from_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        _LOGGER.debug("Pre-Com: agenda ophalen van %s t/m %s", from_date, to_date)
        result = await self._request(
            "GET",
            f"{API_V2}/SchedulerAppointment/GetUserSchedulerAppointments",
            params={"from": from_date, "to": to_date},
        )
        appointments = result if isinstance(result, list) else []
        _LOGGER.debug("Pre-Com: %d afspraak/afspraken gevonden", len(appointments))
        return appointments

    # ------------------------------------------------------------------ #
    # Afspraak-parsing (defensief: oud én nieuw API-formaat)              #
    # ------------------------------------------------------------------ #

    def _parse_start_duration(
        self, appointment: dict
    ) -> tuple[str, str, str] | None:
        """
        Parseer nieuw response-formaat: Start (ISO-datetime) + Duration (HH:MM:SS).

        Voorbeeld: {"Start": "2026-04-22T09:45:00", "Duration": "08:00:00"}
                 → ("2026-04-22", "09:45", "17:45")
        """
        start_val = appointment.get("Start") or appointment.get("start")
        duration_val = appointment.get("Duration") or appointment.get("duration")
        if not start_val or not duration_val:
            _LOGGER.debug(
                "Afspraak (nieuw formaat) onvolledig — velden: %s",
                list(appointment.keys()),
            )
            return None
        try:
            start_dt = datetime.strptime(str(start_val)[:19], "%Y-%m-%dT%H:%M:%S")
            dur_parts = str(duration_val).split(":")
            dur_hours = int(dur_parts[0])
            dur_minutes = int(dur_parts[1])
            end_dt = start_dt + timedelta(hours=dur_hours, minutes=dur_minutes)
            result = (
                start_dt.strftime("%Y-%m-%d"),
                start_dt.strftime("%H:%M"),
                end_dt.strftime("%H:%M"),
            )
            _LOGGER.debug(
                "Afspraak (nieuw formaat) geparsed: %s %s–%s (duration=%s)",
                result[0], result[1], result[2], duration_val,
            )
            return result
        except (ValueError, IndexError, AttributeError) as err:
            _LOGGER.debug(
                "Start+Duration parsen mislukt (%s) voor afspraak: %s", err, appointment
            )
            return None

    def _parse_date_from_to(
        self, appointment: dict
    ) -> tuple[str, str, str] | None:
        """
        Parseer oud response-formaat: Date + From + To.

        Ondersteunt meerdere veldnamenvarianten van de Pre-Com API.
        """
        date_val = (
            appointment.get("Date")
            or appointment.get("date")
            or appointment.get("Datum")
        )
        from_val = (
            appointment.get("From")
            or appointment.get("from")
        )
        to_val = (
            appointment.get("To")
            or appointment.get("to")
            or appointment.get("End")
            or appointment.get("end")
            or appointment.get("Stop")
            or appointment.get("stop")
        )

        if not all([date_val, from_val, to_val]):
            _LOGGER.debug(
                "Afspraak (oud formaat) onvolledig — velden: %s",
                list(appointment.keys()),
            )
            return None

        date_str = str(date_val)[:10]
        from_str = self._normalize_time(str(from_val))
        to_str = self._normalize_time(str(to_val))

        if not from_str or not to_str:
            _LOGGER.debug(
                "Tijdnormalisatie mislukt — from=%s, to=%s", from_val, to_val
            )
            return None

        _LOGGER.debug(
            "Afspraak (oud formaat) geparsed: %s %s–%s", date_str, from_str, to_str
        )
        return date_str, from_str, to_str

    def _extract_appointment_times(
        self, appointment: dict
    ) -> tuple[str, str, str] | None:
        """
        Haal datum, van-tijd en tot-tijd op uit een agenda-afspraak.

        Detecteert het formaat automatisch:
          - 'Duration' aanwezig → nieuw formaat (Start + Duration)
          - Geen 'Duration'     → oud formaat (Date + From + To)
        """
        if "Duration" in appointment or "duration" in appointment:
            return self._parse_start_duration(appointment)
        return self._parse_date_from_to(appointment)

    @staticmethod
    def _normalize_time(value: str) -> str | None:
        """Normaliseer een tijdwaarde naar HH:MM."""
        if "T" in value:
            value = value.split("T")[1]
        for sep in ("+", "Z"):
            if sep in value:
                value = value.split(sep)[0]
        parts = value.strip().split(":")
        if len(parts) >= 2:
            try:
                hh = int(parts[0])
                mm = int(parts[1])
                return f"{hh:02d}:{mm:02d}"
            except ValueError:
                pass
        return None

    def _is_appointment_active_or_future(
        self, date_str: str, from_str: str, to_str: str
    ) -> bool:
        """
        Controleer of een afspraak nu actief is of nog in de toekomst ligt.

        Blokken die over middernacht lopen (eindtijd < begintijd) krijgen
        automatisch een dag extra opgeteld.
        """
        now = datetime.now()
        try:
            start_dt = datetime.strptime(f"{date_str} {from_str}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{date_str} {to_str}", "%Y-%m-%d %H:%M")
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            return end_dt > now
        except ValueError:
            return True  # Bij twijfel meenemen

    async def set_available(self) -> bool:
        """
        Meld beschikbaar door actieve niet-beschikbaar-blokken te verwijderen.

        Stappen:
        1. Haal agenda op (gisteren t/m 7 dagen vooruit)
        2. Parseer elk item — ondersteunt Start+Duration en Date+From+To
        3. Filter op blokken die nu actief zijn of nog komen
        4. Verwijder elk gevonden blok via DELETE
        5. Fallback: lokaal opgeslagen blok als API niets vindt
        6. Verificeer via GetUserInfo dat NotAvailalbeScheduled=false
        """
        _LOGGER.info("Pre-Com: beschikbaar melden — actieve blokken ophalen")

        verwijderd = 0
        api_fout = False

        # ── Stap 1: ophalen ──────────────────────────────────────────────
        try:
            appointments = await self.get_active_appointments()
        except PreComApiError as err:
            _LOGGER.warning(
                "Pre-Com: agenda ophalen mislukt (%s) — terugval op lokaal opgeslagen blok",
                err,
            )
            appointments = []
            api_fout = True

        # ── Stap 2 & 3: parsen en filteren ───────────────────────────────
        te_verwijderen: list[tuple[str, str, str]] = []
        for afspraak in appointments:
            tijden = self._extract_appointment_times(afspraak)
            if tijden is None:
                continue
            date_str, from_str, to_str = tijden
            actief = self._is_appointment_active_or_future(date_str, from_str, to_str)
            _LOGGER.debug(
                "Afspraak %s %s–%s — actief/toekomst: %s",
                date_str, from_str, to_str, actief,
            )
            if actief:
                te_verwijderen.append(tijden)

        _LOGGER.info(
            "Pre-Com: %d blok(ken) geselecteerd voor verwijdering", len(te_verwijderen)
        )

        # ── Stap 4: verwijder elk gevonden blok ──────────────────────────
        for date_str, from_str, to_str in te_verwijderen:
            _LOGGER.info(
                "Pre-Com: DELETE agenda-blok (%s %s–%s)", date_str, from_str, to_str
            )
            try:
                await self._request(
                    "DELETE",
                    f"{API_V2}/SchedulerAppointment/DeleteUserSchedulerAppointment",
                    params={"date": date_str, "from": from_str, "to": to_str},
                )
                verwijderd += 1
                _LOGGER.info(
                    "Pre-Com: blok verwijderd (%s %s–%s)", date_str, from_str, to_str
                )
            except PreComApiError as err:
                _LOGGER.error(
                    "Pre-Com: blok verwijderen mislukt (%s %s–%s): %s",
                    date_str, from_str, to_str, err,
                )

        # ── Stap 5: fallback op lokaal opgeslagen blok ───────────────────
        if verwijderd == 0 and self._last_not_available and not api_fout:
            date_str, from_str, to_str = self._last_not_available
            _LOGGER.info(
                "Pre-Com: geen blokken in API — lokaal opgeslagen blok verwijderen (%s %s–%s)",
                date_str, from_str, to_str,
            )
            try:
                await self._request(
                    "DELETE",
                    f"{API_V2}/SchedulerAppointment/DeleteUserSchedulerAppointment",
                    params={"date": date_str, "from": from_str, "to": to_str},
                )
                verwijderd += 1
                _LOGGER.info("Pre-Com: lokaal blok verwijderd")
            except PreComApiError as err:
                _LOGGER.error("Pre-Com: lokaal blok verwijderen mislukt: %s", err)

        self._last_not_available = None

        if verwijderd == 0:
            _LOGGER.warning(
                "Pre-Com: geen blokken gevonden of verwijderd — "
                "controleer de Pre-Com app of je al beschikbaar was"
            )
            return False

        _LOGGER.info("Pre-Com: %d blok(ken) verwijderd — verificatie starten", verwijderd)

        # ── Stap 6: verificatie ──────────────────────────────────────────
        try:
            user_info = await self.get_user_info()
            scheduled = user_info.get(
                "NotAvailalbeScheduled", user_info.get("NotAvailableScheduled")
            )
            not_available = user_info.get("NotAvailable")
            if scheduled or not_available:
                _LOGGER.warning(
                    "Pre-Com: blok(ken) verwijderd maar server geeft nog "
                    "NotAvailable=%s, NotAvailalbeScheduled=%s — "
                    "Pre-Com heeft de wijziging mogelijk nog niet verwerkt",
                    not_available, scheduled,
                )
            else:
                _LOGGER.info(
                    "Pre-Com: verificatie geslaagd — "
                    "NotAvailable=false, NotAvailalbeScheduled=false"
                )
        except PreComApiError as err:
            _LOGGER.debug("Pre-Com: verificatie GetUserInfo mislukt: %s", err)

        return True

    async def set_availability_for_alarm(self, msg_in_id: int, available: bool) -> None:
        """Reageer op een alarmbericht."""
        _LOGGER.info(
            "Pre-Com: reageren op alarm %d — beschikbaar: %s", msg_in_id, available
        )
        await self._request(
            "POST",
            f"{API_V1}/User/SetAvailabilityForAlarmMessage",
            params={
                "msgInID": str(msg_in_id),
                "available": str(available).lower(),
            },
        )

    async def set_outside_region(self, hours: int) -> None:
        """Alias — gebruik hetzelfde mechanisme als niet-beschikbaar."""
        await self.set_not_available(hours)

    async def get_all_user_groups(self) -> list[dict]:
        """Haal alle groepen op."""
        result = await self._request("GET", f"{API_V2}/Group/GetAllUserGroups")
        return result if isinstance(result, list) else []

    async def get_user_capcodes(self) -> list[dict]:
        """Haal alle capcodes van de gebruiker op."""
        result = await self._request("GET", f"{API_V2}/Capcode/GetUserCapcodes")
        return result if isinstance(result, list) else []

    async def update_user_capcode(self, capcode_id: int, enable: bool) -> None:
        """Schakel een capcode in of uit."""
        _LOGGER.info(
            "Pre-Com: capcode %d %s", capcode_id, "inschakelen" if enable else "uitschakelen"
        )
        await self._request(
            "POST",
            f"{API_V2}/Capcode/UpdateUserCapcode",
            params={"capcode": str(capcode_id), "enable": "true" if enable else "false"},
        )
