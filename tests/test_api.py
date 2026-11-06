"""Provider transport boundary, validation, backoff and privacy regressions."""

import logging
import socket
import time

import pytest
import pytest_socket
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.clash_royale_war.api import (
    ClashRoyaleClient,
    ClashRoyaleError,
    InvalidAuth,
    IPNotAllowed,
    NotFound,
    RateLimited,
    Retired,
    request_gate,
    retry_delay,
)
from custom_components.clash_royale_war.const import normalize_tag, validate_interval


@pytest.mark.parametrize("value", ["p0y", "#p0y", "  #P0Y  "])
def test_canonical_tag(value):
    assert normalize_tag(value) == "#P0Y"


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        "#",
        "##P0Y",
        "ABC",
        "#POY",
        "P0Y/war",
        "P0Y?x",
        "P0Y%20",
        "P0Y\nQ0G",
        "P" * 100,
    ],
)
def test_invalid_tag(value):
    with pytest.raises(ValueError):
        normalize_tag(value)


@pytest.mark.parametrize(
    "value", [True, False, 0, 61, 1.5, "5", None, float("nan"), float("inf")]
)
def test_interval_rejects_invalid(value):
    with pytest.raises(ValueError):
        validate_interval(value)


@pytest.mark.parametrize("value", [1, 5, 60, 5.0])
def test_interval_whole_minutes(value):
    assert validate_interval(value) == value


async def test_http_and_clan_endpoints(hass, provider):
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    assert (await client.async_get_player("p0y"))["name"] == "Synthetic Player"
    assert (await client.async_get_clan("q0g"))["members"] == 35
    assert (await client.async_get_current_river_race("q0g"))["clan"]["tag"] == "#Q0G"
    assert provider.requests == [
        ("/v1/players/#P0Y", "Bearer synthetic-key"),
        ("/v1/clans/#Q0G", "Bearer synthetic-key"),
        ("/v1/clans/#Q0G/currentriverrace", "Bearer synthetic-key"),
    ]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {}, InvalidAuth),
        (403, {}, InvalidAuth),
        (403, {"reason": "accessDenied.invalidIp"}, IPNotAllowed),
        (404, {}, NotFound),
        (500, {}, ClashRoyaleError),
        (302, {}, ClashRoyaleError),
        (200, [], ClashRoyaleError),
        (200, "not-json", ClashRoyaleError),
        (200, {"tag": "#Q0G"}, ClashRoyaleError),
    ],
)
async def test_http_errors(hass, provider, status, body, error):
    provider.set("/v1/players/#P0Y", status, body)
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    with pytest.raises(error):
        await client.async_get_player("#P0Y")


async def test_river_denial_is_auth_error_at_transport_boundary(hass, provider):
    provider.set("/v1/clans/#Q0G/currentriverrace", 403, {"reason": "accessDenied"})
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    with pytest.raises(InvalidAuth):
        await client.async_get_current_river_race("#Q0G")


@pytest.mark.parametrize("header", ["60", "1e308", "1e9999", "NaN", "garbage", "-10"])
async def test_429_extremes_are_bounded_and_shared(hass, provider, header):
    provider.set(
        "/v1/players/#P0Y", 429, {"message": "PRIVATE-CANARY"}, {"Retry-After": header}
    )
    gate = request_gate(hass, "synthetic-key")
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key", gate)
    before = time.monotonic()
    with pytest.raises(RateLimited):
        await client.async_get_player("#P0Y")
    assert before < gate.retry_until <= time.monotonic() + 86401
    replacement = ClashRoyaleClient(
        async_get_clientsession(hass),
        "synthetic-key",
        request_gate(hass, "synthetic-key"),
    )
    with pytest.raises(RateLimited):
        await replacement.async_get_player("#P0Y")
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "header",
    [
        None,
        "garbage",
        "NaN",
        "Mon, 01 Jan 1900 00:00:00 GMT",
        "Wed, 01 Jan 9999 00:00:00 GMT",
    ],
)
def test_retry_date_or_fallback(header):
    assert 1 <= retry_delay(header) <= 86400


async def test_retired_client_never_sends(hass, provider):
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    client.retired = True
    with pytest.raises(Retired):
        await client.async_get_player("#P0Y")
    assert provider.requests == []


async def test_transport_privacy(hass, provider, monkeypatch, caplog):
    client = ClashRoyaleClient(async_get_clientsession(hass), "KEY-PRIVATE-CANARY")

    def fail(*args, **kwargs):
        raise TimeoutError("KEY-PRIVATE-CANARY PLAYER-PRIVATE-CANARY")

    monkeypatch.setattr(client._session, "get", fail)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ClashRoyaleError) as exc:
        await client.async_get_player("#P0Y")
    logging.getLogger(__name__).debug(
        "Synthetic translated failure", exc_info=exc.value
    )
    assert "PRIVATE-CANARY" not in caplog.text
    assert exc.value.__suppress_context__


def test_external_sockets_are_blocked():
    with socket.socket() as connection:
        with pytest.raises(pytest_socket.SocketConnectBlockedError):
            connection.connect(("192.0.2.1", 443))


@pytest.mark.parametrize("endpoint", ["clan", "race"])
@pytest.mark.parametrize(
    "body", [{}, {"tag": "#R0J"}, {"clan": {"tag": "#R0J"}}, {"clan": []}]
)
async def test_optional_identity_validation(hass, provider, endpoint, body):
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    suffix = "/currentriverrace" if endpoint == "race" else ""
    provider.set(f"/v1/clans/#Q0G{suffix}", body=body)
    method = (
        client.async_get_current_river_race
        if endpoint == "race"
        else client.async_get_clan
    )
    with pytest.raises(ClashRoyaleError):
        await method("#Q0G")


async def test_timeout_and_redirect_protection(hass, provider, monkeypatch):
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    calls = []

    def timeout(*args, **kwargs):
        calls.append((args, kwargs))
        raise TimeoutError("PRIVATE-CANARY")

    monkeypatch.setattr(client._session, "get", timeout)
    with pytest.raises(ClashRoyaleError, match="Unable to communicate"):
        await client.async_get_player("#P0Y")
    kwargs = calls[0][1]
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 20
    assert kwargs["timeout"].connect == 10


async def test_retry_after_blocks_then_recovers(hass, provider, freezer):
    provider.set("/v1/players/#P0Y", 429, {}, {"Retry-After": "120"})
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    with pytest.raises(RateLimited):
        await client.async_get_player("#P0Y")
    freezer.tick(119)
    with pytest.raises(RateLimited):
        await client.async_get_player("#P0Y")
    assert len(provider.requests) == 1
    provider.set("/v1/players/#P0Y", body={"tag": "#P0Y", "trophies": 0})
    freezer.tick(1)
    assert (await client.async_get_player("#P0Y"))["trophies"] == 0
    assert len(provider.requests) == 2


async def test_invalid_o_never_sends_http(hass, provider):
    client = ClashRoyaleClient(async_get_clientsession(hass), "synthetic-key")
    with pytest.raises(ValueError):
        await client.async_get_player("#2JYJLOVG")
    assert not provider.requests
