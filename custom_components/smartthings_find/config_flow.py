from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from .const import (
    DOMAIN,
    CONF_JSESSIONID,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL_DEFAULT,
    CONF_ACTIVE_MODE_SMARTTAGS,
    CONF_ACTIVE_MODE_SMARTTAGS_DEFAULT,
    CONF_ACTIVE_MODE_OTHERS,
    CONF_ACTIVE_MODE_OTHERS_DEFAULT,
)
from .utils import validate_jsessionid
import logging


_LOGGER = logging.getLogger(__name__)


class SmartThingsFindConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartThings Find.

    Samsung's account.samsung.com login was rebuilt as a JS SPA (IAM/OAuth2
    with bot protection), so the original QR-code login flow no longer works.
    Until that is reverse-engineered we fall back to letting the user paste
    the JSESSIONID cookie they obtain from a normal browser session at
    https://smartthingsfind.samsung.com/.
    """

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    reauth_entry: ConfigEntry | None = None

    async def _async_handle_jsessionid(self, jsessionid: str) -> ConfigFlowResult:
        data = {CONF_JSESSIONID: jsessionid}
        if self.reauth_entry:
            return self.async_update_reload_and_abort(self.reauth_entry, data=data)
        return self.async_create_entry(title="SmartThings Find", data=data)

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            jsessionid = (user_input.get(CONF_JSESSIONID) or "").strip()
            if not jsessionid:
                errors["base"] = "empty_cookie"
            elif await validate_jsessionid(self.hass, jsessionid):
                return await self._async_handle_jsessionid(jsessionid)
            else:
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_JSESSIONID): str}),
            errors=errors,
        )

    async def async_step_reauth(self, user_input=None):
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SmartThingsFindOptionsFlowHandler(config_entry)


class SmartThingsFindOptionsFlowHandler(OptionsFlowWithConfigEntry):
    """Handle an options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""

        if user_input is not None:

            res = self.async_create_entry(title="", data=user_input)

            # Reload the integration entry to make sure the newly set options take effect
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return res

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self.options.get(
                        CONF_UPDATE_INTERVAL, CONF_UPDATE_INTERVAL_DEFAULT
                    ),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=30)),
                vol.Optional(
                    CONF_ACTIVE_MODE_SMARTTAGS,
                    default=self.options.get(
                        CONF_ACTIVE_MODE_SMARTTAGS, CONF_ACTIVE_MODE_SMARTTAGS_DEFAULT
                    ),
                ): bool,
                vol.Optional(
                    CONF_ACTIVE_MODE_OTHERS,
                    default=self.options.get(
                        CONF_ACTIVE_MODE_OTHERS, CONF_ACTIVE_MODE_OTHERS_DEFAULT
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
