"""Support diagnostics with credentials and account identifiers removed."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import ClashRoyaleConfigEntry
from .const import CONF_PLAYER_TAG

TO_REDACT = {
    CONF_API_KEY,
    CONF_PLAYER_TAG,
    "authorization",
    "token",
    "access_token",
    "title",
    "unique_id",
    "tag",
    "name",
    "description",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClashRoyaleConfigEntry
) -> dict[str, Any]:
    """Return config-entry diagnostics without credentials or account identifiers."""
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(entry.runtime_data.data, TO_REDACT),
    }
