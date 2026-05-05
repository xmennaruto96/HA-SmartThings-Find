import logging
import json
import pytz
import aiohttp
import html
from datetime import datetime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry

from .const import DOMAIN, BATTERY_LEVELS, CONF_ACTIVE_MODE_SMARTTAGS, CONF_ACTIVE_MODE_OTHERS

_LOGGER = logging.getLogger(__name__)

URL_GET_CSRF = "https://smartthingsfind.samsung.com/chkLogin.do"
URL_DEVICE_LIST = "https://smartthingsfind.samsung.com/device/getDeviceList.do"
URL_REQUEST_LOC_UPDATE = "https://smartthingsfind.samsung.com/dm/addOperation.do"
URL_SET_LAST_DEVICE = "https://smartthingsfind.samsung.com/device/setLastSelect.do"


async def validate_jsessionid(hass: HomeAssistant, jsessionid: str) -> bool:
    """Check whether a JSESSIONID cookie is currently valid for SmartThings Find.

    Uses an isolated aiohttp session: the shared HA session may already hold
    a JSESSIONID cookie pinned to ``smartthingsfind.samsung.com`` from a prior
    Set-Cookie response. A bare ``update_cookies({"JSESSIONID": ...})`` would
    only add an unscoped duplicate, and aiohttp's cookie jar would still ship
    the older, domain-matched (stale) cookie — making the freshly-pasted
    cookie look invalid to the server.

    A short-lived ClientSession with its own jar avoids that entirely.
    """
    try:
        async with aiohttp.ClientSession(
            cookies={"JSESSIONID": jsessionid}
        ) as session:
            async with session.get(URL_GET_CSRF) as response:
                if response.status == 200 and response.headers.get("_csrf"):
                    return True
                body = (await response.text())[:200]
                _LOGGER.warning(
                    f"JSESSIONID validation failed: status={response.status}, body='{body}'"
                )
                return False
    except Exception as e:
        _LOGGER.error(f"JSESSIONID validation error: {e}", exc_info=True)
        return False


async def fetch_csrf(hass: HomeAssistant, session: aiohttp.ClientSession, entry_id: str):
    """
    Retrieves the _csrf-Token which needs to be sent with each following request.

    This function retrieves the CSRF token required for further requests to the SmartThings Find service.
    The JSESSIONID must already be present as a cookie in the session at this point.

    Args:
        hass (HomeAssistant): Home Assistant instance.
        session (aiohttp.ClientSession): The current session.

    Raises:
        ConfigEntryAuthFailed: If the CSRF token is not found or if the authentication fails.
    """
    err_msg = ""
    async with session.get(URL_GET_CSRF) as response:
        if response.status == 200:
            csrf_token = response.headers.get("_csrf")
            if csrf_token:
                hass.data[DOMAIN][entry_id]["_csrf"] = csrf_token
                _LOGGER.info("Successfully fetched new CSRF Token")
                return
            else:
                err_msg = f"CSRF token not found in response headers. Status Code: {response.status}, Response: '{await response.text()}'"
                _LOGGER.error(err_msg)
        else:
            err_msg = f"Failed to authenticate with SmartThings Find: [{response.status}]: {await response.text()}"
            _LOGGER.error(err_msg)

        _LOGGER.debug(f"Headers: {response.headers}")

    raise ConfigEntryAuthFailed(err_msg)


