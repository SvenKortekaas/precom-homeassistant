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
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_V1, API_V2, TOKEN_URL

_LOGGER = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------ #
    # Authenticatie                                                        #
    # ------------------------------------------------------------------ #

    async def authenticate(self) -> None:
        """
        Haal een Bearer-token op via OAuth2 password grant.

        De server geeft de token als platte tekst terug (geen JSON-envelop).
        """
        _LOGGER.debug("Pre-Com: authenticeren als '%s'", self._username)
        body = (
            f"grant_type=password"
            f"&username={quote(self._username)}"
            f"&password={quote(self._password)}"
        )
        try:
            async with self._session.post(
                TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                text = await resp.text()
                if resp.status == 400 or not resp.ok:
                    raise PreComAuthError(
                        f"Authenticatie mislukt (HTTP {resp.status}): {text[:200]}"
                    )
                token = text.strip()
                if not token:
                    raise PreComAuthError("Lege tokenrespons ontvangen")
                self._access_token = token
                # Token is 1 uur geldig; vernieuw 60 sec voor verlopen
                self._token_expires = datetime.utcnow() + timedelta(seconds=3540)
                _LOGGER.info(
                    "Pre-Com: authenticatie geslaagd (%d tekens)", len(token)
                )
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

        - Params worden als query-string meegegeven (Pre-Com stijl).
        - Body wordt alleen meegegeven als json_body niet None is.
        - Bij 401 wordt eenmalig opnieuw geauthenticeerd.
        - De response-body wordt gelogd zodat fouten zichtbaar zijn.
        """
        await self._ensure_token()
        _LOGGER.debug("%s %s | params=%s | body=%s", method, url, params, json_body)

        kwargs: dict[str, Any] = {
            "headers": self._auth_headers(),
            "params": params,
            "timeout": aiohttp.ClientTimeout(total=10),
        }
        if json_body is not None:
            kwargs["json"] = json_body

        try:
            async with self._session.request(method, url, **kwargs) as resp:
                text = await resp.text()

                if resp.status == 401:
                    _LOGGER.warning("Pre-Com: 401 — opnieuw authenticeren")
                    await self.authenticate()
                    kwargs["headers"] = self._auth_headers()
                    async with self._session.request(method, url, **kwargs) as resp2:
                        text2 = await resp2.text()
                        if not resp2.ok:
                            raise PreComApiError(
                                f"HTTP {resp2.status} na herauth: {text2[:300]}"
                            )
                        _LOGGER.debug(
                            "%s %s → HTTP %s (na herauth): %s",
                            method, url, resp2.status, text2[:200],
                        )
                        return self._parse(text2)

                if not resp.ok:
                    raise PreComApiError(
                        f"HTTP {resp.status}: {text[:300]}"
                    )

                _LOGGER.debug(
                    "%s %s → HTTP %s: %s",
                    method, url, resp.status, text[:200],
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
            return stripped  # Geef ruwe tekst terug voor onverwachte responses

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
        now    = datetime.now()
        result = await self._request(
            "GET",
            f"{API_V2}/SchedulerAppointment/GetUserSchedulerAppointments",
            params={
                "from": now.strftime("%Y-%m-%d"),
                "to":   (now + timedelta(days=30)).strftime("%Y-%m-%d"),
            },
        )
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------ #
    # Beschikbaarheid                                                      #
    # ------------------------------------------------------------------ #

    async def set_not_available(self, hours: int) -> bool:
        """
        Meld niet-beschikbaar door een blokkade in de agenda te plaatsen.

        POST api/v2/SchedulerAppointment/AddUserSchedulerAppointment
          ?date=YYYY-MM-DD
          &from=HH:MM
          &to=HH:MM

        Tijdformaat is HH:MM (geen seconden).
        """
        now      = datetime.now()
        end_time = now + timedelta(hours=hours)

        date_str = now.strftime("%Y-%m-%d")
        from_str = now.strftime("%H:%M")
        to_str   = end_time.strftime("%H:%M")

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
        # Sla datum/tijd op zodat we het blok later kunnen verwijderen
        self._last_not_available: tuple[str, str, str] | None = (
            date_str, from_str, to_str
        )
        return True

    async def get_today_appointments(self) -> list[dict]:
        """
        Haal de agenda-afspraken van vandaag op.

        GET api/v2/SchedulerAppointment/GetUserSchedulerAppointments
          ?from=YYYY-MM-DD&to=YYYY-MM-DD

        Geeft een lijst van afspraken terug voor vandaag.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        _LOGGER.debug("Pre-Com: agenda ophalen voor %s", today)
        result = await self._request(
            "GET",
            f"{API_V2}/SchedulerAppointment/GetUserSchedulerAppointments",
            params={"from": today, "to": today},
        )
        appointments = result if isinstance(result, list) else []
        _LOGGER.debug(
            "Pre-Com: %d afspraak/afspraken gevonden voor vandaag", len(appointments)
        )
        return appointments

    def _extract_appointment_times(
        self, appointment: dict
    ) -> tuple[str, str, str] | None:
        """
        Haal datum, van-tijd en tot-tijd op uit een agenda-afspraak.

        Pre-Com kan verschillende veldnamen gebruiken:
          date/Date/datum, from/From/Start/start, to/To/End/end/Stop/stop
        Tijdformaat wordt genormaliseerd naar HH:MM.
        """
        # Datum
        date_val = (
            appointment.get("Date")
            or appointment.get("date")
            or appointment.get("Datum")
        )
        # Van-tijd
        from_val = (
            appointment.get("From")
            or appointment.get("from")
            or appointment.get("Start")
            or appointment.get("start")
        )
        # Tot-tijd
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
                "Afspraak onvolledig — velden: %s", list(appointment.keys())
            )
            return None

        # Normaliseer datum naar YYYY-MM-DD (knip tijdzone af als aanwezig)
        date_str = str(date_val)[:10]

        # Normaliseer tijden naar HH:MM
        from_str = self._normalize_time(str(from_val))
        to_str   = self._normalize_time(str(to_val))

        if not from_str or not to_str:
            return None

        return date_str, from_str, to_str

    @staticmethod
    def _normalize_time(value: str) -> str | None:
        """
        Normaliseer een tijdwaarde naar HH:MM.

        Accepteert: HH:MM, HH:MM:SS, volledige ISO-datetime strings.
        """
        # Haal tijdgedeelte op uit ISO-datetime (2026-03-17T13:42:00 → 13:42:00)
        if "T" in value:
            value = value.split("T")[1]
        # Verwijder tijdzone-suffix (+01:00 / Z)
        for sep in ("+", "Z"):
            if sep in value:
                value = value.split(sep)[0]
        # Neem alleen HH:MM
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

        Geeft True als de afspraak vandaag is én eindigt na het huidige moment.
        """
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        if date_str != today:
            return False

        try:
            end_dt = datetime.strptime(f"{date_str} {to_str}", "%Y-%m-%d %H:%M")
            return end_dt > now
        except ValueError:
            return True  # Bij twijfel meenemen

    async def set_available(self) -> bool:
        """
        Meld beschikbaar door actieve niet-beschikbaar-blokken te verwijderen.

        Werkwijze:
        1. Haal de agenda-afspraken van vandaag op via de API
        2. Filter op blokken die nu actief zijn of nog komen
        3. Verwijder elk gevonden blok met de exacte tijden uit de API-response
        4. Fallback: gebruik lokaal opgeslagen tijden als de API geen blokken geeft
        """
        _LOGGER.info("Pre-Com: beschikbaar melden — agenda ophalen voor tijden")

        verwijderd = 0
        api_fout   = False

        # ── Stap 1: ophalen ──────────────────────────────────────────────
        try:
            appointments = await self.get_today_appointments()
        except PreComApiError as err:
            _LOGGER.warning(
                "Pre-Com: agenda ophalen mislukt (%s) — terugval op lokaal opgeslagen blok",
                err,
            )
            appointments = []
            api_fout = True

        # ── Stap 2: filter op actieve/toekomstige blokken ────────────────
        te_verwijderen: list[tuple[str, str, str]] = []

        for afspraak in appointments:
            tijden = self._extract_appointment_times(afspraak)
            if tijden is None:
                continue
            date_str, from_str, to_str = tijden
            if self._is_appointment_active_or_future(date_str, from_str, to_str):
                te_verwijderen.append(tijden)
                _LOGGER.debug(
                    "Pre-Com: blok gevonden om te verwijderen: %s %s–%s",
                    date_str, from_str, to_str,
                )

        # ── Stap 3: verwijder elk gevonden blok ──────────────────────────
        for date_str, from_str, to_str in te_verwijderen:
            _LOGGER.info(
                "Pre-Com: agenda-blok verwijderen (%s %s–%s)",
                date_str, from_str, to_str,
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

        # ── Stap 4: fallback op lokaal opgeslagen blok ───────────────────
        last = getattr(self, "_last_not_available", None)
        if verwijderd == 0 and last and not api_fout:
            date_str, from_str, to_str = last
            _LOGGER.info(
                "Pre-Com: geen actieve blokken in API gevonden — "
                "lokaal opgeslagen blok verwijderen (%s %s–%s)",
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

        # Wis het lokaal opgeslagen blok altijd na een beschikbaar-melding
        self._last_not_available: tuple[str, str, str] | None = None

        if verwijderd > 0:
            _LOGGER.info(
                "Pre-Com: %d blok(ken) verwijderd — beschikbaar gemeld", verwijderd
            )
        else:
            _LOGGER.warning(
                "Pre-Com: geen blokken gevonden of verwijderd — "
                "controleer de Pre-Com app of je al beschikbaar was"
            )

        return verwijderd > 0

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
