"""Smoke-tests voor Pre-Com API appointment-parsing (beide response-formaten)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.precom.api import PreComClient, _scrub


@pytest.fixture
def client() -> PreComClient:
    return PreComClient(session=MagicMock(), username="test@example.com", password="test")


# ---------------------------------------------------------------------------
# _extract_appointment_times — formaatdetectie
# ---------------------------------------------------------------------------

class TestExtractAppointmentTimes:

    # ── Nieuw formaat: Start + Duration ────────────────────────────────

    def test_new_format_basic(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"Start": "2026-04-22T09:45:00", "Duration": "08:00:00"}
        )
        assert result == ("2026-04-22", "09:45", "17:45")

    def test_new_format_with_minutes_in_duration(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"Start": "2026-04-22T07:30:00", "Duration": "01:15:00"}
        )
        assert result == ("2026-04-22", "07:30", "08:45")

    def test_new_format_crosses_midnight(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"Start": "2026-04-22T22:00:00", "Duration": "03:00:00"}
        )
        # 22:00 + 3h = 01:00 volgende dag
        assert result == ("2026-04-22", "22:00", "01:00")

    def test_new_format_missing_start(self, client: PreComClient) -> None:
        assert client._extract_appointment_times({"Duration": "08:00:00"}) is None

    def test_new_format_lowercase_keys(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"start": "2026-04-22T09:45:00", "duration": "02:00:00"}
        )
        assert result == ("2026-04-22", "09:45", "11:45")

    # ── Oud formaat: Date + From + To ──────────────────────────────────

    def test_old_format_basic(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"Date": "2026-04-22", "From": "09:45", "To": "17:45"}
        )
        assert result == ("2026-04-22", "09:45", "17:45")

    def test_old_format_with_seconds(self, client: PreComClient) -> None:
        result = client._extract_appointment_times(
            {"Date": "2026-04-22", "From": "09:45:00", "To": "17:45:00"}
        )
        assert result == ("2026-04-22", "09:45", "17:45")

    def test_old_format_iso_datetime_fields(self, client: PreComClient) -> None:
        result = client._extract_appointment_times({
            "Date": "2026-04-22T00:00:00",
            "From": "2026-04-22T09:45:00",
            "To": "2026-04-22T17:45:00",
        })
        assert result == ("2026-04-22", "09:45", "17:45")

    def test_old_format_missing_to(self, client: PreComClient) -> None:
        assert client._extract_appointment_times(
            {"Date": "2026-04-22", "From": "09:45"}
        ) is None

    def test_old_format_missing_date(self, client: PreComClient) -> None:
        assert client._extract_appointment_times(
            {"From": "09:45", "To": "17:45"}
        ) is None

    # ── Leeg / onbekend ────────────────────────────────────────────────

    def test_empty_dict(self, client: PreComClient) -> None:
        assert client._extract_appointment_times({}) is None

    def test_unknown_keys_only(self, client: PreComClient) -> None:
        assert client._extract_appointment_times({"foo": "bar"}) is None


# ---------------------------------------------------------------------------
# _is_appointment_active_or_future
# ---------------------------------------------------------------------------

class TestIsAppointmentActiveOrFuture:

    def test_active_now(self, client: PreComClient) -> None:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        from_str = (now - timedelta(hours=1)).strftime("%H:%M")
        to_str   = (now + timedelta(hours=1)).strftime("%H:%M")
        assert client._is_appointment_active_or_future(date_str, from_str, to_str) is True

    def test_ended_in_past(self, client: PreComClient) -> None:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        from_str = (now - timedelta(hours=2)).strftime("%H:%M")
        to_str   = (now - timedelta(hours=1)).strftime("%H:%M")
        assert client._is_appointment_active_or_future(date_str, from_str, to_str) is False

    def test_starts_in_future(self, client: PreComClient) -> None:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        from_str = (now + timedelta(hours=1)).strftime("%H:%M")
        to_str   = (now + timedelta(hours=3)).strftime("%H:%M")
        assert client._is_appointment_active_or_future(date_str, from_str, to_str) is True

    def test_midnight_crossing_treated_as_future(self, client: PreComClient) -> None:
        # to < from → end_dt krijgt +1 dag → eindigt morgen 01:00 → nog actief
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        assert client._is_appointment_active_or_future(date_str, "22:00", "01:00") is True


# ---------------------------------------------------------------------------
# _scrub — auth-material verwijderen
# ---------------------------------------------------------------------------

class TestScrub:

    def test_scrubs_authorization(self) -> None:
        result = _scrub({"Authorization": "Bearer secret123", "Accept": "application/json"})
        assert result["Authorization"] == "***"
        assert result["Accept"] == "application/json"

    def test_scrubs_case_insensitive(self) -> None:
        assert _scrub({"authorization": "token"})["authorization"] == "***"
        assert _scrub({"AUTHORIZATION": "token"})["AUTHORIZATION"] == "***"

    def test_scrubs_set_cookie(self) -> None:
        assert _scrub({"set-cookie": "session=abc"})["set-cookie"] == "***"

    def test_passthrough_non_sensitive(self) -> None:
        data = {"Content-Type": "application/json", "X-Custom": "value"}
        assert _scrub(data) == data

    def test_non_dict_passthrough(self) -> None:
        assert _scrub("plain string") == "plain string"
        assert _scrub(42) == 42
