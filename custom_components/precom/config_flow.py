"""Config flow voor de Pre-Com integratie."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PreComApiError, PreComAuthError, PreComClient
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

_LOGGER = logging.getLogger(__name__)

SCHEMA_GEBRUIKER = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
        vol.Coerce(int), vol.Range(min=10, max=3600)
    ),
    vol.Optional(CONF_ALARM_SCAN_INTERVAL, default=DEFAULT_ALARM_SCAN_INTERVAL): vol.All(
        vol.Coerce(int), vol.Range(min=15, max=300)
    ),
    vol.Optional(CONF_SCHEDULE_SCAN_INTERVAL, default=DEFAULT_SCHEDULE_SCAN_INTERVAL): vol.All(
        vol.Coerce(int), vol.Range(min=60, max=3600)
    ),
})


class PreComConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow voor Pre-Com."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client  = PreComClient(session, username, password)

            try:
                await client.authenticate()
                user_info = await client.get_user_info()
                name = user_info.get("FullName") or user_info.get("Name") or username
            except PreComAuthError:
                errors["base"] = "invalid_auth"
            except PreComApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Onverwachte fout bij Pre-Com configuratie")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Pre-Com ({name})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=SCHEMA_GEBRUIKER,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PreComOptionsFlow:
        return PreComOptionsFlow(config_entry)


class PreComOptionsFlow(config_entries.OptionsFlow):
    """Opties flow voor Pre-Com."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def _get(key: str, default: Any) -> Any:
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=_get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                vol.Optional(
                    CONF_ALARM_SCAN_INTERVAL,
                    default=_get(CONF_ALARM_SCAN_INTERVAL, DEFAULT_ALARM_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
                vol.Optional(
                    CONF_DEBUG_LOGGING,
                    default=_get(CONF_DEBUG_LOGGING, True),
                ): bool,
            }),
        )
