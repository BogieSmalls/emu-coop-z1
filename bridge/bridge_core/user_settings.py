from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any


def default_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "emu-coop-plus" / "bridge-settings.json"
    return Path.home() / ".emu-coop-plus" / "bridge-settings.json"


@dataclass
class UserSettings:
    path: Path = field(default_factory=default_settings_path)
    mister_host: str = ""
    mister_username: str = "root"
    mister_password: str = "1"

    @property
    def mister_password_default(self) -> str:
        return "1"

    @classmethod
    def load(cls, path: Path | None = None) -> "UserSettings":
        settings_path = path or default_settings_path()
        if not settings_path.exists():
            return cls(path=settings_path)

        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(path=settings_path)

        if not isinstance(data, dict):
            return cls(path=settings_path)

        return cls(
            path=settings_path,
            mister_host=_string_value(data.get("mister_host")),
            mister_username=_string_value(data.get("mister_username")) or "root",
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mister_host": self.mister_host.strip(),
            "mister_username": self.mister_username.strip() or "root",
        }
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
