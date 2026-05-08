import json
from pathlib import Path

from bridge_core.user_settings import UserSettings, default_settings_path


def test_settings_default_mister_username_and_password(tmp_path: Path):
    settings = UserSettings.load(tmp_path / "missing.json")

    assert settings.mister_host == ""
    assert settings.mister_username == "root"
    assert settings.mister_password_default == "1"


def test_settings_remembers_mister_host_but_not_password(tmp_path: Path):
    path = tmp_path / "settings.json"
    settings = UserSettings.load(path)
    settings.mister_host = "192.168.1.50"
    settings.mister_username = "root"
    settings.mister_password = "secret"

    settings.save()

    raw = path.read_text(encoding="utf-8")
    assert "192.168.1.50" in raw
    assert "secret" not in raw
    assert json.loads(raw) == {
        "mister_host": "192.168.1.50",
        "mister_username": "root",
    }


def test_settings_loads_existing_mister_host_and_username(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "mister_host": "192.168.1.51",
                "mister_username": "admin",
                "mister_password": "do-not-load",
            }
        ),
        encoding="utf-8",
    )

    settings = UserSettings.load(path)

    assert settings.mister_host == "192.168.1.51"
    assert settings.mister_username == "admin"
    assert settings.mister_password_default == "1"
    assert settings.mister_password == "1"


def test_default_settings_path_uses_localappdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_settings_path() == (
        tmp_path / "emu-coop-plus" / "bridge-settings.json"
    )
