"""Diagnostics must keep public game data and remove the API token."""

import json

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant.common import MockConfigEntry

from custom_components.clash_royale.diagnostics import (
    async_get_config_entry_diagnostics,
)

DOMAIN = "clash_royale"
TOKEN = "synthetic-key"


async def test_diagnostics_redact_token_and_keep_public_snapshot(hass, provider):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="#P0Y",
        title="Clash Royale Synthetic Player",
        data={"api_key": TOKEN, "player_tag": "#P0Y"},
        options={"scan_interval": 5},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.data["clan"]["token"] = TOKEN
    entry.runtime_data.data["player"]["authorization"] = f"Bearer {TOKEN}"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    encoded = json.dumps(diagnostics)

    assert TOKEN not in encoded
    assert "Bearer" not in encoded
    assert diagnostics["entry"]["data"]["api_key"] == REDACTED
    assert diagnostics["entry"]["data"]["player_tag"] == "#P0Y"
    assert diagnostics["entry"]["unique_id"] == "#P0Y"
    assert diagnostics["entry"]["options"] == {"scan_interval": 5}
    assert diagnostics["data"]["player"]["trophies"] == 7500
    assert diagnostics["data"]["player"]["name"] == "Synthetic Player"
    assert diagnostics["data"]["clan"]["tag"] == "#Q0G"
    assert diagnostics["data"]["clan"]["token"] == REDACTED
    assert diagnostics["data"]["player"]["authorization"] == REDACTED
    assert entry.data["api_key"] == TOKEN
    assert entry.runtime_data.data["clan"]["token"] == TOKEN
