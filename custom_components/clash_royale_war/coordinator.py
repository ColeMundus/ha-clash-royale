"""Shared snapshots and polling deadlines, retained across entry reloads."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ClashRoyaleClient,
    ClashRoyaleError,
    InvalidAuth,
    RateLimited,
    Retired,
)
from .const import CONF_PLAYER_TAG, DEFAULT_SCAN_INTERVAL, DOMAIN, normalize_tag

_LOGGER = logging.getLogger(__name__)


@dataclass
class PollGate:
    """One polling budget per player, even during reload."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_poll: float = 0
    last_attempt: float | None = None
    snapshot: dict[str, Any] | None = None


class ClashRoyaleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Follow the player's current clan without changing entity identity."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: ClashRoyaleClient
    ) -> None:
        self.client = client
        self.player_tag = normalize_tag(entry.data[CONF_PLAYER_TAG])
        self.retired = False
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        self.poll_seconds = int(minutes) * 60
        gates = hass.data.setdefault(f"{DOMAIN}_poll_gates", {})
        self.gate: PollGate = gates.setdefault(self.player_tag, PollGate())
        if self.gate.last_attempt is not None:
            self.gate.next_poll = max(
                self.gate.next_poll, self.gate.last_attempt + self.poll_seconds
            )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )

    @callback
    def retire(self) -> None:
        """Reject queued HTTP and late publication before platform unload."""
        self.retired = True
        self.client.retired = True

    @callback
    def _schedule_refresh(self) -> None:
        """Rearm early Core timers at the retained deadline, not another period."""
        deadline = max(self.gate.next_poll, self.client.gate.retry_until)
        if deadline > time.monotonic():
            # Core rounds loop.time() down and adds jitter. One second avoids
            # running early without weakening manual/reload request pacing.
            self._retry_after = max(
                self._retry_after or 0,
                self.poll_seconds,
                deadline - time.monotonic() + 1,
            )
        super()._schedule_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        async with self.gate.lock:
            if self.retired:
                raise UpdateFailed("Runtime unloaded") from None
            if time.monotonic() < self.client.gate.retry_until:
                if self.gate.snapshot is not None:
                    return self.gate.snapshot
                raise UpdateFailed("Provider cooldown active") from None
            if time.monotonic() < self.gate.next_poll:
                if self.gate.snapshot is not None:
                    return self.gate.snapshot
                raise UpdateFailed("Polling cooldown active") from None
            # Reserve before I/O; unload/cancellation must not refund the budget.
            self.gate.snapshot = None
            self.gate.last_attempt = time.monotonic()
            self.gate.next_poll = self.gate.last_attempt + self.poll_seconds
            try:
                player = await self.client.async_get_player(self.player_tag)
                clan = river_race = None
                membership = player.get("clan")
                clan_tag = (
                    membership.get("tag") if isinstance(membership, dict) else None
                )
                if clan_tag:
                    # Each optional resource is fresh or absent; never carry a
                    # former clan/race into the current player's snapshot.
                    try:
                        clan_tag = normalize_tag(clan_tag)
                        clan = await self.client.async_get_clan(clan_tag)
                    except Retired:
                        raise
                    except ClashRoyaleError, ValueError:
                        pass
                    else:
                        try:
                            river_race = await self.client.async_get_current_river_race(
                                clan_tag
                            )
                        except Retired:
                            raise
                        except ClashRoyaleError:
                            pass
                if self.retired:
                    raise Retired("Runtime unloaded")
                snapshot = {"player": player, "clan": clan, "river_race": river_race}
                self.gate.snapshot = snapshot
                return snapshot
            except InvalidAuth:
                raise ConfigEntryAuthFailed(
                    "API key rejected; check key and IP allowlist"
                ) from None
            except RateLimited:
                raise UpdateFailed("Provider cooldown active") from None
            except ClashRoyaleError, ValueError:
                raise UpdateFailed(
                    "Unable to update Clash Royale War Tracker"
                ) from None
