from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]


def _pe_machine(path: Path) -> int:
    data = path.read_bytes()
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    return int.from_bytes(data[pe_offset + 4:pe_offset + 6], "little")


def test_bundled_fceux_native_modules_are_win32():
    """The current vendored DLLs only support 32-bit FCEUX."""
    for relative in ["iup.dll", "iuplua.dll", "socket/core.dll"]:
        assert _pe_machine(REPO_ROOT / relative) == 0x014C


def test_readme_names_32_bit_fceux_requirement():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "32-bit FCEUX" in readme
    assert "fceux-win32.zip" in readme


def test_dialog_handles_missing_or_wrong_bitness_iuplua_gracefully():
    dialog = (REPO_ROOT / "dialog.lua").read_text(encoding="utf-8")

    assert 'pcall(require, "iuplua")' in dialog
    assert "32-bit FCEUX" in dialog
    assert "not a valid Win32 application" in dialog
