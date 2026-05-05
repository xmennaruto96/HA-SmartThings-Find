"""Stub the HA imports the integration touches so utils/config_flow can be
imported and exercised without a full Home Assistant install.

Only the bits used by the code under test are faked — anything new the
integration starts touching will need to be added here."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _module(name: str) -> types.ModuleType:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


# homeassistant.core
ha = _module("homeassistant")
core = _module("homeassistant.core")


class HomeAssistant:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        # Tests assign a real aiohttp.ClientSession here.
        self.clientsession = None


def callback(func):
    return func


core.HomeAssistant = HomeAssistant
core.callback = callback
ha.core = core

# homeassistant.exceptions
exc = _module("homeassistant.exceptions")


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


exc.ConfigEntryAuthFailed = ConfigEntryAuthFailed
exc.ConfigEntryNotReady = ConfigEntryNotReady

# homeassistant.helpers + submodules
helpers = _module("homeassistant.helpers")
aiohttp_client = _module("homeassistant.helpers.aiohttp_client")


def async_get_clientsession(hass: HomeAssistant):
    return hass.clientsession


aiohttp_client.async_get_clientsession = async_get_clientsession
helpers.aiohttp_client = aiohttp_client

entity = _module("homeassistant.helpers.entity")


class DeviceInfo(dict):
    pass


entity.DeviceInfo = DeviceInfo
helpers.entity = entity

device_registry = _module("homeassistant.helpers.device_registry")


class _FakeDeviceRegistry:
    def async_get_device(self, identifiers):
        return None


def _async_get(_hass):
    return _FakeDeviceRegistry()


device_registry.async_get = _async_get
helpers.device_registry = device_registry

typing_module = _module("homeassistant.helpers.typing")
typing_module.ConfigType = dict

# config_entries
config_entries = _module("homeassistant.config_entries")


class ConfigEntry:
    pass


class ConfigFlow:
    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)


class OptionsFlow:
    pass


class OptionsFlowWithConfigEntry(OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.options = dict(getattr(config_entry, "options", {}) or {})


CONN_CLASS_CLOUD_POLL = "cloud_poll"
ConfigFlowResult = dict

config_entries.ConfigEntry = ConfigEntry
config_entries.ConfigFlow = ConfigFlow
config_entries.OptionsFlow = OptionsFlow
config_entries.OptionsFlowWithConfigEntry = OptionsFlowWithConfigEntry
config_entries.CONN_CLASS_CLOUD_POLL = CONN_CLASS_CLOUD_POLL
config_entries.ConfigFlowResult = ConfigFlowResult

# const
const = _module("homeassistant.const")


class Platform:
    DEVICE_TRACKER = "device_tracker"
    BUTTON = "button"
    SENSOR = "sensor"


const.Platform = Platform

# update_coordinator
update_coord = _module("homeassistant.helpers.update_coordinator")


class DataUpdateCoordinator:
    def __init__(self, *args, **kwargs):
        pass


class UpdateFailed(Exception):
    pass


update_coord.DataUpdateCoordinator = DataUpdateCoordinator
update_coord.UpdateFailed = UpdateFailed
helpers.update_coordinator = update_coord
