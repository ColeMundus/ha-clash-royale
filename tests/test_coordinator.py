"""Coordinator snapshots, partial failure, cooldown and retirement regressions."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.clash_royale_war.api import ClashRoyaleClient, request_gate
from custom_components.clash_royale_war.coordinator import ClashRoyaleCoordinator


def coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain="clash_royale_war",
        unique_id="#P0Y",
        data={
            "api_key": "synthetic-key",
            "player_tag": "#P0Y",
            "scan_interval": 5,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    client = ClashRoyaleClient(
        async_get_clientsession(hass),
        "synthetic-key",
        request_gate(hass, "synthetic-key"),
    )
    return ClashRoyaleCoordinator(hass, entry, client)


async def test_snapshot_schema_and_shared_poll_cache(hass, provider):
    runtime = coordinator(hass)
    snapshot = await runtime._async_update_data()
    assert set(snapshot) == {"player", "clan", "river_race"}
    assert snapshot["river_race"]["clan"]["tag"] == "#Q0G"
    replacement = coordinator(hass)
    assert await replacement._async_update_data() is snapshot
    assert len(provider.requests) == 3


@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_clan_failure_keeps_player_no_old_race(hass, provider, status, freezer):
    runtime = coordinator(hass)
    await runtime._async_update_data()
    provider.set("/v1/clans/#Q0G", status, {}, {"Retry-After": "600"})
    freezer.tick(timedelta(seconds=301))
    snapshot = await runtime._async_update_data()
    assert snapshot["player"]["tag"] == "#P0Y"
    assert snapshot["clan"] is None and snapshot["river_race"] is None
    assert len(provider.requests) == 5
    assert await runtime._async_update_data() is snapshot
    assert len(provider.requests) == 5


@pytest.mark.parametrize(
    "status,error",
    [
        (401, ConfigEntryAuthFailed),
        (403, ConfigEntryAuthFailed),
        (404, UpdateFailed),
        (429, UpdateFailed),
        (500, UpdateFailed),
    ],
)
async def test_core_player_failure_rejects_old_snapshot(
    hass, provider, status, error, freezer
):
    runtime = coordinator(hass)
    await runtime._async_update_data()
    provider.set("/v1/players/#P0Y", status, {}, {"Retry-After": "100"})
    freezer.tick(timedelta(seconds=301))
    with pytest.raises(error):
        await runtime._async_update_data()
    assert runtime.gate.snapshot is None
    with pytest.raises(UpdateFailed):
        await runtime._async_update_data()
    assert len(provider.requests) == 4


@pytest.mark.parametrize("membership", [None, {}, [], {"tag": "#POY"}])
async def test_missing_or_invalid_membership_does_not_erase_player(
    hass, provider, player, membership
):
    player["clan"] = membership
    provider.set("/v1/players/#P0Y", body=player)
    snapshot = await coordinator(hass)._async_update_data()
    assert snapshot["player"]["trophies"] == 7500
    assert snapshot["clan"] is None and snapshot["river_race"] is None
    assert len(provider.requests) == 1


async def test_retire_discards_inflight_and_preserves_reserved_budget(
    hass, provider, freezer
):
    runtime = coordinator(hass)
    await runtime._async_update_data()
    started, release = asyncio.Event(), asyncio.Event()

    async def block(request):
        if request.path == "/v1/players/#P0Y":
            started.set()
            await release.wait()

    provider.before_response = block
    freezer.tick(timedelta(seconds=301))
    task = asyncio.create_task(runtime._async_update_data())
    try:
        await asyncio.wait_for(started.wait(), 2)
        runtime.retire()
        release.set()
        with pytest.raises(UpdateFailed):
            await task
        assert runtime.gate.snapshot is None
        replacement = coordinator(hass)
        with pytest.raises(UpdateFailed, match="Polling cooldown"):
            await replacement._async_update_data()
        assert len(provider.requests) == 4
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "status,phase",
    [
        (401, "headers"),
        (403, "headers"),
        (429, "headers"),
        (401, "body"),
        (403, "body"),
    ],
)
@pytest.mark.parametrize("replace", [False, True])
async def test_native_unload_discards_delayed_error(
    hass, provider, freezer, monkeypatch, caplog, status, phase, replace
):
    import time
    from copy import deepcopy

    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(
        domain="clash_royale_war",
        unique_id="#P0Y",
        data={"api_key": "synthetic-key", "player_tag": "#P0Y"},
        options={"scan_interval": 5, "custom": "preserved"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    registry = er.async_get(hass)
    original_data, original_options = dict(entry.data), dict(entry.options)
    original_registry = dict(registry.entities)
    started, release = asyncio.Event(), asyncio.Event()

    async def block(request):
        started.set()
        await release.wait()

    if phase == "headers":
        provider.before_response = block
    else:
        import aiohttp

        real_json = aiohttp.ClientResponse.json

        async def blocked_json(response, *args, **kwargs):
            if response.status in (401, 403):
                started.set()
                await release.wait()
            return await real_json(response, *args, **kwargs)

        monkeypatch.setattr(aiohttp.ClientResponse, "json", blocked_json)
    provider.set(
        "/v1/players/#P0Y",
        status,
        {"reason": "accessDenied.invalidIp", "message": "PRIVATE-CANARY"},
        {"Retry-After": "600"},
    )
    freezer.tick(301)
    task = asyncio.create_task(runtime.async_refresh())
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert runtime.retired
        release.set()
        await task
        await hass.async_block_till_done()
        assert hass.config_entries.flow.async_progress() == []
        assert runtime.gate.snapshot is None
        assert entry.data == original_data
        assert entry.options == original_options
        assert dict(registry.entities) == original_registry
        if status == 429:
            assert runtime.client.gate.retry_until == time.monotonic() + 600
        if replace:
            # A successor can refresh only after the retained request budget.
            provider.before_response = None
            provider.set("/v1/players/#P0Y", body={"tag": "#P0Y", "trophies": 123})
            freezer.tick(601)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            successor = entry.runtime_data
            assert successor is not runtime
            assert not successor.retired
            successor_data = deepcopy(successor.data)
            await runtime.async_refresh()
            await hass.async_block_till_done()
            assert entry.runtime_data is successor
            assert successor.data == successor_data
            assert hass.config_entries.flow.async_progress() == []
        assert len(provider.requests) == (5 if replace else 4)
        assert "PRIVATE-CANARY" not in caplog.text
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("minutes,deadline", [(10, 600), (1, 300)])
async def test_interval_reload_never_shortens_reserved_deadline(
    hass, provider, freezer, minutes, deadline
):
    runtime = coordinator(hass)
    await runtime._async_update_data()
    started = runtime.gate.last_attempt
    freezer.tick(timedelta(seconds=30))
    replacement = coordinator(hass, {"scan_interval": minutes})
    assert replacement.gate.next_poll == started + deadline
    assert await replacement._async_update_data() is runtime.gate.snapshot
    assert len(provider.requests) == 3
