from __future__ import annotations

from pathlib import Path
from typing import Any


DEVICE_EDN8 = "edn8"
DEVICE_MISTER = "mister"
AVAILABLE_DEVICES = [DEVICE_EDN8, DEVICE_MISTER]
DEFAULT_MISTER_USERNAME = "root"
DEFAULT_MISTER_PASSWORD = "1"
DEFAULT_MISTER_HELPER_PORT = 55355


def next_screen_for_device(device: str) -> str:
    normalized = device.strip().lower()
    if normalized in {DEVICE_EDN8, DEVICE_MISTER}:
        return "rom_setup"
    raise ValueError(f"unknown device: {device}")


def build_mister_rom_setup_config(
    *,
    rom_path: str | Path,
    remote_rom_path: str,
    host: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    return {
        "endpoint_type": DEVICE_MISTER,
        "rom_path": str(rom_path),
        "mister_remote_rom_path": remote_rom_path,
        "mister_host": host.strip(),
        "mister_username": username.strip() or DEFAULT_MISTER_USERNAME,
        "mister_password": password or DEFAULT_MISTER_PASSWORD,
        "mister_port": DEFAULT_MISTER_HELPER_PORT,
        "enable_writes": True,
    }


def build_session_config(
    *,
    endpoint_type: str,
    mode: str,
    relay: str,
    relay_port: int,
    code: str,
    com_port: str | None = None,
    force_send: bool = False,
    mister_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint = endpoint_type.strip().lower() or DEVICE_EDN8
    base = {
        "endpoint_type": endpoint,
        "mode": mode,
        "relay": relay,
        "relay_port": int(relay_port),
        "code": code.strip(),
        "force_send": bool(force_send),
    }

    if endpoint == DEVICE_EDN8:
        if not com_port:
            raise ValueError("com_port is required for EDN8")
        base["com_port"] = com_port
        return base

    if endpoint == DEVICE_MISTER:
        if not mister_config:
            raise ValueError("mister_config is required for MiSTer")
        config = {**base, **mister_config}
        config["endpoint_type"] = DEVICE_MISTER
        config.pop("com_port", None)
        return config

    raise ValueError(f"unknown endpoint type: {endpoint_type}")
