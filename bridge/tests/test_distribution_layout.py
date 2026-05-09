from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def test_fceux_builder_writes_to_emu_dist_with_fceux_artifact_name():
    script = (REPO_ROOT / "build-fceux.ps1").read_text(encoding="utf-8")

    assert "dist\\emu" in script
    assert "emu-coop-plus-$version-fceux-win32" in script
    assert "emu-coop-plus-$version-fceux-win64" in script
    assert "dist\\fceux" not in script


def test_hardware_builder_writes_to_hardware_dist_with_hardware_artifact_name():
    script = (REPO_ROOT / "bridge" / "build-hardware.ps1").read_text(encoding="utf-8")

    assert "dist\\hardware" in script
    assert "emu-coop-plus-$version-hardware.exe" in script
    assert "dist\\edn8" not in script


def test_build_all_uses_generic_distribution_targets():
    script = (REPO_ROOT / "build-all.ps1").read_text(encoding="utf-8")

    assert "dist/hardware/emu-coop-plus-<version>-hardware.exe" in script
    assert "dist/emu/emu-coop-plus-<version>-fceux-win32.zip" in script
    assert "dist/emu/emu-coop-plus-<version>-fceux-win64.zip" in script
    assert 'label = "Hardware"' in script
    assert 'script = "bridge\\build-hardware.ps1"' in script
    assert "dist/edn8" not in script
    assert "dist/fceux" not in script


def test_legacy_edn8_builder_delegates_to_hardware_builder():
    script = (REPO_ROOT / "bridge" / "build-edn8.ps1").read_text(encoding="utf-8")

    assert "build-hardware.ps1" in script
