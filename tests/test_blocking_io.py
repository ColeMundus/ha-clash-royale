"""Setup and polling must not do blocking I/O on the event loop."""

import ast
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/clash_royale_war"
DOMAIN = "clash_royale_war"
INPUT = {"api_key": "synthetic-key", "player_tag": "#P0Y"}


def _integration_caller() -> str | None:
    frame = sys._getframe(2)
    filename = frame.f_code.co_filename.replace("\\", "/")
    if "/custom_components/clash_royale_war/" in filename:
        return f"{filename}:{frame.f_lineno} {frame.f_code.co_name}"
    return None


def test_integration_source_has_no_blocking_io_calls():
    """Reject zoneinfo, sync HTTP and file reads in the integration itself."""
    offenders: list[str] = []
    for path in sorted(COMPONENT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "zoneinfo" or alias.name.startswith(
                        ("requests", "urllib.request", "http.client")
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno} import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "zoneinfo" or node.module.startswith(
                    ("requests", "urllib.request", "http.client")
                ):
                    offenders.append(f"{path.name}:{node.lineno} from {node.module}")
                if node.module == "time" and any(
                    alias.name == "sleep" for alias in node.names
                ):
                    offenders.append(f"{path.name}:{node.lineno} time.sleep")
                if node.module == "pathlib" and any(
                    alias.name == "Path" for alias in node.names
                ):
                    offenders.append(f"{path.name}:{node.lineno} pathlib.Path")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"open", "ZoneInfo"}:
                    offenders.append(f"{path.name}:{node.lineno} {func.id}()")
                elif isinstance(func, ast.Attribute) and func.attr in {
                    "sleep",
                    "urlopen",
                    "listdir",
                    "walk",
                    "read_text",
                    "read_bytes",
                    "write_text",
                    "write_bytes",
                }:
                    offenders.append(f"{path.name}:{node.lineno} .{func.attr}()")
    assert offenders == []


@pytest.fixture
def record_blocking(monkeypatch):
    hits: list[str] = []

    def guard(label, original):
        def wrapped(*args, **kwargs):
            if caller := _integration_caller():
                hits.append(f"{label} from {caller}")
            return original(*args, **kwargs)

        return wrapped

    monkeypatch.setattr("builtins.open", guard("open", open))
    monkeypatch.setattr(time, "sleep", guard("sleep", time.sleep))
    import http.client
    import urllib.request
    import zoneinfo

    monkeypatch.setattr(
        http.client.HTTPConnection,
        "putrequest",
        guard("HTTPConnection.putrequest", http.client.HTTPConnection.putrequest),
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", guard("urlopen", urllib.request.urlopen)
    )
    monkeypatch.setattr(zoneinfo, "ZoneInfo", guard("ZoneInfo", zoneinfo.ZoneInfo))
    return hits


async def test_setup_refresh_and_retry_after_stay_off_the_event_loop(
    hass, provider, record_blocking, freezer
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}, data=INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    freezer.tick(timedelta(minutes=6))
    provider.set(
        "/v1/players/#P0Y",
        429,
        {},
        {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
    )
    before = len(provider.requests)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(provider.requests) > before
    assert record_blocking == []
