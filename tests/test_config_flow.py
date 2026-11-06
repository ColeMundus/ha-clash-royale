"""Native HA flow tests; only provider HTTP is replaced."""

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant.common import MockConfigEntry

DOMAIN = "clash_royale_war"
INPUT = {"api_key": "synthetic-key", "player_tag": "#P0Y"}


def entry_for(hass, **kwargs):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="#P0Y", data=INPUT.copy(), **kwargs
    )
    entry.add_to_hass(hass)
    return entry


def fields(result):
    return {str(key): key for key in result["data_schema"].schema}


async def test_setup_required_fields(hass, provider):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    assert set(fields(result)) == {"api_key", "player_tag"}
    assert all(type(key).__name__ == "Required" for key in fields(result).values())
    schema = result["data_schema"]
    assert schema.schema[fields(result)["api_key"]].config["type"] == "password"
    assert provider.requests == []


@pytest.mark.parametrize("tag", ["p0y", "#p0y", " #P0Y "])
async def test_create_canonical_player(hass, provider, tag):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "player_tag": tag}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == INPUT
    assert result["result"].unique_id == "#P0Y"
    await hass.async_block_till_done()
    assert result["result"].runtime_data.data["clan"]["tag"] == "#Q0G"


async def test_duplicate_before_http(hass, provider):
    entry_for(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={**INPUT, "player_tag": "p0y"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert provider.requests == []


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {}, "invalid_auth"),
        (403, {}, "invalid_auth"),
        (403, {"reason": "accessDenied.invalidIp"}, "ip_not_allowed"),
        (404, {}, "player_not_found"),
        (429, {}, "rate_limited"),
        (500, {}, "cannot_connect"),
        (200, [], "cannot_connect"),
    ],
)
async def test_setup_http_errors(hass, provider, status, body, error):
    provider.set("/v1/players/#P0Y", status, body)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("player_tag", "ABC", "invalid_tag"),
        ("player_tag", "P0Y/war", "invalid_tag"),
        ("player_tag", "POY", "invalid_tag"),
        ("player_tag", "#P0YO", "invalid_tag"),
    ],
)
async def test_setup_invalid_input_no_http(hass, provider, field, value, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={**INPUT, field: value},
    )
    assert result["errors"] == {field: error}
    assert provider.requests == []


async def test_interval_selector_renders_native_number(hass, provider):
    import probatio
    from homeassistant.helpers import config_validation as cv

    entry = entry_for(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    serialized = probatio.to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    interval = next(item for item in serialized if item["name"] == "scan_interval")
    assert interval["selector"]["number"]["unit_of_measurement"] == "min"
    assert interval["selector"]["number"]["min"] == 1
    assert interval["selector"]["number"]["max"] == 60
    assert interval["default"] == 5
    values = result["data_schema"]({"scan_interval": 5.0})
    assert type(values["scan_interval"]) is int


async def test_options_success(hass, provider):
    entry = entry_for(hass, options={"unrelated": "preserved"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert set(fields(result)) == {"scan_interval"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 10}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"unrelated": "preserved", "scan_interval": 10}
    assert entry.data == INPUT
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "value", [True, False, 0, 61, 1.5, "5", None, float("inf"), float("nan")]
)
async def test_options_strict_validation(hass, provider, value):
    entry = entry_for(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    try:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": value}
        )
    except InvalidData:
        pass  # Native schema rejection is also valid; configuration stays unchanged.
    else:
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"scan_interval": "invalid_interval"}
    assert entry.options == {}
    assert entry.data == INPUT
    assert provider.requests == []


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_reauth_failure_preserves_original(hass, provider, status):
    entry = entry_for(hass, options={"scan_interval": 10})
    provider.set("/v1/players/#P0Y", status, {"message": "PRIVATE-CANARY"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert set(fields(result)) == {"api_key"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "replacement-synthetic-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert entry.data == INPUT
    assert entry.options == {"scan_interval": 10}
    assert entry.unique_id == "#P0Y"


async def test_reauth_success(hass, provider):
    entry = entry_for(hass, options={"scan_interval": 10})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "replacement-synthetic-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {**INPUT, "api_key": "replacement-synthetic-key"}
    assert entry.options == {"scan_interval": 10}
    await hass.async_block_till_done()


async def test_reopened_setup_cannot_bypass_extreme_429(hass, provider):
    provider.set("/v1/players/#P0Y", 429, {}, {"Retry-After": "1e308"})
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=INPUT
    )
    hass.config_entries.flow.async_abort(first["flow_id"])
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=INPUT
    )
    assert second["errors"] == {"base": "rate_limited"}
    assert len(provider.requests) == 1


@pytest.mark.parametrize("missing", ["api_key", "player_tag"])
async def test_missing_required_field_rejected(hass, provider, missing):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    values = {key: value for key, value in INPUT.items() if key != missing}
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(result["flow_id"], values)
    assert provider.requests == []


async def test_cancelled_reauth_preserves_entry(hass, provider):
    entry = entry_for(hass, options={"scan_interval": 10})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    hass.config_entries.flow.async_abort(result["flow_id"])
    assert entry.data == INPUT
    assert entry.options == {"scan_interval": 10}
    assert provider.requests == []


@pytest.mark.parametrize("tag", ["#Q0G", "invalid", None])
async def test_reauth_wrong_or_malformed_player_preserves_entry(hass, provider, tag):
    entry = entry_for(hass, options={"scan_interval": 10})
    provider.set("/v1/players/#P0Y", body={"tag": tag})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "replacement-synthetic-key"}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == INPUT
    assert entry.options == {"scan_interval": 10}


