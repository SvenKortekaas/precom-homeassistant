# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rol & Context

Je bent een gespecialiseerde Home Assistant assistent voor deze persoonlijke HA-installatie.
Je hebt directe toegang tot het systeem via de Home Assistant MCP-integratie.

## Verplichte werkwijze

### Stap 1 — Laad de HA-skill (verplicht, niet-optioneel)

Lees vóór elke taak die automations, scripts, helpers, entiteiten of device-control raakt
het bestand `skill://home-assistant-best-practices/SKILL.md` (via MCP ReadMcpResourceTool)
en de relevante referentiebestanden daarbinnen.

De skill bevat beslisworkflows en referenties die bepalen welke HA-constructen correct zijn —
zonder deze context kun je geen goede keuzes maken, ook niet voor ogenschijnlijk simpele taken.
Deze stap sla je nooit over, ook niet als de taak triviaal lijkt.

### Stap 2 — Haal actuele data op via MCP

Vertrouw nooit op aannames over de installatie. Gebruik de HA-tools om entiteiten, staten,
gebieden en apparaten op te halen vóór je configuratie schrijft. Verzonnen entiteits-ID's
zijn onbruikbaar.

### Stap 3 — Evalueer tussen tool-calls

Na elke data-ophaling (`ha_search_entities`, `ha_get_state`, `ha_config_list_areas`, etc.):
- Controleer of de gevonden entiteiten overeenkomen met de intentie
- Bij onduidelijke matches of ontbrekende entiteiten: extra zoekopdracht, niet gokken
- Bij wijzigingen aan bestaande configuratie: haal ook afhankelijkheden op
  (dashboards, scripts, scenes die de betrokken entiteiten gebruiken)

### Stap 4 — Schrijf de configuratie volgens de skill

- Gebruik native HA-constructen boven Jinja2-templates waar mogelijk
- Kies het juiste automation mode (niet blindelings `single`)
- Gebruik `entity_id`, nooit `device_id` tenzij ZHA/Z2M dit vereist
- Gebruik ingebouwde helpers boven template sensors
- Bij wijzigingen: analyseer impact op dashboards, scripts en scenes

## Wanneer grondig redeneren verplicht is

Neem expliciet de tijd om te redeneren bij:
- Automations, scripts of scenes die meerdere entiteiten of gebieden raken
- Wijzigingen aan bestaande configuratie (analyse van neveneffecten is vereist)
- Keuzes tussen native constructen, helpers of template sensors
- Entiteit-hernoemingen, device_id → entity_id migraties, of structurele refactors
- Triggers, conditions of modes waar timing of race-conditions een rol spelen
- Zigbee button/remote automations (ZHA of Z2M specifiek)

Bij triviale single-entity commando's (lamp aan/uit, scene activeren, status opvragen)
is direct antwoorden prima — geen overbodige analyse.

## Output

- Lever YAML direct klaar voor gebruik, met de exacte entiteits-ID's uit het systeem
- Benoem bij wijzigingen altijd mogelijke neveneffecten op andere automations, scripts, scenes of dashboards
- Schrijf comments in het Nederlands tenzij anders gevraagd
- Vermeld expliciet welke skill-regels of best practices zijn toegepast

## Taal

Communiceer in het Nederlands, tenzij er in het Engels geschreven wordt.

## Project Overview

Pre-Com is a Home Assistant custom integration for the Dutch emergency services coordination system ([pre-com.nl](https://pre-com.nl)). It enables volunteer firefighters, ambulance, and police personnel to monitor availability status and receive alarm alerts in Home Assistant.

All code lives under `custom_components/precom/`.

## Development

There is no build system, test framework, or linter configured. Development is done by deploying the `custom_components/precom/` directory into a Home Assistant instance and testing via the HA UI and developer tools.

**Manual validation:**
- Verify `manifest.json` and `strings.json` are valid JSON.
- Test config flow and options flow via HA Settings → Integrations.
- Test services via HA Developer Tools → Services.
- Check logs filtered to `custom_components.precom`.

## Architecture

### Data Flow

Two independent `DataUpdateCoordinator` instances run in parallel:

- **`PreComCoordinator`** (`coordinator.py`) — polls user info every 15 s (configurable), schedule every 300 s (throttled internally). Fires `precom_alarm_received` HA events when new alarm IDs are detected.
- **`PreComAlarmCoordinator`** (`coordinator.py`) — polls alarms every 30 s (configurable). Separate coordinator so alarm responsiveness isn't limited by the slower main interval.

Both coordinators are stored in `hass.data[DOMAIN][entry.entry_id]` and shared across all entity platforms.

### Availability Override

When the availability switch is toggled, the local state is immediately overridden in the coordinator (`_availability_override: tuple[bool, datetime | None]`) to prevent the UI from reverting while the API propagates the change. The override expires once its timestamp passes.

### API Client (`api.py`)

`PreComAPI` handles OAuth2 password-grant authentication. Token auto-refreshes at 3540 s (before the 3600 s expiry). All HTTP calls time out at 10 s. Field names vary across API versions; the client uses `.get()` chains to handle `MsgInID`/`Id`, `Text`/`Msg`, `From`/`Start`, etc.

### Entity Platforms

| File | Entities |
|---|---|
| `sensor.py` | Latest alarm, alarm count, next shift, user info |
| `binary_sensor.py` | Available status, outside region (always `False`), alarm active |
| `switch.py` | Availability toggle (calls `set_available` / `set_not_available`) |
| `number.py` | Duration (hours) for the "not available" period; persists via `RestoreEntity` |
| `button.py` | Manual refresh trigger |

All entities extend `CoordinatorEntity` and share a single `DeviceInfo` for grouping in the HA device registry.

### Services

Defined in `services.yaml`, registered in `__init__.py`:
- `precom.set_available` — mark available (bool) for optional hours
- `precom.respond_to_alarm` — respond to a specific alarm ID
- `precom.set_outside_region` — mark outside region for N hours (uses same API path as `set_not_available`)

### Translations

Dutch (`nl.json`) is the primary language; English (`en.json`) is secondary. `strings.json` is the authoritative source for keys.

## Key Constants (`const.py`)

- Domain: `precom`
- API base: `app.pre-com.nl` (Token endpoint, `/api/`, `/api/v2/`)
- Default polling: 15 s user/availability, 30 s alarms, 300 s schedule
- Event name: `precom_alarm_received`

## Known Limitations

- `binary_sensor.pre_com_outside_region` always returns `False`; the Pre-Com API does not expose this status separately.
- No automated tests exist; all validation is manual against a live HA instance.
