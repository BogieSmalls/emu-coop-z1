from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_MACHINE_AMD64 = 0x8664


def _pe_machine(path: Path) -> int:
    data = path.read_bytes()
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    return int.from_bytes(data[pe_offset + 4:pe_offset + 6], "little")


def _pe_imports(path: Path) -> set[str]:
    data = path.read_bytes()
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    optional_offset = pe_offset + 24
    optional_magic = int.from_bytes(data[optional_offset:optional_offset + 2], "little")
    if optional_magic == 0x10B:
        data_directory_offset = optional_offset + 96
    elif optional_magic == 0x20B:
        data_directory_offset = optional_offset + 112
    else:
        raise AssertionError(f"Unexpected PE optional header magic {optional_magic:#x} in {path}")

    import_rva = int.from_bytes(
        data[data_directory_offset + 8:data_directory_offset + 12],
        "little",
    )
    if import_rva == 0:
        return set()

    section_count = int.from_bytes(data[pe_offset + 6:pe_offset + 8], "little")
    optional_size = int.from_bytes(data[pe_offset + 20:pe_offset + 22], "little")
    section_offset = optional_offset + optional_size

    sections = []
    for index in range(section_count):
        offset = section_offset + (index * 40)
        virtual_size = int.from_bytes(data[offset + 8:offset + 12], "little")
        virtual_address = int.from_bytes(data[offset + 12:offset + 16], "little")
        raw_size = int.from_bytes(data[offset + 16:offset + 20], "little")
        raw_pointer = int.from_bytes(data[offset + 20:offset + 24], "little")
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

    def rva_to_offset(rva: int) -> int:
        for virtual_address, size, raw_pointer in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_pointer + (rva - virtual_address)
        raise AssertionError(f"RVA {rva:#x} not mapped in {path}")

    imports = set()
    descriptor_offset = rva_to_offset(import_rva)
    while True:
        descriptor = data[descriptor_offset:descriptor_offset + 20]
        if descriptor == b"\0" * 20:
            break
        name_rva = int.from_bytes(descriptor[12:16], "little")
        name_offset = rva_to_offset(name_rva)
        end = data.index(b"\0", name_offset)
        imports.add(data[name_offset:end].decode("ascii").lower())
        descriptor_offset += 20

    return imports


def test_bundled_fceux_native_modules_include_win32_and_win64():
    """Each FCEUX package must carry native modules matching its process bitness."""
    for relative in ["iup.dll", "iuplua.dll", "socket/core.dll"]:
        assert _pe_machine(REPO_ROOT / relative) == IMAGE_FILE_MACHINE_I386

    for relative in [
        "native/fceux-win64/iup.dll",
        "native/fceux-win64/iuplua.dll",
        "native/fceux-win64/socket/core.dll",
    ]:
        assert _pe_machine(REPO_ROOT / relative) == IMAGE_FILE_MACHINE_AMD64


def test_win64_fceux_lua_modules_link_against_lua51_abi():
    """FCEUX 2.6.x embeds Lua 5.1, so win64 Lua modules must import its Lua DLL ABI."""
    iuplua_imports = _pe_imports(REPO_ROOT / "native/fceux-win64/iuplua.dll")
    socket_imports = _pe_imports(REPO_ROOT / "native/fceux-win64/socket/core.dll")
    lua51_dll_names = {"lua5.1.dll", "lua51.dll"}

    assert "iup.dll" in iuplua_imports
    assert iuplua_imports & lua51_dll_names
    assert socket_imports & lua51_dll_names


def test_readme_names_32_bit_fceux_requirement():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "32-bit FCEUX" in readme
    assert "fceux-win32.zip" in readme
    assert "64-bit FCEUX" in readme
    assert "fceux-win64.zip" in readme


def test_dialog_handles_missing_or_wrong_bitness_iuplua_gracefully():
    dialog = (REPO_ROOT / "dialog.lua").read_text(encoding="utf-8")

    assert 'pcall(require, "iuplua")' in dialog
    assert "32-bit FCEUX" in dialog
    assert "not a valid Win32 application" in dialog
