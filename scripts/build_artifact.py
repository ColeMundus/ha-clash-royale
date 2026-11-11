"""Build a bounded, reproducible manual-install ZIP; never publish it."""

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image

DOMAIN = "clash_royale_war"
PREFIX = f"custom_components/{DOMAIN}/"
REQUIRED = {
    "__init__.py",
    "api.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "sensor.py",
    "manifest.json",
    "strings.json",
    "translations/en.json",
    "brand/icon.png",
}
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 5 * 1024 * 1024
SECRET = re.compile(
    rb"(?:eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]+"
    rb"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    rb"|gh[pousr]_[A-Za-z0-9]{30,})"
)


def validate_member(name, data):
    """Reject unknown paths, oversized payloads and recognizable credentials."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe archive path")
    local = name.removeprefix(PREFIX)
    if not name.startswith(PREFIX) or local not in REQUIRED | {"LICENSE"}:
        raise ValueError(f"Unapproved archive member: {name}")
    if len(data) > MAX_FILE:
        raise ValueError("Artifact member exceeds size limit")
    if not local.endswith(".png") and SECRET.search(data):
        raise ValueError("Possible credential in artifact")
    if local.endswith(".py"):
        compile(data, name, "exec")
    if local.endswith(".json"):
        json.loads(data)
    if local == "brand/icon.png":
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size not in {(256, 256), (512, 512)}:
                raise ValueError("Expected square 256px or 512px PNG brand icon")
            image.verify()


def build(root: Path, output: Path):
    component = root / "custom_components" / DOMAIN
    if component.is_symlink() or (root / "custom_components").is_symlink():
        raise ValueError("Symlinks are not permitted")
    files = {}
    for path in component.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are not permitted")
        if path.is_file():
            local = path.relative_to(component).as_posix()
            name = PREFIX + local
            data = path.read_bytes()
            validate_member(name, data)
            files[name] = data
    missing = REQUIRED - {name.removeprefix(PREFIX) for name in files}
    if missing:
        raise ValueError(f"Missing required runtime files: {sorted(missing)}")
    for notice in ("LICENSE",):
        path = root / notice
        if path.is_symlink():
            raise ValueError("Symlink notice")
        data = path.read_bytes()
        if not data.strip():
            raise ValueError("Empty notice")
        validate_member(PREFIX + notice, data)
        if files.get(PREFIX + notice) != data:
            raise ValueError("Component notice does not match repository notice")
        files[PREFIX + notice] = data
    manifest = json.loads(files[PREFIX + "manifest.json"])
    version = manifest["version"]
    if manifest["domain"] != DOMAIN or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:b\d+)?", version
    ):
        raise ValueError("Unexpected integration identity/version")
    if sum(map(len, files.values())) > MAX_TOTAL:
        raise ValueError("Artifact exceeds total size limit")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"clash_royale_war-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() or set(bundle.namelist()) != set(files):
            raise ValueError("Artifact verification failed")
        for name in bundle.namelist():
            if bundle.read(name) != files[name]:
                raise ValueError("Artifact content mismatch")
            validate_member(name, bundle.read(name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    return archive, len(files), digest


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    archive, count, digest = build(root, root / "dist")
    print(f"Verified {archive.name}: {count} allowlisted members, sha256={digest}")