async def get_devices(hass: HomeAssistant, session: aiohttp.ClientSession, entry_id: str) -> list:
    """
    Sends a request to the SmartThings Find API to retrieve a list of devices associated with the user's account.

    Args:
        hass (HomeAssistant): Home Assistant instance.
        session (aiohttp.ClientSession): The current session.

    Returns:
        list: A list of devices if successful, empty list otherwise.
    """
    url = f"{URL_DEVICE_LIST}?_csrf={hass.data[DOMAIN][entry_id]['_csrf']}"
    async with session.post(url, headers={'Accept': 'application/json'}, data={}) as response:
        if response.status != 200:
            _LOGGER.error(f"Failed to retrieve devices [{response.status}]: {await response.text()}")
            if response.status == 404:
                _LOGGER.warn(
                    f"Received 404 while trying to fetch devices -> Triggering reauth")
                raise ConfigEntryAuthFailed(
                    "Request to get device list failed: 404")
            return []
        response_json = await response.json()
        devices_data = response_json["deviceList"]
        devices = []
        for device in devices_data:
            # Double unescaping required. Example:
            # "Benedev&amp;#39;s S22" first becomes "Benedev&#39;s S22" and then "Benedev's S22"
            device['modelName'] = html.unescape(
                html.unescape(device['modelName']))
            identifier = (DOMAIN, device['dvceID'])
            ha_dev = device_registry.async_get(
                hass).async_get_device({identifier})
            if ha_dev and ha_dev.disabled:
                _LOGGER.debug(
                    f"Ignoring disabled device: '{device['modelName']}' (disabled by {ha_dev.disabled_by})")
                continue
            ha_dev_info = DeviceInfo(
                identifiers={identifier},
                manufacturer="Samsung",
                name=device['modelName'],
                model=device['modelID'],
                configuration_url="https://smartthingsfind.samsung.com/"
            )
            devices += [{"data": device, "ha_dev_info": ha_dev_info}]
            _LOGGER.debug(f"Adding device: {device['modelName']}")
        return devices


