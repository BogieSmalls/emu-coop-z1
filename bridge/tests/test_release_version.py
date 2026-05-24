import json
from pathlib import Path

from bridge_core import __version__


REPO_ROOT = Path(__file__).parents[2]


def _release_from_version_lua() -> str:
    text = (REPO_ROOT / "version.lua").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("release"):
            return stripped.split('"')[1]
    raise AssertionError("release not found in version.lua")


def test_bridge_core_version_matches_release_version_lua():
    assert __version__ == _release_from_version_lua()


def test_beta7_release_version_is_advertised():
    assert __version__ == "2.0 beta7"


def test_readme_and_release_notes_advertise_beta7_artifacts():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    release_notes = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")

    for text in (readme, release_notes):
        assert "z1rr-coop-2.0-beta7" in text
        assert "emu-coop-plus-2.0-beta7" not in text
        assert "2.0-beta6" not in text


def test_mister_payload_manifest_uses_release_version():
    manifest = json.loads(
        (REPO_ROOT / "bridge" / "bridge_core" / "mister_payload" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["helper"]["version"] == __version__
    assert manifest["core"]["version"] == __version__