async def test_user_and_reauth_serialized_password_fields(hass, provider):
    import probatio
    from homeassistant.helpers import config_validation as cv

    user = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = entry_for(hass)
    reauth = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    for result in (user, reauth):
        serialized = probatio.to_field_list(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )
        token = next(item for item in serialized if item["name"] == "api_key")
        assert token["selector"]["text"]["type"] == "password"
        assert "default" not in token
        assert (
            result["description_placeholders"].items()
            >= {
                "developer_portal": "https://developer.clashroyale.com/",
                "help_url": "https://github.com/ColeMundus/ha-clash-royale#create-an-api-key",
            }.items()
        )
    assert provider.requests == []


@pytest.mark.parametrize("minutes", [1, 5, 60, 5.0])
async def test_native_options_bounds_and_integer_storage(hass, provider, minutes):
    entry = entry_for(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": minutes}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": int(minutes)}
    assert type(entry.options["scan_interval"]) is int
    assert entry.data == INPUT


async def test_real_setup_unload_retires_runtime(hass, provider):
    from homeassistant.config_entries import ConfigEntryState

    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert entry.state is ConfigEntryState.LOADED
    assert not coordinator.retired
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator.retired
    assert coordinator.client.retired
    states = [
        state
        for state in hass.states.async_all()
        if state.entity_id.startswith("sensor.clash_royale_war")
    ]
    assert states
    assert all(state.state == "unavailable" for state in states)
    requests = len(provider.requests)
    await coordinator.async_request_refresh()
    assert len(provider.requests) == requests


async def test_real_loaded_entry_options_reload(hass, provider):
    from datetime import timedelta

    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    previous = entry.runtime_data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 10}
    )
    await hass.async_block_till_done()
    assert previous.retired
    assert entry.runtime_data is not previous
    assert entry.runtime_data.update_interval == timedelta(minutes=10)
    assert entry.data == INPUT


async def test_abort_inflight_reauth_preserves_entry(hass, provider):
    import asyncio

    entry = entry_for(hass, options={"scan_interval": 10, "custom": "preserved"})
    started = asyncio.Event()
    release = asyncio.Event()

    async def block(request):
        started.set()
        await release.wait()

    provider.before_response = block
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    task = asyncio.create_task(
        hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "replacement-synthetic-key"}
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    hass.config_entries.flow.async_abort(result["flow_id"])
    release.set()
    await hass.async_block_till_done()
    assert entry.data == INPUT
    assert entry.options == {"scan_interval": 10, "custom": "preserved"}
    assert entry.unique_id == "#P0Y"


