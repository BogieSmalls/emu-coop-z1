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
