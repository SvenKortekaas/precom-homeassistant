"""Pre-Com integratie voor Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .api import PreComClient
from .const import (
    CONF_ALARM_SCAN_INTERVAL,
    CONF_DEBUG_LOGGING,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_SCAN_INTERVAL,
    DEFAULT_ALARM_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import PreComCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

SERVICE_SET_AVAILABLE      = "set_available"
SERVICE_RESPOND_TO_ALARM   = "respond_to_alarm"
SERVICE_SET_OUTSIDE_REGION = "set_outside_region"

SCHEMA_SET_AVAILABLE = vol.Schema({
    vol.Required("available"): cv.boolean,
    vol.Optional("hours", default=8): vol.All(cv.positive_int, vol.Range(min=1, max=168)),
})
SCHEMA_RESPOND_TO_ALARM = vol.Schema({
    vol.Required("alarm_id"): cv.positive_int,
    vol.Required("available"): cv.boolean,
})
SCHEMA_SET_OUTSIDE_REGION = vol.Schema({
    vol.Required("hours"): vol.All(cv.positive_int, vol.Range(min=1, max=168)),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stel de Pre-Com integratie in vanuit een config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    alarm_scan_interval = entry.options.get(
        CONF_ALARM_SCAN_INTERVAL,
        entry.data.get(CONF_ALARM_SCAN_INTERVAL, DEFAULT_ALARM_SCAN_INTERVAL),
    )
    schedule_scan_interval = entry.options.get(
        CONF_SCHEDULE_SCAN_INTERVAL,
        entry.data.get(CONF_SCHEDULE_SCAN_INTERVAL, DEFAULT_SCHEDULE_SCAN_INTERVAL),
    )

    debug_logging = entry.options.get(
        CONF_DEBUG_LOGGING,
        entry.data.get(CONF_DEBUG_LOGGING, True),
    )
    if debug_logging:
        logging.getLogger("custom_components.precom").setLevel(logging.DEBUG)
    else:
        logging.getLogger("custom_components.precom").setLevel(logging.INFO)

    session = async_get_clientsession(hass)
    client  = PreComClient(session, username, password)
    await client.authenticate()

    coordinator = PreComCoordinator(
        hass, client,
        scan_interval=scan_interval,
        alarm_scan_interval=alarm_scan_interval,
        schedule_scan_interval=schedule_scan_interval,
    )
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start_alarm_coordinator()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Services registreren (eenmalig)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_AVAILABLE):

        async def handle_set_available(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                if isinstance(coord, PreComCoordinator):
                    if call.data["available"]:
                        await coord.client.set_available()
                        coord.mark_availability_pending(True)
                    else:
                        hours = call.data.get("hours", 8)
                        await coord.client.set_not_available(hours)
                        coord.mark_availability_pending(False)
                    await coord.async_request_refresh()

        async def handle_respond_to_alarm(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                if isinstance(coord, PreComCoordinator):
                    await coord.client.set_availability_for_alarm(
                        call.data["alarm_id"], call.data["available"]
                    )
                    await coord.async_request_refresh()

        async def handle_set_outside_region(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                if isinstance(coord, PreComCoordinator):
                    await coord.client.set_outside_region(call.data["hours"])
                    await coord.async_request_refresh()

        hass.services.async_register(
            DOMAIN, SERVICE_SET_AVAILABLE, handle_set_available, SCHEMA_SET_AVAILABLE
        )
        hass.services.async_register(
            DOMAIN, SERVICE_RESPOND_TO_ALARM, handle_respond_to_alarm, SCHEMA_RESPOND_TO_ALARM
        )
        hass.services.async_register(
            DOMAIN, SERVICE_SET_OUTSIDE_REGION, handle_set_outside_region, SCHEMA_SET_OUTSIDE_REGION
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Verwijder de Pre-Com integratie."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_AVAILABLE)
            hass.services.async_remove(DOMAIN, SERVICE_RESPOND_TO_ALARM)
            hass.services.async_remove(DOMAIN, SERVICE_SET_OUTSIDE_REGION)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Herlaad de config entry bij opties-wijziging."""
    await hass.config_entries.async_reload(entry.entry_id)
