"""Native player, followed-clan, and current river-race metrics."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClashRoyaleConfigEntry
from .const import DOMAIN, normalize_tag
from .coordinator import ClashRoyaleCoordinator


def value_at(data: dict[str, Any], section: str, key: str) -> Any:
    """Missing source sections and fields are unknown, never zero."""
    source = data.get(section)
    return source.get(key) if isinstance(source, dict) else None


def race_clan(data: dict[str, Any]) -> dict[str, Any]:
    """Use only the current clan's race object, not rivals or stale membership."""
    membership = value_at(data, "player", "clan")
    race = value_at(data, "river_race", "clan")
    if not isinstance(membership, dict) or not isinstance(race, dict):
        return {}
    try:
        if normalize_tag(membership.get("tag")) == normalize_tag(race.get("tag")):
            return race
    except ValueError:
        pass
    return {}


def race_participant(data: dict[str, Any]) -> dict[str, Any]:
    """Only the configured player's participant in their current clan counts."""
    participants = race_clan(data).get("participants")
    if not isinstance(participants, list):
        return {}
    try:
        tag = normalize_tag(value_at(data, "player", "tag"))
    except ValueError:
        return {}
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        try:
            if normalize_tag(participant.get("tag")) == tag:
                return participant
        except ValueError:
            continue
    return {}


@dataclass(frozen=True, kw_only=True)
class ClashRoyaleSensorDescription(SensorEntityDescription):
    """One provider-native value per stable metric."""

    value_fn: Callable[[dict[str, Any]], Any]


def numeric(
    key: str,
    name: str,
    section: str,
    field: str,
    icon: str,
) -> ClashRoyaleSensorDescription:
    """Counters can reset; use measurement, not a fabricated lifetime total."""

    def value(data: dict[str, Any]) -> int | None:
        if section == "race_clan":
            result = race_clan(data).get(field)
        elif section == "participant":
            result = race_participant(data).get(field)
        else:
            result = value_at(data, section, field)
        # The official metrics are integer counts; malformed values are unknown.
        return result if type(result) is int and result >= 0 else None

    return ClashRoyaleSensorDescription(
        key=key,
        name=name,
        icon=icon,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=value,
    )


SENSORS = (
    numeric("trophies", "Trophies", "player", "trophies", "mdi:trophy"),
    numeric(
        "best_trophies", "Best trophies", "player", "bestTrophies", "mdi:trophy-award"
    ),
    numeric("exp_level", "XP level", "player", "expLevel", "mdi:star-circle"),
    numeric("exp_points", "XP points", "player", "expPoints", "mdi:star-plus"),
    numeric("wins", "Wins", "player", "wins", "mdi:sword"),
    numeric("losses", "Losses", "player", "losses", "mdi:shield-off"),
    numeric("battle_count", "Battle count", "player", "battleCount", "mdi:sword-cross"),
    numeric("donations", "Donations", "player", "donations", "mdi:hand-heart"),
    numeric(
        "donations_received",
        "Donations received",
        "player",
        "donationsReceived",
        "mdi:gift",
    ),
    numeric("clan_members", "Clan members", "clan", "members", "mdi:account-group"),
    numeric("clan_score", "Clan score", "clan", "clanScore", "mdi:counter"),
    numeric(
        "clan_war_trophies",
        "Clan war trophies",
        "clan",
        "clanWarTrophies",
        "mdi:shield-star",
    ),
    numeric("river_race_fame", "River race fame", "race_clan", "fame", "mdi:medal"),
    numeric(
        "river_race_repair_points",
        "River race repair points",
        "race_clan",
        "repairPoints",
        "mdi:hammer-wrench",
    ),
    numeric(
        "player_race_fame", "Player race fame", "participant", "fame", "mdi:medal-star"
    ),
    numeric(
        "player_race_repair_points",
        "Player race repair points",
        "participant",
        "repairPoints",
        "mdi:tools",
    ),
    numeric(
        "player_race_boat_attacks",
        "Player race boat attacks",
        "participant",
        "boatAttacks",
        "mdi:ferry",
    ),
    numeric(
        "player_race_decks_used",
        "Player race decks used",
        "participant",
        "decksUsed",
        "mdi:cards",
    ),
    numeric(
        "player_race_decks_used_today",
        "Player race decks used today",
        "participant",
        "decksUsedToday",
        "mdi:cards-playing",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClashRoyaleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose optional metrics as unavailable until the provider supplies them."""
    async_add_entities(
        ClashRoyaleSensor(entry.runtime_data, description) for description in SENSORS
    )


class ClashRoyaleSensor(CoordinatorEntity[ClashRoyaleCoordinator], SensorEntity):
    """Player-scoped identity remains stable across clan changes and reloads."""

    _attr_has_entity_name = True
    entity_description: ClashRoyaleSensorDescription

    def __init__(
        self,
        coordinator: ClashRoyaleCoordinator,
        description: ClashRoyaleSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.player_tag}_{description.key}"

    @property
    def suggested_object_id(self) -> str:
        """Core prepends the service-branded device name to this local suffix."""
        return self.entity_description.key

    @property
    def device_info(self) -> DeviceInfo:
        player = (self.coordinator.data or {}).get("player") or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.player_tag)},
            name=(
                "Clash Royale War Tracker "
                f"{player.get('name', self.coordinator.player_tag)}"
            ),
            manufacturer="Supercell",
            model="Clash Royale War Tracker player",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
