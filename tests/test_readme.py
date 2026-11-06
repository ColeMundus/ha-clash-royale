"""Keep reader-facing docs accurate without real accounts or network access."""

import ast
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/clash_royale_war"


def test_readme_installation_and_minimal_setup():
    readme = (ROOT / "README.md").read_text()
    assert readme.index("## Installation") < readme.index("## Create an API key")
    assert "https://github.com/ColeMundus/ha-clash-royale" in readme
    assert "Home Assistant Core 2026.11.0" in readme
    assert "0.1.0" in readme
    assert "Custom repositories" in readme
    assert "has not been submitted" in readme
    assert "https://developer.clashroyale.com/" in readme
    assert "**API key**" in readme and "**Player tag**" in readme
    assert "Allowed IP addresses" in readme and "IP-bound" in readme
    assert "Only the API token and player tag are required" in readme
    assert "remaining-attacks estimate" in readme
    assert "reset countdown" in readme
    assert "not zero" in readme
    assert "player's reported medals" in readme
    assert "Colosseum score" in readme
    assert "No race rank is exposed" in readme
    for stale in ("Clash of Clans", "clash_of_clans", "ha-clash-of-clans"):
        assert stale not in readme


def test_sensor_table_matches_implemented_sensor_names():
    """Use AST, not HA imports: this check must stay offline and lightweight."""
    tree = ast.parse((COMPONENT / "sensor.py").read_text())
    sensors = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SENSORS"
            for target in node.targets
        )
    )
    assert isinstance(sensors, ast.Tuple)
    names = []
    for call in sensors.elts:
        assert isinstance(call, ast.Call)
        if isinstance(call.func, ast.Name) and call.func.id == "numeric":
            names.append(ast.literal_eval(call.args[1]))
        else:
            names.append(
                ast.literal_eval(
                    next(kw.value for kw in call.keywords if kw.arg == "name")
                )
            )
    readme = (ROOT / "README.md").read_text()
    table = readme.split("## Sensors\n", 1)[1].split("\n## ", 1)[0]
    documented = {
        name.strip().casefold()
        for line in table.splitlines()
        if line.startswith("| ")
        and line.count("|") == 3
        and line.split("|")[1].strip() not in {"Group", "---"}
        for name in line.split("|")[2].split(",")
    }
    assert documented == {name.casefold() for name in names}


def test_official_brand_asset_and_attribution():
    readme = (ROOT / "README.md").read_text()
    assert (
        '<img src="https://raw.githubusercontent.com/ColeMundus/ha-clash-royale/'
        'main/custom_components/clash_royale_war/brand/icon.png"' in readme
    )
    assert 'alt="Clash Royale War Tracker"' in readme
    with Image.open(COMPONENT / "brand/icon.png") as image:
        assert image.format == "PNG"
        assert image.size == (512, 512)
        assert not image.info
        image.verify()
    notice = (ROOT / "NOTICE.md").read_text()
    assert notice == (COMPONENT / "NOTICE.md").read_text()
    for attribution in (
        "Supercell Oy",
        "https://supercell.com/en/games/clashroyale/",
        "https://apps.apple.com/us/app/clash-royale/id1053012308",
        "https://itunes.apple.com/lookup?id=1053012308",
        "https://supercell.com/en/fan-content-policy/",
        "not the repository's MIT license",
        "This material is unofficial and is not endorsed by Supercell",
    ):
        assert attribution in notice
    assert "is1-ssl.mzstatic.com" in notice


def test_native_setup_screenshots_are_optional_and_metadata_free():
    """Omit screenshots until a real, sanitized native capture is available."""
    readme = (ROOT / "README.md").read_text()
    screenshots = re.findall(r"!\[[^\]]+\]\((docs/images/[^)]+)\)", readme)
    for name in screenshots:
        with Image.open(ROOT / name) as image:
            assert image.format == "PNG"
            assert 256 <= image.width <= 1600
            assert 256 <= image.height <= 2000
            assert not image.info
            image.verify()
    files = list((ROOT / "docs/images").glob("*.png"))
    assert {ROOT / path for path in screenshots} == set(files)
