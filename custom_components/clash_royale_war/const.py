"""Constants and strict input validation for Clash Royale War Tracker."""

import re

DOMAIN = "clash_royale_war"
CONF_PLAYER_TAG = "player_tag"
DEFAULT_SCAN_INTERVAL = 5
API_BASE = "https://api.clashroyale.com/v1"
PLATFORMS = ["sensor"]


def normalize_tag(value: object) -> str:
    """Canonicalize a player or clan tag without allowing URL components."""
    if not isinstance(value, str):
        raise ValueError("Invalid tag")
    tag = value.strip().upper().removeprefix("#")
    if not re.fullmatch(r"[0289PYLQGRJCUV]{3,15}", tag):
        raise ValueError("Invalid tag")
    return f"#{tag}"


def validate_interval(value: object) -> int:
    """Accept only whole minutes, never booleans or fractional values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid interval")
    if not 1 <= value <= 60 or int(value) != value:
        raise ValueError("Invalid interval")
    return int(value)
