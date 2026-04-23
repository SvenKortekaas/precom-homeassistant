"""Tests voor capcodes: helpers, API-client en switch-entiteit."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestCleanDescription:

    def test_strips_trailing_crlf(self) -> None:
        from custom_components.precom.helpers import _clean_description
        assert _clean_description("Kennemerland - Uitgeest\r\n") == "Kennemerland - Uitgeest"

    def test_collapses_double_spaces(self) -> None:
        from custom_components.precom.helpers import _clean_description
        assert _clean_description("Kennemerland  OvD Noord") == "Kennemerland OvD Noord"

    def test_strips_and_collapses_combined(self) -> None:
        from custom_components.precom.helpers import _clean_description
        assert _clean_description("  Foo  Bar  \r\n") == "Foo Bar"

    def test_empty_string(self) -> None:
        from custom_components.precom.helpers import _clean_description
        assert _clean_description("") == ""

    def test_only_whitespace(self) -> None:
        from custom_components.precom.helpers import _clean_description
        assert _clean_description("   \r\n  ") == ""


# ── API: get_user_capcodes ─────────────────────────────────────────────────────

class TestGetUserCapcodes:

    def _client(self):
        from custom_components.precom.api import PreComClient
        return PreComClient(session=MagicMock(), username="u", password="p")

    @pytest.mark.asyncio
    async def test_empty_response(self) -> None:
        client = self._client()
        client._request = AsyncMock(return_value=[])
        assert await client.get_user_capcodes() == []

    @pytest.mark.asyncio
    async def test_single_capcode(self) -> None:
        client = self._client()
        client._request = AsyncMock(return_value=[
            {"CapcodeId": 106530, "Enable": False, "Description": "Test"},
        ])
        result = await client.get_user_capcodes()
        assert len(result) == 1
        assert result[0]["CapcodeId"] == 106530

    @pytest.mark.asyncio
    async def test_multiple_capcodes(self) -> None:
        client = self._client()
        client._request = AsyncMock(return_value=[
            {"CapcodeId": 1, "Enable": True,  "Description": "A"},
            {"CapcodeId": 2, "Enable": False, "Description": "B"},
            {"CapcodeId": 3, "Enable": True,  "Description": "C"},
        ])
        result = await client.get_user_capcodes()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_non_list_returns_empty(self) -> None:
        client = self._client()
        client._request = AsyncMock(return_value=None)
        assert await client.get_user_capcodes() == []


# ── API: update_user_capcode ───────────────────────────────────────────────────

class TestUpdateUserCapcode:

    def _client(self):
        from custom_components.precom.api import PreComClient
        return PreComClient(session=MagicMock(), username="u", password="p")

    @pytest.mark.asyncio
    async def test_enable_true_uses_lowercase(self) -> None:
        from custom_components.precom.const import API_V2
        client = self._client()
        client._request = AsyncMock(return_value=None)
        await client.update_user_capcode(106530, True)
        client._request.assert_called_once_with(
            "POST",
            f"{API_V2}/Capcode/UpdateUserCapcode",
            params={"capcode": "106530", "enable": "true"},
        )

    @pytest.mark.asyncio
    async def test_enable_false_uses_lowercase(self) -> None:
        from custom_components.precom.const import API_V2
        client = self._client()
        client._request = AsyncMock(return_value=None)
        await client.update_user_capcode(107711, False)
        client._request.assert_called_once_with(
            "POST",
            f"{API_V2}/Capcode/UpdateUserCapcode",
            params={"capcode": "107711", "enable": "false"},
        )

    @pytest.mark.asyncio
    async def test_uses_post_method(self) -> None:
        client = self._client()
        client._request = AsyncMock(return_value=None)
        await client.update_user_capcode(1, True)
        method = client._request.call_args[0][0]
        assert method == "POST"


# ── Switch-entiteit ────────────────────────────────────────────────────────────

def _make_coordinator(capcodes, user_id=42):
    coord = MagicMock()
    coord.data = {"capcodes": capcodes}
    coord.user_id = user_id
    coord.last_update_success = True
    return coord


def _make_entry(entry_id="test_entry"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "Pre-Com Test"
    return entry


class TestPreComCapcodeSwitchProperties:

    def test_unique_id_uses_user_id(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([], user_id=99)
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "Test")
        assert switch._attr_unique_id == "precom_99_capcode_106530"

    def test_unique_id_falls_back_to_entry_id(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([], user_id=None)
        entry = _make_entry("fallback_entry")
        switch = PreComCapcodeSwitch(coord, entry, 106530, "Test")
        assert "fallback_entry" in switch._attr_unique_id

    def test_name_includes_description(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        switch = PreComCapcodeSwitch(_make_coordinator([]), _make_entry(), 106530, "OvD Noord")
        assert switch._attr_name == "Pre-Com Capcode OvD Noord"

    def test_name_falls_back_to_id(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        switch = PreComCapcodeSwitch(_make_coordinator([]), _make_entry(), 106530, "")
        assert "106530" in switch._attr_name

    def test_get_capcode_returns_correct_item(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        capcodes = [
            {"CapcodeId": 106530, "Enable": False, "Description": "A"},
            {"CapcodeId": 107711, "Enable": True,  "Description": "B"},
        ]
        coord = _make_coordinator(capcodes)
        switch = PreComCapcodeSwitch(coord, _make_entry(), 107711, "B")
        result = switch._get_capcode()
        assert result is not None
        assert result["CapcodeId"] == 107711
        assert result["Enable"] is True

    def test_get_capcode_returns_none_when_missing(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        switch = PreComCapcodeSwitch(_make_coordinator([]), _make_entry(), 106530, "T")
        assert switch._get_capcode() is None

    def test_handle_update_sets_attr_is_on(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        switch._handle_coordinator_update()
        assert switch._attr_is_on is True

    def test_handle_update_tracks_unavailable_transition(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        switch._was_available = True
        coord.data = {"capcodes": []}
        switch._handle_coordinator_update()
        assert switch._was_available is False

    def test_handle_update_does_not_change_attr_is_on_when_capcode_missing(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch._attr_is_on = True
        switch.async_write_ha_state = MagicMock()
        coord.data = {"capcodes": []}
        switch._handle_coordinator_update()
        assert switch._attr_is_on is True


class TestPreComCapcodeSwitchActions:

    @pytest.mark.asyncio
    async def test_turn_on_calls_api(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": False, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "Test")
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_on()
        coord.client.update_user_capcode.assert_called_once_with(106530, True)
        assert switch._attr_is_on is True
        coord.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_calls_api(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "Test")
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_off()
        coord.client.update_user_capcode.assert_called_once_with(106530, False)
        assert switch._attr_is_on is False
        coord.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_pending_called_after_successful_turn_on(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": False, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_on()
        coord.mark_capcode_pending.assert_called_once_with(106530, True)

    @pytest.mark.asyncio
    async def test_mark_pending_called_after_successful_turn_off(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_off()
        coord.mark_capcode_pending.assert_called_once_with(106530, False)

    @pytest.mark.asyncio
    async def test_mark_pending_not_called_on_api_failure(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        from custom_components.precom.api import PreComApiError
        import homeassistant.exceptions as ha_exc
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": False, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock(side_effect=PreComApiError("fout"))
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        with pytest.raises(ha_exc.HomeAssistantError):
            await switch.async_turn_on()
        coord.mark_capcode_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_on_raises_on_api_error(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        from custom_components.precom.api import PreComApiError
        import homeassistant.exceptions as ha_exc
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": False, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock(side_effect=PreComApiError("fout"))
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch.async_write_ha_state = MagicMock()
        with pytest.raises(ha_exc.HomeAssistantError):
            await switch.async_turn_on()

    @pytest.mark.asyncio
    async def test_state_not_changed_on_api_failure(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        from custom_components.precom.api import PreComApiError
        import homeassistant.exceptions as ha_exc
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": False, "Description": "T"}])
        coord.client = MagicMock()
        coord.client.update_user_capcode = AsyncMock(side_effect=PreComApiError("fout"))
        coord.mark_capcode_pending = MagicMock()
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        switch._attr_is_on = False
        switch.async_write_ha_state = MagicMock()
        with pytest.raises(ha_exc.HomeAssistantError):
            await switch.async_turn_on()
        assert switch._attr_is_on is False


# ── Dynamische toevoeging/verwijdering ────────────────────────────────────────

class TestDynamicCapcodes:

    def _setup(self, initial_capcodes):
        from custom_components.precom.switch import PreComCapcodeSwitch
        from custom_components.precom.helpers import _clean_description
        from custom_components.precom.const import DATA_CAPCODES

        coord = _make_coordinator(initial_capcodes)
        entry = _make_entry()
        known_ids: set = set()
        added = []

        def _add_new_capcodes():
            capcodes = coord.data.get(DATA_CAPCODES, []) if coord.data else []
            new = []
            for capcode in capcodes:
                cid = capcode.get("CapcodeId")
                if cid is None:
                    continue
                if cid not in known_ids:
                    known_ids.add(cid)
                    desc = _clean_description(capcode.get("Description", ""))
                    new.append(PreComCapcodeSwitch(coord, entry, cid, desc))
            if new:
                added.extend(new)

        return coord, _add_new_capcodes, added

    def test_initial_capcodes_create_entities(self) -> None:
        _, add_fn, added = self._setup([
            {"CapcodeId": 106530, "Enable": False, "Description": "A"},
            {"CapcodeId": 107711, "Enable": True,  "Description": "B"},
        ])
        add_fn()
        assert len(added) == 2

    def test_no_entities_for_empty_response(self) -> None:
        _, add_fn, added = self._setup([])
        add_fn()
        assert len(added) == 0

    def test_second_call_does_not_duplicate(self) -> None:
        _, add_fn, added = self._setup([
            {"CapcodeId": 106530, "Enable": False, "Description": "A"},
        ])
        add_fn()
        add_fn()
        assert len(added) == 1

    def test_new_capcode_in_refresh_creates_entity(self) -> None:
        from custom_components.precom.const import DATA_CAPCODES
        coord, add_fn, added = self._setup([
            {"CapcodeId": 106530, "Enable": False, "Description": "A"},
        ])
        add_fn()
        assert len(added) == 1
        coord.data = {DATA_CAPCODES: [
            {"CapcodeId": 106530, "Enable": False, "Description": "A"},
            {"CapcodeId": 999999, "Enable": True,  "Description": "Nieuw"},
        ]}
        add_fn()
        assert len(added) == 2
        assert any(e._capcode_id == 999999 for e in added)

    def test_removed_capcode_makes_get_capcode_return_none(self) -> None:
        from custom_components.precom.switch import PreComCapcodeSwitch
        from custom_components.precom.const import DATA_CAPCODES
        coord = _make_coordinator([{"CapcodeId": 106530, "Enable": True, "Description": "T"}])
        switch = PreComCapcodeSwitch(coord, _make_entry(), 106530, "T")
        assert switch._get_capcode() is not None
        coord.data = {DATA_CAPCODES: []}
        assert switch._get_capcode() is None

    def test_capcode_without_id_is_skipped(self) -> None:
        _, add_fn, added = self._setup([
            {"Enable": True, "Description": "Geen ID"},
            {"CapcodeId": 106530, "Enable": False, "Description": "Wel ID"},
        ])
        add_fn()
        assert len(added) == 1


# ── Description-sanitatie in sensor ───────────────────────────────────────────

class TestSensorAttributes:

    def test_omschrijving_is_cleaned(self) -> None:
        from custom_components.precom.sensor import PreComCapcodesSensor
        coord = _make_coordinator([
            {"CapcodeId": 107711, "Enable": False, "Description": "Kennemerland - Uitgeest\r\n"},
            {"CapcodeId": 106530, "Enable": True,  "Description": "Kennemerland  OvD Noord"},
        ])
        sensor = PreComCapcodesSensor(coord, _make_entry())
        attrs = sensor.extra_state_attributes
        by_id = {c["id"]: c["omschrijving"] for c in attrs["capcodes"]}
        assert by_id[107711] == "Kennemerland - Uitgeest"
        assert by_id[106530] == "Kennemerland OvD Noord"

    def test_native_value_is_total_count(self) -> None:
        from custom_components.precom.sensor import PreComCapcodesSensor
        coord = _make_coordinator([
            {"CapcodeId": 1, "Enable": True,  "Description": "A"},
            {"CapcodeId": 2, "Enable": False, "Description": "B"},
            {"CapcodeId": 3, "Enable": True,  "Description": "C"},
        ])
        sensor = PreComCapcodesSensor(coord, _make_entry())
        assert sensor.native_value == 3

    def test_aantal_actief_in_attributes(self) -> None:
        from custom_components.precom.sensor import PreComCapcodesSensor
        coord = _make_coordinator([
            {"CapcodeId": 1, "Enable": True,  "Description": "A"},
            {"CapcodeId": 2, "Enable": False, "Description": "B"},
            {"CapcodeId": 3, "Enable": True,  "Description": "C"},
        ])
        sensor = PreComCapcodesSensor(coord, _make_entry())
        attrs = sensor.extra_state_attributes
        assert attrs["totaal"] == 3
        assert attrs["aantal_actief"] == 2


# ── Pending-write reconciliatie ────────────────────────────────────────────────

def _make_real_coordinator():
    """Maak een echte PreComCoordinator met een mock client."""
    from custom_components.precom.coordinator import PreComCoordinator
    client = MagicMock()
    return PreComCoordinator(hass=None, client=client)


class TestCapcodePendingReconciliation:

    def test_no_pending_returns_server_value(self) -> None:
        coord = _make_real_coordinator()
        from datetime import datetime
        capcodes = [{"CapcodeId": 1, "Enable": False}]
        result = coord._reconcile_capcodes(capcodes, datetime.now())
        assert result[0]["Enable"] is False

    def test_pending_not_yet_confirmed_holds_expected(self) -> None:
        from datetime import datetime, timedelta
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(1, True)
        # Server zegt nog False — verwachte waarde moet aanhouden
        capcodes = [{"CapcodeId": 1, "Enable": False}]
        result = coord._reconcile_capcodes(capcodes, datetime.now())
        assert result[0]["Enable"] is True

    def test_pending_confirmed_by_server_clears_pending(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(1, True)
        # Server bevestigt True — pending moet verdwijnen
        capcodes = [{"CapcodeId": 1, "Enable": True}]
        coord._reconcile_capcodes(capcodes, datetime.now())
        assert 1 not in coord._pending_capcodes

    def test_pending_not_confirmed_keeps_pending(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(1, True)
        capcodes = [{"CapcodeId": 1, "Enable": False}]
        coord._reconcile_capcodes(capcodes, datetime.now())
        assert 1 in coord._pending_capcodes

    def test_expired_pending_server_wins(self) -> None:
        from datetime import datetime, timedelta
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(1, True)
        capcodes = [{"CapcodeId": 1, "Enable": False}]
        # Simuleer expired: now = expires_at + 1s
        future = coord._pending_capcodes[1].expires_at + timedelta(seconds=1)
        result = coord._reconcile_capcodes(capcodes, future)
        assert result[0]["Enable"] is False
        assert 1 not in coord._pending_capcodes

    def test_capcode_without_pending_not_affected(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(99, True)
        capcodes = [{"CapcodeId": 1, "Enable": False}]
        result = coord._reconcile_capcodes(capcodes, datetime.now())
        assert result[0]["Enable"] is False

    def test_multiple_capcodes_only_pending_one_affected(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_capcode_pending(1, True)
        capcodes = [
            {"CapcodeId": 1, "Enable": False},
            {"CapcodeId": 2, "Enable": False},
        ]
        result = coord._reconcile_capcodes(capcodes, datetime.now())
        by_id = {c["CapcodeId"]: c["Enable"] for c in result}
        assert by_id[1] is True   # pending toegepast
        assert by_id[2] is False  # ongewijzigd


class TestAvailabilityPendingReconciliation:

    def test_no_pending_clears_override(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord._availability_override = (False, None)
        coord._update_override({"NotAvailable": False})
        assert coord._availability_override is None

    def test_pending_not_confirmed_holds_override(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_availability_pending(False)
        # Server zegt beschikbaar — pending houdt niet-beschikbaar vast
        coord._update_override({"NotAvailable": False, "NotAvailalbeScheduled": False})
        assert coord._availability_override == (False, None)
        assert coord._pending_availability is not None

    def test_pending_confirmed_by_server_clears_pending(self) -> None:
        from datetime import datetime
        coord = _make_real_coordinator()
        coord.mark_availability_pending(False)
        # Server bevestigt niet-beschikbaar
        coord._update_override({"NotAvailable": True})
        assert coord._pending_availability is None
        assert coord._availability_override is None

    def test_expired_pending_server_wins(self) -> None:
        from datetime import datetime, timedelta
        coord = _make_real_coordinator()
        coord.mark_availability_pending(False)
        # Forceer expired pending
        coord._pending_availability.expires_at = datetime.now() - timedelta(seconds=1)
        coord._update_override({"NotAvailable": False})
        assert coord._pending_availability is None
        assert coord._availability_override is None

    def test_mark_availability_pending_sets_override(self) -> None:
        coord = _make_real_coordinator()
        coord.mark_availability_pending(False)
        assert coord._availability_override == (False, None)
        assert coord._pending_availability is not None
        assert coord._pending_availability.expected_available is False
