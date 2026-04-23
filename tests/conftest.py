"""
Mock homeassistant en andere HA-afhankelijkheden zodat de integratie
importeerbaar is zonder een volledige HA-installatie.

Kritieke modules (die als base-klasse of via 'from x import' worden gebruikt)
worden aangemaakt als echte types.ModuleType zodat attribuuttoegang stabiel is.
Overige modules worden als MagicMock gemockt.
"""
import sys
import types
from enum import Enum
from unittest.mock import MagicMock

# ── Fake entity-basisklassen ──────────────────────────────────────────────────

class _FakeEntity:
    _attr_unique_id = None
    _attr_name = None
    _attr_icon = None
    _attr_device_info = None
    _attr_entity_category = None
    _attr_native_unit_of_measurement = None
    _attr_is_on = None

    def async_write_ha_state(self):
        pass


class _FakeCoordinatorEntity(_FakeEntity):
    def __init__(self, coordinator, **kwargs):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        # Retourneer de klasse zelf zodat CoordinatorEntity[T] geen GenericAlias
        # oplevert — voorkomt metaclass-conflict bij multiple inheritance.
        return cls

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    @property
    def available(self):
        return bool(getattr(self.coordinator, "last_update_success", True))


class _FakeDataUpdateCoordinator:
    def __init__(self, hass=None, logger=None, *, name="", update_interval=None, **kwargs):
        self.hass = hass
        self.data = None
        self.last_update_success = True

    def async_add_listener(self, cb, context=None):
        return lambda: None


class _FakeSwitchEntity(_FakeEntity):
    pass


class _FakeSensorEntity(_FakeEntity):
    pass


class _FakeBinarySensorEntity(_FakeEntity):
    pass


class _FakeButtonEntity(_FakeEntity):
    pass


class _FakeEntityCategory(Enum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class _FakeHomeAssistantError(Exception):
    pass


# ── Module-factory ────────────────────────────────────────────────────────────

def _real_mod(name, **attrs):
    """Maak een echte module met gegeven attributen."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _mock_mod(name):
    """Maak een MagicMock-module voor niet-kritieke HA-modules."""
    return MagicMock(spec=types.ModuleType)


# ── Kritieke modules met echte klassen ───────────────────────────────────────
# Deze worden via 'from x import Y' geïmporteerd als superklassen.

_REAL_MODULES = {
    "homeassistant.helpers.update_coordinator": _real_mod(
        "homeassistant.helpers.update_coordinator",
        CoordinatorEntity=_FakeCoordinatorEntity,
        DataUpdateCoordinator=_FakeDataUpdateCoordinator,
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
    ),
    "homeassistant.components.switch": _real_mod(
        "homeassistant.components.switch",
        SwitchEntity=_FakeSwitchEntity,
    ),
    "homeassistant.components.sensor": _real_mod(
        "homeassistant.components.sensor",
        SensorEntity=_FakeSensorEntity,
    ),
    "homeassistant.components.binary_sensor": _real_mod(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=_FakeBinarySensorEntity,
    ),
    "homeassistant.components.button": _real_mod(
        "homeassistant.components.button",
        ButtonEntity=_FakeButtonEntity,
    ),
    "homeassistant.helpers.entity": _real_mod(
        "homeassistant.helpers.entity",
        EntityCategory=_FakeEntityCategory,
        DeviceInfo=dict,
    ),
    "homeassistant.exceptions": _real_mod(
        "homeassistant.exceptions",
        HomeAssistantError=_FakeHomeAssistantError,
    ),
    "homeassistant.helpers.device_registry": _real_mod(
        "homeassistant.helpers.device_registry",
        DeviceEntryType=type("DeviceEntryType", (), {"SERVICE": "service"}),
    ),
}

# ── Overige modules als MagicMock ─────────────────────────────────────────────

_MOCK_MODULE_NAMES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.components",
    "homeassistant.components.number",
    "voluptuous",
]

for _name in _MOCK_MODULE_NAMES:
    sys.modules.setdefault(_name, MagicMock())

for _name, _mod in _REAL_MODULES.items():
    sys.modules[_name] = _mod
    # Also set the attribute on the parent package so `import pkg.sub as x`
    # resolves to the real module rather than the parent MagicMock's auto-attr.
    parts = _name.rsplit(".", 1)
    if len(parts) == 2:
        parent = sys.modules.get(parts[0])
        if parent is not None:
            setattr(parent, parts[1], _mod)
