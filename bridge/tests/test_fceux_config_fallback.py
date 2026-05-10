from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def test_fceux_builder_packages_editable_connection_config():
    script = (REPO_ROOT / "build-fceux.ps1").read_text(encoding="utf-8")
    config = (REPO_ROOT / "coop_config.lua").read_text(encoding="utf-8")

    assert '"coop_config.lua"' in script
    assert 'enabled = false' in config
    assert 'host_addr = "129.158.62.225"' in config
    assert 'code = ""' in config


def test_dialog_can_fall_back_to_connection_config_when_iup_is_unavailable():
    dialog = (REPO_ROOT / "dialog.lua").read_text(encoding="utf-8")

    assert "Must call iup.Open in main thread" in dialog
    assert "coop_config.lua" in dialog
    assert "loadConnectionConfig" in dialog
    assert "return normalized" in dialog
