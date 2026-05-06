import io
import struct
from pathlib import Path

import pytest

from bridge_core import ips


def make_ips(records: list[tuple[int, bytes]]) -> bytes:
    """Build a minimal IPS file from (offset, data) records."""
    buf = b"PATCH"
    for offset, data in records:
        buf += offset.to_bytes(3, "big")
        buf += len(data).to_bytes(2, "big")
        buf += data
    buf += b"EOF"
    return buf


def test_parse_simple_patch():
    raw = make_ips([(0x0010, b"\xab\xcd"), (0x0100, b"\xff")])
    records = list(ips.parse(io.BytesIO(raw)))
    assert records == [(0x0010, b"\xab\xcd"), (0x0100, b"\xff")]


def test_apply_simple_patch():
    src = bytearray(b"\x00" * 256)
    raw = make_ips([(0x0010, b"\xab\xcd"), (0x0100, b"\xff")])
    out = ips.apply(bytes(src), raw)
    assert out[0x0010:0x0012] == b"\xab\xcd"
    assert out[0x0100] == 0xFF
    assert out[0x0000] == 0x00  # unchanged


def test_apply_extends_rom_if_needed():
    src = bytearray(b"\x00" * 256)
    raw = make_ips([(0x0300, b"\x42")])  # past end of src
    out = ips.apply(bytes(src), raw)
    assert len(out) >= 0x0301
    assert out[0x0300] == 0x42


def test_invalid_header_raises():
    with pytest.raises(ips.IPSError):
        ips.apply(b"\x00" * 16, b"NOPATCH...")


def test_zelda_cc_patch_loads():
    """The vendored Z1 CC patch should be parseable."""
    patch_path = Path(__file__).parent.parent / "bridge_core" / "patches" / "zelda_emu_coop_plus.ips"
    raw = patch_path.read_bytes()
    records = list(ips.parse(io.BytesIO(raw)))
    assert len(records) > 0


def test_is_patched_detects_applied():
    """If an IPS has been applied, is_patched should return True."""
    src = bytearray(b"\x00" * 1024)
    raw = make_ips([(0x0100, b"\xab\xcd")])
    patched = ips.apply(bytes(src), raw)
    assert ips.is_patched(patched, raw) is True
    assert ips.is_patched(bytes(src), raw) is False
