"""Artifact acceptance and fail-closed packaging tests."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.build_artifact import MAX_FILE, PREFIX, REQUIRED, build, validate_member

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", ["LICENSE"])
def test_source_download_includes_notices(filename):
    """HACS downloads the component subtree, not repository-root notices."""
    assert (ROOT / PREFIX / filename).read_bytes() == (ROOT / filename).read_bytes()


@pytest.fixture
def package_source(tmp_path):
    root = tmp_path / "source"
    shutil.copytree(
        ROOT / "custom_components",
        root / "custom_components",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for filename in ["LICENSE"]:
        shutil.copyfile(ROOT / filename, root / filename)
    return root


def test_build_reproducible_complete_and_importable(package_source, tmp_path):
    archive, count, digest = build(package_source, tmp_path / "first")
    again, _, again_digest = build(package_source, tmp_path / "second")
    assert archive.read_bytes() == again.read_bytes()
    assert digest == again_digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    version = json.loads((package_source / PREFIX / "manifest.json").read_text())[
        "version"
    ]
    assert archive.name == f"clash_royale_war-{version}.zip"
    assert archive.with_suffix(".zip.sha256").read_text() == (
        f"{digest}  {archive.name}\n"
    )
    assert count == len(REQUIRED) + 1
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {
            PREFIX + name for name in REQUIRED | {"LICENSE"}
        }
        bundle.extractall(tmp_path / "installed")
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import custom_components.clash_royale_war.sensor as sensor; import custom_components.clash_royale_war.config_flow; assert sensor.DOMAIN == 'clash_royale_war'; print(sensor.__file__)",
        ],
        cwd=tmp_path / "installed",
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert str(tmp_path / "installed") in result.stdout


@pytest.mark.parametrize(
    "name",
    [
        "../api.py",
        "/api.py",
        PREFIX + "../api.py",
        PREFIX + "secret.env",
        PREFIX + "tests/test_api.py",
        PREFIX + r"brand\icon.png",
        "custom_components/other/api.py",
    ],
)
def test_paths_fail_closed(name):
    with pytest.raises(ValueError):
        validate_member(name, b"pass")


def test_size_limit():
    with pytest.raises(ValueError, match="size limit"):
        validate_member(PREFIX + "api.py", b"x" * (MAX_FILE + 1))


def test_credentials_rejected():
    credential = b"eyJ" + b"x" * 30 + b"." + b"y" * 30 + b"." + b"z" * 30
    with pytest.raises(ValueError, match="credential"):
        validate_member(PREFIX + "LICENSE", credential)


@pytest.mark.parametrize(
    "filename", ["brand/icon.png", "translations/en.json", "manifest.json"]
)
def test_missing_runtime_file_rejected(package_source, tmp_path, filename):
    (package_source / PREFIX / filename).unlink()
    with pytest.raises(ValueError, match="Missing required"):
        build(package_source, tmp_path / "dist")


@pytest.mark.parametrize("filename", ["LICENSE"])
def test_missing_notice_rejected(package_source, tmp_path, filename):
    (package_source / filename).unlink()
    with pytest.raises(FileNotFoundError):
        build(package_source, tmp_path / "dist")


def test_unapproved_extra_file_rejected(package_source, tmp_path):
    (package_source / PREFIX / "secrets.yaml").write_text("synthetic: true")
    with pytest.raises(ValueError, match="Unapproved"):
        build(package_source, tmp_path / "dist")


def test_symlink_rejected(package_source, tmp_path):
    target = package_source / PREFIX / "api.py"
    target.unlink()
    target.symlink_to(ROOT / PREFIX / "api.py")
    with pytest.raises(ValueError, match="Symlinks"):
        build(package_source, tmp_path / "dist")


def test_translation_matches_source():
    assert json.loads((ROOT / PREFIX / "strings.json").read_text()) == json.loads(
        (ROOT / PREFIX / "translations/en.json").read_text()
    )


@pytest.mark.parametrize("filename", ["LICENSE"])
@pytest.mark.parametrize("missing", [False, True])
def test_component_notices_required_and_matching(
    package_source, tmp_path, filename, missing
):
    notice = package_source / PREFIX / filename
    if missing:
        notice.unlink()
    else:
        notice.write_text("Outdated component notice")
    with pytest.raises(ValueError, match="notice does not match"):
        build(package_source, tmp_path / "dist")


@pytest.mark.parametrize("version", ["../bad", "v0.1.0", "", "0.1"])
def test_invalid_version_rejected(package_source, tmp_path, version):
    path = package_source / PREFIX / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = version
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity/version"):
        build(package_source, tmp_path / "dist")


def test_wrong_domain_rejected(package_source, tmp_path):
    path = package_source / PREFIX / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["domain"] = "unrelated_domain"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity/version"):
        build(package_source, tmp_path / "dist")


def test_metadata_agrees_with_distribution():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = json.loads((ROOT / PREFIX / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert project["name"] == "ha-clash-royale"
    assert project["version"] == manifest["version"]
    assert manifest["domain"] == "clash_royale_war"
    assert manifest["name"] == hacs["name"] == "Clash Royale War Tracker"
    assert manifest["documentation"] == "https://github.com/ColeMundus/ha-clash-royale"
    assert manifest["issue_tracker"] == manifest["documentation"] + "/issues"
    assert hacs["homeassistant"] == "2026.11.0"
    # Default HACS source extraction needs component-local legal files; the
    # manual ZIP intentionally has a different full custom_components layout.
    assert not hacs.get("zip_release", False)


def test_player_tag_field_explains_format_and_location():
    from custom_components.clash_royale_war.const import normalize_tag

    strings = json.loads((ROOT / PREFIX / "strings.json").read_text())
    help_text = strings["config"]["step"]["user"]["data_description"]["player_tag"]
    assert "player profile" in help_text
    assert "below your name" in help_text
    assert "# optional" in help_text
    assert "#P0Y28Q" in help_text
    assert normalize_tag("p0y28q") == "#P0Y28Q"
