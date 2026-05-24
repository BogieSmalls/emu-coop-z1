from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def test_gui_uses_taller_release_window_defaults():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "app.py").read_text(encoding="utf-8")

    assert 'WINDOW_GEOMETRY = "760x720"' in source
    assert "WINDOW_MIN_SIZE = (700, 560)" in source


def test_gui_uses_ganon_icon_asset():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "app.py").read_text(encoding="utf-8")

    assert (REPO_ROOT / "bridge" / "assets" / "ganon_blue.ico").is_file()
    assert 'APP_ICON = Path("assets/ganon_blue.ico")' in source
    assert "self._set_window_icon()" in source


def test_rom_setup_screen_is_scrollable_for_mister_deploy_flow():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "setup_screen.py").read_text(encoding="utf-8")

    assert "class ROMSetupScreen(ctk.CTkScrollableFrame):" in source


def test_relay_setup_defaults_to_public_hostname():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "relay_setup_screen.py").read_text(encoding="utf-8")

    assert 'DEFAULT_RELAY = "coop.z1rracing.com"' in source


def test_session_screen_has_diagnostics_tab_with_copy_button():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "session_screen.py").read_text(encoding="utf-8")

    assert 'self._tabs.add("Diagnostics")' in source
    assert "self._diagnostics_text" in source
    assert 'text="Copy Diagnostics"' in source
    assert "def _copy_diagnostics" in source