@pytest.mark.parametrize("status", [200, 401, 429])
async def test_abort_inflight_reauth_without_cancelling_submission(
    hass, provider, status
):
    import asyncio
    from copy import deepcopy

    from homeassistant.helpers import entity_registry as er

    entry = entry_for(hass, options={"scan_interval": 10, "custom": "preserved"})
    hass.config_entries.async_update_entry(entry, data={**entry.data, "legacy": "kept"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime = entry.runtime_data
    registry = er.async_get(hass)
    entity = er.async_entries_for_config_entry(registry, entry.entry_id)[0]
    registry.async_update_entity(
        entity.entity_id, new_entity_id="sensor.custom_player", name="Custom player"
    )
    await hass.async_block_till_done()
    original_data, original_options = (
        deepcopy(dict(entry.data)),
        deepcopy(dict(entry.options)),
    )
    original_registry = dict(registry.entities)
    original_states = {
        state.entity_id: state.as_dict() for state in hass.states.async_all("sensor")
    }
    started, release = asyncio.Event(), asyncio.Event()

    async def block(request):
        started.set()
        await release.wait()

    provider.before_response = block
    if status != 200:
        provider.set("/v1/players/#P0Y", status, {"message": "PRIVATE-CANARY"})
    flow = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    task = asyncio.create_task(
        hass.config_entries.flow.async_configure(
            flow["flow_id"], {"api_key": "replacement-synthetic-key"}
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        hass.config_entries.flow.async_abort(flow["flow_id"])
        assert not task.cancelled()
        release.set()
        result = await task
        await hass.async_block_till_done()
        assert entry.data == original_data
        assert entry.options == original_options
        assert entry.runtime_data is runtime
        assert not runtime.retired
        assert dict(registry.entities) == original_registry
        assert {
            state.entity_id: state.as_dict()
            for state in hass.states.async_all("sensor")
        } == original_states
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] != "reauth_successful"
        assert hass.config_entries.flow.async_progress() == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "status, body",
    [
        (401, {}),
        (403, {"reason": "accessDenied.invalidIp"}),
        (404, {}),
        (429, {}),
        (500, {}),
        (200, {"tag": "#Q0G"}),
    ],
)
async def test_failed_reauth_preserves_loaded_runtime_and_registry(
    hass, provider, status, body
):
    from homeassistant.helpers import entity_registry as er

    entry = entry_for(hass, options={"scan_interval": 10, "custom": "preserved"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    entities = {
        (item.entity_id, item.unique_id)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    states = {state.entity_id: state.state for state in hass.states.async_all("sensor")}
    provider.set("/v1/players/#P0Y", status, body)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "replacement-synthetic-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert entry.data == INPUT
    assert entry.options == {"scan_interval": 10, "custom": "preserved"}
    assert entry.runtime_data is coordinator
    assert not coordinator.retired
    assert entities == {
        (item.entity_id, item.unique_id)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert states == {
        state.entity_id: state.state for state in hass.states.async_all("sensor")
    }


@pytest.mark.parametrize("failure", [False, RuntimeError("synthetic failure")])
async def test_platform_unload_failure_restores_runtime(
    hass, provider, monkeypatch, failure
):
    from unittest.mock import AsyncMock

    from custom_components.clash_royale_war import async_unload_entry

    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with monkeypatch.context() as scoped:
        mocked = AsyncMock(return_value=False)
        if isinstance(failure, Exception):
            mocked.side_effect = failure
        scoped.setattr(hass.config_entries, "async_unload_platforms", mocked)
        if isinstance(failure, Exception):
            with pytest.raises(RuntimeError, match="synthetic failure"):
                await async_unload_entry(hass, entry)
        else:
            assert not await async_unload_entry(hass, entry)
        assert not entry.runtime_data.retired
        assert not entry.runtime_data.client.retired
    assert await hass.config_entries.async_unload(entry.entry_id)
