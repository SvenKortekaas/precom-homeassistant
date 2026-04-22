"""
Mock homeassistant en andere HA-afhankelijkheden zodat api.py importeerbaar is
zonder een volledige HA-installatie.
"""
import sys
from unittest.mock import MagicMock

_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.button",
    "homeassistant.components.number",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "voluptuous",
]

for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())
