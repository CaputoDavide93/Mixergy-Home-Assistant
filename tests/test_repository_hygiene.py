"""Public repository policy checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import struct

import yaml


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Job-level permissions may only narrow, never widen. Everything a job in
# this repository legitimately needs is read-only.
_READ_ONLY = {"read", "none"}


def _png_metadata(path: Path) -> tuple[int, int, int]:
    """Return width, height, and PNG color type from the IHDR chunk."""
    header = path.read_bytes()[:26]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    assert header[12:16] == b"IHDR", f"{path} has no leading IHDR chunk"
    width, height = struct.unpack(">II", header[16:24])
    return width, height, header[25]


def test_workflows_pin_actions_and_use_read_only_permissions() -> None:
    """CI dependencies must be immutable and tokens least-privileged."""
    action_ref = re.compile(r"^[^@]+@[0-9a-f]{40}$")

    # GitHub Actions executes both extensions; globbing only one would let a
    # future .yml workflow bypass every check here — and an empty match list
    # would pass vacuously.
    paths = sorted(WORKFLOWS.glob("*.yaml")) + sorted(WORKFLOWS.glob("*.yml"))
    assert paths, "no workflows found — glob is broken or directory moved"

    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        assert workflow.get("permissions") == {"contents": "read"}, path
        for job_name, job in workflow["jobs"].items():
            # Job-level permissions override the workflow default — the
            # standard way scopes get widened. Require any override to be
            # read-only too.
            for scope, level in (job.get("permissions") or {}).items():
                assert level in _READ_ONLY, (
                    f"{path}: job '{job_name}' widens '{scope}' to '{level}'"
                )
            for step in job.get("steps", []):
                if uses := step.get("uses"):
                    # Local composite actions ("./.github/actions/x") are
                    # pinned by the repo commit itself and cannot carry @sha.
                    if uses.startswith("./"):
                        continue
                    assert action_ref.fullmatch(uses), f"{path}: {uses}"


def test_local_artifacts_are_ignored() -> None:
    """Machine-specific environments must never enter the public repository."""
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".test_venv/" in ignored
    assert ".pytest_cache/" in ignored
    assert ".coverage" in ignored
    assert "htmlcov/" in ignored


def test_brand_assets_are_complete_and_distinct() -> None:
    """Ship one coherent icon/logo family at HA's exact dimensions."""
    brand = ROOT / "custom_components" / "mixergy_tank" / "brand"
    expected = {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "logo.png": (1000, 256),
        "logo@2x.png": (2000, 512),
        "dark_logo.png": (1000, 256),
        "dark_logo@2x.png": (2000, 512),
    }

    for name, dimensions in expected.items():
        path = brand / name
        assert path.is_file(), f"missing brand asset: {name}"
        width, height, color_type = _png_metadata(path)
        assert (width, height) == dimensions, name
        assert color_type == 6, f"{name} must be RGBA"

    hashes = {
        name: hashlib.sha256((brand / name).read_bytes()).hexdigest()
        for name in expected
    }
    assert hashes["icon.png"] != hashes["icon@2x.png"]
    assert hashes["logo.png"] != hashes["logo@2x.png"]
    assert hashes["dark_logo.png"] != hashes["dark_logo@2x.png"]
    assert hashes["logo.png"] != hashes["dark_logo.png"]

    # One transparent tank icon works on both themes; duplicate dark icons are
    # rejected by home-assistant/brands and would drift independently.
    assert not (brand / "dark_icon.png").exists()
    assert not (brand / "dark_icon@2x.png").exists()

    for source in ("icon.svg", "logo.svg", "dark_logo.svg", "banner.svg"):
        assert (ROOT / "assets" / source).is_file(), source

    manifest = json.loads((ROOT / "assets" / "brand-manifest.json").read_text())
    for name, expected_hash in manifest["sources"].items():
        path = ROOT / "assets" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash, name
    for name, expected_hash in manifest["outputs"].items():
        path = ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash, name
