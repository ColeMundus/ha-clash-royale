"""Native configuration, options and same-player reauthentication."""

from typing import Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ClashRoyaleClient,
    ClashRoyaleError,
    InvalidAuth,
    IPNotAllowed,
    NotFound,
    RateLimited,
    request_gate,
)
from .const import (
    CONF_PLAYER_TAG,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    normalize_tag,
    validate_interval,
)

PLACEHOLDERS = {
    "developer_portal": "https://developer.clashroyale.com/",
    "help_url": "https://github.com/ColeMundus/ha-clash-royale#create-an-api-key",
}


class WholeMinuteSelector(selector.NumberSelector):
    """Keep native number rendering without coercing booleans or strings."""

    def __call__(self, data: Any) -> int:
        try:
            return validate_interval(data)
        except ValueError:
            raise vol.Invalid(
                "Expected a whole number of minutes from 1 to 60"
            ) from None


def interval_selector() -> selector.NumberSelector:
    return WholeMinuteSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=60,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


def error_key(error: Exception) -> str:
    if isinstance(error, IPNotAllowed):
        return "ip_not_allowed"
    if isinstance(error, InvalidAuth):
        return "invalid_auth"
    if isinstance(error, NotFound):
        return "player_not_found"
    if isinstance(error, RateLimited):
        return "rate_limited"
    return "cannot_connect"


class ClashRoyaleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one entry for a canonical player tag."""

    VERSION = 1
    _removed = False

    @callback
    def async_remove(self) -> None:
        """Invalidate in-flight submissions even when their task is not cancelled."""
        self._removed = True
        super().async_remove()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return ClashRoyaleOptionsFlow()

    async def _validate(self, api_key: str, tag: str) -> dict[str, Any]:
        client = ClashRoyaleClient(
            async_get_clientsession(self.hass),
            api_key,
            request_gate(self.hass, api_key),
        )
        return await client.async_get_player(tag)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                tag = normalize_tag(user_input[CONF_PLAYER_TAG])
            except ValueError:
                errors[CONF_PLAYER_TAG] = "invalid_tag"
            if not errors:
                await self.async_set_unique_id(tag)
                self._abort_if_unique_id_configured()
                try:
                    player = await self._validate(user_input[CONF_API_KEY], tag)
                except ClashRoyaleError as err:
                    errors["base"] = error_key(err)
                else:
                    return self.async_create_entry(
                        title=f"Clash Royale War Tracker {player.get('name', tag)}",
                        data={
                            CONF_API_KEY: user_input[CONF_API_KEY],
                            CONF_PLAYER_TAG: tag,
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(CONF_PLAYER_TAG): selector.TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders=PLACEHOLDERS,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await self._validate(
                    user_input[CONF_API_KEY], normalize_tag(entry.data[CONF_PLAYER_TAG])
                )
            except ClashRoyaleError as err:
                errors["base"] = error_key(err)
            if self._removed:
                return self.async_abort(reason="reauth_aborted")
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=PLACEHOLDERS,
        )


class ClashRoyaleOptionsFlow(config_entries.OptionsFlowWithReload):
    """Change polling cadence without replacing credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                minutes = validate_interval(user_input[CONF_SCAN_INTERVAL])
            except ValueError:
                errors[CONF_SCAN_INTERVAL] = "invalid_interval"
            else:
                return self.async_create_entry(
                    title="",
                    data={**self.config_entry.options, CONF_SCAN_INTERVAL: minutes},
                )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SCAN_INTERVAL, default=current): interval_selector()}
            ),
            errors=errors,
        )
