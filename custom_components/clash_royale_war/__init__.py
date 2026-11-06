"""Clash Royale War Tracker cloud polling integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ClashRoyaleClient, request_gate
from .const import PLATFORMS
from .coordinator import ClashRoyaleCoordinator

type ClashRoyaleConfigEntry = ConfigEntry[ClashRoyaleCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ClashRoyaleConfigEntry) -> bool:
    """Create one shared coordinator and forward sensor setup."""
    token = entry.data[CONF_API_KEY]
    client = ClashRoyaleClient(
        async_get_clientsession(hass), token, request_gate(hass, token)
    )
    coordinator = ClashRoyaleCoordinator(hass, entry, client)
    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        coordinator.retire()
        raise
    entry.async_on_unload(coordinator.retire)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ClashRoyaleConfigEntry
) -> bool:
    """Retire before unloading so queued and late responses cannot publish."""
    entry.runtime_data.retire()
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except BaseException:
        entry.runtime_data.retired = False
        entry.runtime_data.client.retired = False
        raise
    if not unloaded:
        # Platform unload failed; restore the still-loaded runtime.
        entry.runtime_data.retired = False
        entry.runtime_data.client.retired = False
    return unloaded
