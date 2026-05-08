from pathlib import Path

import pytest

from bridge_gui.device_flow import (
    DEFAULT_MISTER_HELPER_PORT,
    build_mister_rom_setup_config,
    next_screen_for_device,
)


def test_edn8_device_selection_routes_to_rom_setup():
    assert next_screen_for_device("edn8") == "rom_setup"


def test_mister_device_selection_routes_to_rom_setup():
    assert next_screen_for_device("mister") == "rom_setup"


def test_unknown_device_selection_is_rejected():
    with pytest.raises(ValueError, match="unknown device"):
        next_screen_for_device("unknown")


def test_mister_setup_config_uses_defaults_and_remembered_host():
    config = build_mister_rom_setup_config(
        rom_path="zelda.nes",
        remote_rom_path="/media/fat/games/NES/emu-coop-plus/zelda.nes",
        host=" 192.168.1.50 ",
        username="",
        password="",
    )

    assert config == {
        "endpoint_type": "mister",
        "rom_path": "zelda.nes",
        "mister_remote_rom_path": "/media/fat/games/NES/emu-coop-plus/zelda.nes",
        "mister_host": "192.168.1.50",
        "mister_username": "root",
        "mister_password": "1",
        "mister_port": DEFAULT_MISTER_HELPER_PORT,
        "enable_writes": True,
    }


def test_mister_setup_config_keeps_custom_credentials():
    config = build_mister_rom_setup_config(
        rom_path=Path("zelda.nes"),
        remote_rom_path="/media/fat/games/NES/emu-coop-plus/zelda.nes",
        host="mister.local",
        username="admin",
        password="secret",
    )

    assert config["rom_path"] == "zelda.nes"
    assert config["mister_host"] == "mister.local"
    assert config["mister_username"] == "admin"
    assert config["mister_password"] == "secret"
