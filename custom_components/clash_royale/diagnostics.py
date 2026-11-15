"""Support diagnostics with the API token removed."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import ClashRoyaleConfigEntry

TO_REDACT = {
    CONF_API_KEY,
    "authorization",
    "token",
    "access_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClashRoyaleConfigEntry
) -> dict[str, Any]:
    """Return config-entry diagnostics without the developer token."""
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": async_redact_data(entry.runtime_data.data, TO_REDACT),
    }
