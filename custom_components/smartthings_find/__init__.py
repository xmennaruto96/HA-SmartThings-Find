from datetime import timedelta
import logging
import aiohttp
from yarl import URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    CONF_JSESSIONID,
    CONF_ACTIVE_MODE_OTHERS,
    CONF_ACTIVE_MODE_OTHERS_DEFAULT,
    CONF_ACTIVE_MODE_SMARTTAGS,
    CONF_ACTIVE_MODE_SMARTTAGS_DEFAULT,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL_DEFAULT
)
from .utils import fetch_csrf, get_devices, get_device_location

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.BUTTON, Platform.SENSOR]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the SmartThings Find component."""
    hass.data[DOMAIN] = {}
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartThings Find from a config entry."""
    
    hass.data[DOMAIN][entry.entry_id] = {}

    # Load the jsessionid from the config and create a session from it
    jsessionid = entry.data[CONF_JSESSIONID]

    session = async_get_clientsession(hass)
    # The shared HA session may already hold a JSESSIONID for this domain
    # from a previous load (set via Set-Cookie). Clear it first; otherwise
    # a bare update_cookies adds an unscoped duplicate and aiohttp ships the
    # older, domain-matched (stale) value, breaking auth after a UI reauth.
    session.cookie_jar.clear_domain("smartthingsfind.samsung.com")
    session.cookie_jar.update_cookies(
        {"JSESSIONID": jsessionid},
        response_url=URL("https://smartthingsfind.samsung.com/"),
    )

    active_smarttags = entry.options.get(CONF_ACTIVE_MODE_SMARTTAGS, CONF_ACTIVE_MODE_SMARTTAGS_DEFAULT)
    active_others = entry.options.get(CONF_ACTIVE_MODE_OTHERS, CONF_ACTIVE_MODE_OTHERS_DEFAULT)

    hass.data[DOMAIN][entry.entry_id].update({
        CONF_ACTIVE_MODE_SMARTTAGS:  active_smarttags,
        CONF_ACTIVE_MODE_OTHERS: active_others,
    })

    # This raises ConfigEntryAuthFailed-exception if failed. So if we
    # can continue after fetch_csrf, we know that authentication was ok
    await fetch_csrf(hass, session, entry.entry_id)
    
    # Load all SmartThings-Find devices from the users account
    devices = await get_devices(hass, session, entry.entry_id)

    # Create an update coordinator. This is responsible to regularly
    # fetch data from STF and update the device_tracker and sensor
    # entities
    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, CONF_UPDATE_INTERVAL_DEFAULT)
    coordinator = SmartThingsFindCoordinator(hass, session, entry.entry_id, update_interval)

    # Store everything the coordinator needs BEFORE the first refresh,
    # because _async_update_data reads `devices` out of hass.data.
    hass.data[DOMAIN][entry.entry_id].update({
        CONF_JSESSIONID: jsessionid,
        "session": session,
        "coordinator": coordinator,
        "devices": devices,
    })

    # This is what makes the whole integration slow to load (around 10-15
    # seconds for my 15 devices) but it is the right way to do it. Only if
    # it succeeds, the integration will be marked as successfully loaded.
    await coordinator.async_config_entry_first_refresh()

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_success:
        hass.data[DOMAIN].pop(entry.entry_id)
    else:
        _LOGGER.error(f"Unload failed: {unload_success}")
    return unload_success


class SmartThingsFindCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartThings Find data."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, entry_id: str, update_interval : int):
        """Initialize the coordinator."""
        self.session = session
        self._entry_id = entry_id
        self.hass = hass
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval)  # Update interval for all entities
        )

    async def _async_update_data(self):
        """Fetch data from SmartThings Find."""
        try:
            devices = self.hass.data[DOMAIN][self._entry_id]["devices"]
            tags = {}
            _LOGGER.debug(f"Updating locations...")
            for device in devices:
                dev_data = device['data']
                tag_data = await get_device_location(self.hass, self.session, dev_data, self._entry_id)
                tags[dev_data['dvceID']] = tag_data
            _LOGGER.debug(f"Fetched {len(tags)} locations")
            return tags
        except ConfigEntryAuthFailed as err:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}")