async def get_device_location(hass: HomeAssistant, session: aiohttp.ClientSession, dev_data: dict, entry_id: str) -> dict:
    """
    Sends requests to update the device's location and retrieves the current location data for the specified device.

    Args:
        hass (HomeAssistant): Home Assistant instance.
        session (aiohttp.ClientSession): The current session.
        dev_data (dict): The device information obtained from get_devices.

    Returns:
        dict: The device location data.
    """
    dev_id = dev_data['dvceID']
    dev_name = dev_data['modelName']

    set_last_payload = {
        "dvceId": dev_id,
        "removeDevice": []
    }

    update_payload = {
        "dvceId": dev_id,
        "operation": "CHECK_CONNECTION_WITH_LOCATION",
        "usrId": dev_data['usrId']
    }

    csrf_token = hass.data[DOMAIN][entry_id]["_csrf"]

    try:
        active = (
            (dev_data['deviceTypeCode'] == 'TAG' and hass.data[DOMAIN][entry_id][CONF_ACTIVE_MODE_SMARTTAGS]) or
            (dev_data['deviceTypeCode'] != 'TAG' and hass.data[DOMAIN]
             [entry_id][CONF_ACTIVE_MODE_OTHERS])
        )

        if active:
            _LOGGER.debug("Active mode; requesting location update now")
            async with session.post(f"{URL_REQUEST_LOC_UPDATE}?_csrf={csrf_token}", json=update_payload) as response:
                # _LOGGER.debug(f"[{dev_name}] Update request response ({response.status}): {await response.text()}")
                pass
        else:
            _LOGGER.debug("Passive mode; not requesting location update")

        async with session.post(f"{URL_SET_LAST_DEVICE}?_csrf={csrf_token}", json=set_last_payload, headers={'Accept': 'application/json'}) as response:
            _LOGGER.debug(
                f"[{dev_name}] Location response ({response.status})")
            if response.status == 200:
                data = await response.json()
                res = {
                    "dev_name": dev_name,
                    "dev_id": dev_id,
                    "update_success": True,
                    "location_found": False,
                    "used_op": None,
                    "used_loc": None,
                    "ops": []
                }
                used_loc = None
                if 'operation' in data and len(data['operation']) > 0:
                    res['ops'] = data['operation']

                    used_op = None
                    used_loc = {
                        "latitude": None,
                        "longitude": None,
                        "gps_accuracy": None,
                        "gps_date": None
                    }
                    # Find and extract the latest location from the response. Often the response
                    # contains multiple locations (especially for non-SmartTag devices such as phones).
                    # We go through all of them and find the "most usable" one. Sometimes locations
                    # are encrypted (usually OFFLINE_LOC), we ignore these. They could probably also
                    # be encrypted; there is a special getEncToken-Endpoint which returns some sort of
                    # key. Since the only encrypted locations I encountered were even older than the
                    # non encrypted ones, I didn't try anything to encrypt them yet.
                    for op in data['operation']:
                        if op['oprnType'] in ['LOCATION', 'LASTLOC', 'OFFLINE_LOC']:
                            if 'latitude' in op:
                                utcDate = None

                                if 'extra' in op and 'gpsUtcDt' in op['extra']:
                                    utcDate = parse_stf_date(
                                        op['extra']['gpsUtcDt'])
                                else:
                                    _LOGGER.warning(
                                        f"[{dev_name}] No UTC date found for operation '{op['oprnType']}'. OP: {json.dumps(op)}")
                                    continue

                                if utcDate is None:
                                    _LOGGER.warning(
                                        f"[{dev_name}] Could not parse UTC date for operation '{op['oprnType']}'")
                                    continue

                                if used_loc['gps_date'] and used_loc['gps_date'] >= utcDate:
                                    _LOGGER.debug(
                                        f"[{dev_name}] Ignoring location older than the previous ({op['oprnType']})")
                                    continue

                                locFound = False
                                if 'latitude' in op:
                                    used_loc['latitude'] = float(
                                        op['latitude'])
                                    locFound = True
                                if 'longitude' in op:
                                    used_loc['longitude'] = float(
                                        op['longitude'])
                                    locFound = True

                                if not locFound:
                                    _LOGGER.warn(
                                        f"[{dev_name}] Found no coordinates in operation '{op['oprnType']}'")
                                else:
                                    res['location_found'] = True

                                used_loc['gps_accuracy'] = calc_gps_accuracy(
                                    op.get('horizontalUncertainty'), op.get('verticalUncertainty'))
                                used_loc['gps_date'] = utcDate
                                used_op = op

                            elif 'encLocation' in op:
                                loc = op['encLocation']
                                if 'encrypted' in loc and loc['encrypted']:
                                    _LOGGER.info(
                                        f"[{dev_name}] Ignoring encrypted location ({op['oprnType']})")
                                    continue
                                elif 'gpsUtcDt' not in loc:
                                    _LOGGER.info(
                                        f"[{dev_name}] Ignoring location with missing date ({op['oprnType']})")
                                    continue
                                else:
                                    utcDate = parse_stf_date(loc['gpsUtcDt'])
                                    if utcDate is None:
                                        _LOGGER.warning(
                                            f"[{dev_name}] Could not parse UTC date for encrypted location ('{op['oprnType']}')")
                                        continue
                                    if used_loc['gps_date'] and used_loc['gps_date'] >= utcDate:
                                        _LOGGER.debug(
                                            f"[{dev_name}] Ignoring location older than the previous ({op['oprnType']})")
                                        continue
                                    else:
                                        locFound = False
                                        if 'latitude' in loc:
                                            used_loc['latitude'] = float(
                                                loc['latitude'])
                                            locFound = True
                                        if 'longitude' in loc:
                                            used_loc['longitude'] = float(
                                                loc['longitude'])
                                            locFound = True
                                        else:
                                            res['location_found'] = True

                                        if not locFound:
                                            _LOGGER.warn(
                                                f"[{dev_name}] Found no coordinates in operation '{op['oprnType']}'")

                                        used_loc['gps_accuracy'] = calc_gps_accuracy(
                                            loc.get('horizontalUncertainty'), loc.get('verticalUncertainty'))
                                        used_loc['gps_date'] = utcDate
                                        used_op = op
                                    continue

                    if used_op:
                        res['used_op'] = used_op
                        res['used_loc'] = used_loc
                    else:
                        _LOGGER.warn(
                            f"[{dev_name}] No useable location-operation found")

                    _LOGGER.debug(
                        f"    --> {dev_name} used operation: {'NONE' if not used_op else used_op['oprnType']}")

                else:
                    _LOGGER.warn(
                        f"[{dev_name}] No operation found in response; marking update failed")
                    res['update_success'] = False
                return res
            else:
                _LOGGER.error(
                    f"[{dev_name}] Failed to fetch device data ({response.status})")
                res_text = await response.text()
                _LOGGER.debug(f"[{dev_name}] Full response: '{res_text}'")

                # Our session is not valid anymore. Refreshing the CSRF Token ist not
                # enough at this point. Instead we have to ask the user to  go through
                # the whole auth flow again
                if res_text == 'Logout' or response.status == 401:
                    raise ConfigEntryAuthFailed(
                        f"Session not valid anymore, received status_code of {response.status} with response '{res_text}'")

    except ConfigEntryAuthFailed as e:
        raise
    except Exception as e:
        _LOGGER.error(
            f"[{dev_name}] Exception occurred while fetching location data for tag '{dev_name}': {e}", exc_info=True)

    return None


