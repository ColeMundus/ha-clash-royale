"""Native HA sensor states, stable registry identity and honest river data."""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.clash_royale_war.sensor import SENSORS

DOMAIN = "clash_royale_war"
INPUT = {"api_key": "synthetic-key", "player_tag": "#P0Y", "scan_interval": 5}
PREFIX = "sensor.clash_royale_war_tracker_synthetic_player_"


async def setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="#P0Y", data=INPUT, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def participant():
    return {
        "tag": "#P0Y",
        "name": "Synthetic Player",
        "fame": 800,
        "repairPoints": 0,
        "boatAttacks": 2,
        "decksUsed": 8,
        "decksUsedToday": 0,
    }


async def test_native_states_icons_and_registry(hass, provider, war):
    war["clan"]["participants"] = [participant()]
    provider.set("/v1/clans/#Q0G/currentriverrace", body=war)
    entry = await setup(hass)
    expected = {
        "trophies": "7500",
        "best_trophies": "8000",
        "exp_level": "54",
        "exp_points": "unavailable",
        "wins": "1000",
        "losses": "900",
        "battle_count": "2000",
        "donations": "40",
        "donations_received": "30",
        "clan_members": "35",
        "clan_score": "60000",
        "clan_war_trophies": "2000",
        "river_race_fame": "12000",
        "river_race_repair_points": "400",
        "player_race_fame": "800",
        "player_race_repair_points": "0",
        "player_race_boat_attacks": "2",
        "player_race_decks_used": "8",
        "player_race_decks_used_today": "0",
    }
    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    assert set(states) == {PREFIX + key for key in expected}
    assert {key: states[PREFIX + key].state for key in expected} == expected
    for description in SENSORS:
        assert states[PREFIX + description.key].attributes["icon"] == description.icon
    assert (
        states[PREFIX + "trophies"].attributes["friendly_name"]
        == "Clash Royale War Tracker Synthetic Player Trophies"
    )
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.unique_id for e in entities} == {f"#P0Y_{key}" for key in expected}
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "#P0Y"), entry.entry_id
    )
    assert device.name == "Clash Royale War Tracker Synthetic Player"
    assert len(provider.requests) == 3


async def test_departure_clears_clan_and_race(hass, provider, player, war, freezer):
    war["clan"]["participants"] = [participant()]
    provider.set("/v1/clans/#Q0G/currentriverrace", body=war)
    entry = await setup(hass)
    assert hass.states.get(PREFIX + "player_race_fame").state == "800"
    player.pop("clan")
    provider.set("/v1/players/#P0Y", body=player)
    freezer.tick(timedelta(seconds=301))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(PREFIX + "trophies").state == "7500"
    for description in SENSORS:
        if "clan" in description.key or "race" in description.key:
            assert hass.states.get(PREFIX + description.key).state == "unavailable"
    assert len(provider.requests) == 4


async def test_absent_participant_is_not_previous_or_zero(hass, provider, war, freezer):
    war["clan"]["participants"] = [participant()]
    provider.set("/v1/clans/#Q0G/currentriverrace", body=war)
    entry = await setup(hass)
    war["clan"]["participants"] = [{**participant(), "tag": "#R0J"}]
    provider.set("/v1/clans/#Q0G/currentriverrace", body=war)
    freezer.tick(timedelta(seconds=301))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(PREFIX + "river_race_fame").state == "12000"
    assert hass.states.get(PREFIX + "player_race_fame").state == "unavailable"
    assert (
        hass.states.get(PREFIX + "player_race_decks_used_today").state == "unavailable"
    )


async def test_changed_clan_preserves_ids(hass, provider, player, clan, war, freezer):
    entry = await setup(hass)
    registry = er.async_get(hass)
    original = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    player["clan"] = {"tag": "#R0J", "name": "New Synthetic Clan"}
    clan.update(tag="#R0J", members=21)
    war["clan"].update(tag="#R0J", fame=100)
    provider.set("/v1/players/#P0Y", body=player)
    provider.set("/v1/clans/#R0J", body=clan)
    provider.set("/v1/clans/#R0J/currentriverrace", body=war)
    freezer.tick(timedelta(seconds=301))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(PREFIX + "clan_members").state == "21"
    assert hass.states.get(PREFIX + "river_race_fame").state == "100"
    assert {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    } == original
    assert [p for p, _ in provider.requests[-3:]] == [
        "/v1/players/#P0Y",
        "/v1/clans/#R0J",
        "/v1/clans/#R0J/currentriverrace",
    ]


@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_optional_river_failure_keeps_player_clan(hass, provider, status):
    provider.set("/v1/clans/#Q0G/currentriverrace", status, {}, {"Retry-After": "120"})
    entry = await setup(hass)
    assert hass.states.get(PREFIX + "trophies").state == "7500"
    assert hass.states.get(PREFIX + "clan_members").state == "35"
    assert hass.states.get(PREFIX + "river_race_fame").state == "unavailable"
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert len(provider.requests) == 3


async def test_reload_and_unload_preserve_custom_entity(hass, provider):
    entry = await setup(hass)
    old = entry.runtime_data
    registry = er.async_get(hass)
    original = registry.async_get(PREFIX + "trophies")
    registry.async_update_entity(
        original.entity_id,
        new_entity_id="sensor.custom_game_score",
        name="My custom score",
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert old.retired and old.client.retired
    preserved = registry.async_get("sensor.custom_game_score")
    assert preserved.unique_id == original.unique_id and preserved.id == original.id
    assert hass.states.get("sensor.custom_game_score").state == "7500"
    assert len(provider.requests) == 3
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.custom_game_score").state == "unavailable"


async def test_manual_refresh_and_options_reload_preserve_budget(hass, provider):
    entry = await setup(hass)
    for _ in range(3):
        await entry.runtime_data.async_refresh()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 10}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(minutes=10)
    assert entry.data == INPUT
    assert len(provider.requests) == 3


async def test_native_scheduler_refreshes(hass, provider, freezer):
    entry = await setup(hass, {"scan_interval": 1})
    freezer.tick(timedelta(seconds=59))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(provider.requests) == 3
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(provider.requests) == 6
    assert entry.runtime_data.last_update_success


@pytest.mark.parametrize("bad", [None, True, "40", -1, 1.5, {}, []])
def test_invalid_numeric_fields_are_unknown(bad):
    sensor = next(s for s in SENSORS if s.key == "donations")
    assert sensor.value_fn({"player": {"donations": bad}}) is None


def test_no_invented_rank_boat_total_remaining_or_reset():
    assert not any(
        s.key
        in {"river_race_rank", "river_race_boat_attacks", "remaining_battles", "reset"}
        for s in SENSORS
    )
