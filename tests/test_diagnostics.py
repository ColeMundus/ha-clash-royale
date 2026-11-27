"""Diagnostics must remove credentials and account identifiers while keeping stats."""

import json

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant.common import MockConfigEntry

from custom_components.clash_royale_stats.diagnostics import (
    async_get_config_entry_diagnostics,
)

DOMAIN = "clash_royale_stats"
TOKEN = "synthetic-key"


async def test_diagnostics_redact_credentials_and_identifiers(
    hass, provider, clan, war
):
    clan["description"] = "Private clan invite link"
    clan["memberList"] = [
        {"tag": "#P0Y", "name": "Synthetic Player", "role": "member"},
        {"tag": "#M1A", "name": "Other Member", "role": "elder"},
    ]
    war["clan"]["participants"] = [
        {
            "tag": "#P0Y",
            "name": "Synthetic Player",
            "fame": 1600,
            "decksUsed": 4,
        },
        {
            "tag": "#M1A",
            "name": "Other Member",
            "fame": 1200,
            "decksUsed": 3,
        },
    ]
    war["clans"] = [
        {
            "tag": "#R9Z",
            "name": "Rival Clan",
            "fame": 11000,
            "participants": [
                {"tag": "#R8Y", "name": "Rival Member", "fame": 800},
            ],
        }
    ]
    provider.set("/v1/clans/#Q0G", 200, clan)
    provider.set("/v1/clans/#Q0G/currentriverrace", 200, war)

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

    for sensitive in (
        TOKEN,
        "Bearer",
        "#P0Y",
        "#Q0G",
        "#M1A",
        "#R9Z",
        "#R8Y",
        "Synthetic Player",
        "Synthetic Clan",
        "Other Member",
        "Rival Clan",
        "Rival Member",
        "Private clan invite link",
    ):
        assert sensitive not in encoded

    assert diagnostics["entry"]["title"] == REDACTED
    assert diagnostics["entry"]["unique_id"] == REDACTED
    assert diagnostics["entry"]["data"]["api_key"] == REDACTED
    assert diagnostics["entry"]["data"]["player_tag"] == REDACTED
    assert diagnostics["entry"]["options"] == {"scan_interval": 5}

    assert diagnostics["data"]["player"]["trophies"] == 7500
    assert diagnostics["data"]["player"]["tag"] == REDACTED
    assert diagnostics["data"]["player"]["name"] == REDACTED
    assert diagnostics["data"]["player"]["clan"]["tag"] == REDACTED
    assert diagnostics["data"]["player"]["clan"]["name"] == REDACTED
    assert diagnostics["data"]["player"]["authorization"] == REDACTED

    assert diagnostics["data"]["clan"]["tag"] == REDACTED
    assert diagnostics["data"]["clan"]["name"] == REDACTED
    assert diagnostics["data"]["clan"]["description"] == REDACTED
    assert diagnostics["data"]["clan"]["members"] == 35
    assert diagnostics["data"]["clan"]["token"] == REDACTED
    assert diagnostics["data"]["clan"]["memberList"][1]["tag"] == REDACTED
    assert diagnostics["data"]["clan"]["memberList"][1]["name"] == REDACTED

    race_clan = diagnostics["data"]["river_race"]["clan"]
    assert race_clan["tag"] == REDACTED
    assert race_clan["name"] == REDACTED
    assert race_clan["fame"] == 12000
    assert race_clan["participants"][0]["tag"] == REDACTED
    assert race_clan["participants"][0]["name"] == REDACTED
    assert race_clan["participants"][0]["fame"] == 1600
    assert race_clan["participants"][1]["tag"] == REDACTED
    assert race_clan["participants"][1]["name"] == REDACTED

    rival = diagnostics["data"]["river_race"]["clans"][0]
    assert rival["tag"] == REDACTED
    assert rival["name"] == REDACTED
    assert rival["participants"][0]["tag"] == REDACTED
    assert rival["participants"][0]["name"] == REDACTED

    assert entry.data["api_key"] == TOKEN
    assert entry.data["player_tag"] == "#P0Y"
    assert entry.runtime_data.data["clan"]["token"] == TOKEN
    assert entry.runtime_data.data["player"]["tag"] == "#P0Y"
