from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def test_gui_uses_taller_beta5_window_defaults():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "app.py").read_text(encoding="utf-8")

    assert 'WINDOW_GEOMETRY = "760x720"' in source
    assert "WINDOW_MIN_SIZE = (700, 560)" in source


def test_rom_setup_screen_is_scrollable_for_mister_deploy_flow():
    source = (REPO_ROOT / "bridge" / "bridge_gui" / "setup_screen.py").read_text(encoding="utf-8")

    assert "class ROMSetupScreen(ctk.CTkScrollableFrame):" in source