def calc_gps_accuracy(hu: float, vu: float) -> float:
    """
    Calculate the GPS accuracy using the Pythagorean theorem.
    Returns the combined GPS accuracy based on the horizontal
    and vertical uncertainties provided by the API

    Args:
        hu (float): Horizontal uncertainty.
        vu (float): Vertical uncertainty.

    Returns:
        float: Calculated GPS accuracy.
    """
    try:
        return round((float(hu)**2 + float(vu)**2) ** 0.5, 1)
    except ValueError:
        return None


def get_sub_location(ops: list, subDeviceName: str) -> tuple:
    """
    Extracts sub-location data for devices that contain multiple
    sub-locations (e.g., left and right earbuds).

    Args:
        ops (list): List of operations from the API.
        subDeviceName (str): Name of the sub-device.

    Returns:
        tuple: The operation and sub-location data.
    """
    if not ops or not subDeviceName or len(ops) < 1:
        return {}, {}
    for op in ops:
        if subDeviceName in op.get('encLocation', {}):
            loc = op['encLocation'][subDeviceName]
            gps_date = parse_stf_date(loc.get('gpsUtcDt', ''))
            sub_loc = {
                "latitude": float(loc['latitude']) if loc.get('latitude') is not None else None,
                "longitude": float(loc['longitude']) if loc.get('longitude') is not None else None,
                "gps_accuracy": calc_gps_accuracy(loc.get('horizontalUncertainty'), loc.get('verticalUncertainty')),
                "gps_date": gps_date
            }
            return op, sub_loc
    return {}, {}


def parse_stf_date(datestr: str) -> datetime | None:
    """
    Parses a date string in the format "%Y%m%d%H%M%S" to a datetime object.
    This is the format, the SmartThings Find API uses.

    Args:
        datestr (str): The date string in the format "%Y%m%d%H%M%S".

    Returns:
        datetime: A datetime object representing the input date string,
        or None if parsing fails.
    """
    if not datestr:
        return None
    try:
        return datetime.strptime(datestr, "%Y%m%d%H%M%S").replace(tzinfo=pytz.UTC)
    except ValueError:
        _LOGGER.warning(f"Failed to parse date string: '{datestr}'")
        return None


def get_battery_level(dev_name: str, ops: list) -> int:
    """
    Try to extract the device battery level from the received operation

    Args:
        dev_name (str): The name of the device.
        ops (list): List of operations from the API.

    Returns:
        int: The battery level if found, None otherwise.
    """
    for op in ops:
        if op['oprnType'] == 'CHECK_CONNECTION' and 'battery' in op:
            batt_raw = op['battery']
            batt = BATTERY_LEVELS.get(batt_raw, None)
            if batt is None:
                try:
                    batt = int(batt_raw)
                except ValueError:
                    _LOGGER.warn(
                        f"[{dev_name}]: Received invalid battery level: {batt_raw}")
            return batt
    return None
