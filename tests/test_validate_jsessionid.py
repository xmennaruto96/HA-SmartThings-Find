"""Tests for validate_jsessionid.

The interesting case is cookie-jar pollution: HA's shared aiohttp session can
already hold a JSESSIONID cookie that was stored from a previous Set-Cookie
response (so it carries a real domain attribute). When we then pre-load a new
JSESSIONID via update_cookies({"JSESSIONID": ...}) without specifying a
response_url, the new cookie gets stored with no domain and aiohttp ships the
older, more-specific one — making the new (valid) cookie look invalid to
Samsung."""
from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.smartthings_find.utils import (
    URL_GET_CSRF,
    validate_jsessionid,
)


@pytest.fixture
async def hass(monkeypatch):
    from homeassistant.core import HomeAssistant

    h = HomeAssistant()
    async with aiohttp.ClientSession() as session:
        h.clientsession = session
        yield h


@pytest.mark.asyncio
async def test_valid_cookie_returns_true(hass):
    with aioresponses() as m:
        m.get(URL_GET_CSRF, status=200, headers={"_csrf": "tok123"})
        assert await validate_jsessionid(hass, "fresh-cookie") is True


@pytest.mark.asyncio
async def test_no_csrf_header_returns_false(hass):
    with aioresponses() as m:
        m.get(URL_GET_CSRF, status=200, body="fail")
        assert await validate_jsessionid(hass, "expired-cookie") is False


@pytest.mark.asyncio
async def test_non_200_returns_false(hass):
    with aioresponses() as m:
        m.get(URL_GET_CSRF, status=401, body="Logout")
        assert await validate_jsessionid(hass, "anything") is False


@pytest.mark.asyncio
async def test_validation_does_not_touch_shared_session(hass):
    """The shared HA session may already hold a JSESSIONID cookie with a real
    domain (set by a previous Set-Cookie). Validation must run in an isolated
    aiohttp session so:

    * the shared jar is not mutated as a side-effect of validation, and
    * a stale domain-bound JSESSIONID can't shadow the cookie we're validating.

    Without this, aiohttp's cookie jar prefers the domain-matched (stale)
    cookie over the bare cookie we just added, so Samsung sees the expired
    session, returns no `_csrf`, and we tell the user their cookie was
    rejected even though it was perfectly fine."""
    hass.clientsession.cookie_jar.update_cookies(
        {"JSESSIONID": "STALE_VALUE"},
        response_url=URL("https://smartthingsfind.samsung.com/"),
    )
    before = sorted(
        (c.key, c["domain"], c.value)
        for c in hass.clientsession.cookie_jar
    )

    with aioresponses() as m:
        m.get(URL_GET_CSRF, status=200, headers={"_csrf": "tok"})
        result = await validate_jsessionid(hass, "FRESH_VALUE")

    after = sorted(
        (c.key, c["domain"], c.value)
        for c in hass.clientsession.cookie_jar
    )

    assert before == after, (
        "validate_jsessionid mutated the shared HA session's cookie jar; "
        "it must use an isolated session.\n"
        f"  before: {before}\n  after:  {after}"
    )
    assert result is True, (
        "validate_jsessionid returned False even though the mocked server "
        "would have replied with _csrf — the stale shared-jar cookie likely "
        "shadowed the fresh one"
    )
