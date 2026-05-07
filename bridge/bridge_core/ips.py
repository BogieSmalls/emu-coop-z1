"""IPS patch format parser and applier.

IPS is a simple binary patch format:
- 5-byte header: b"PATCH"
- Records: 3-byte big-endian offset, 2-byte big-endian length, length bytes data
  (length=0 means RLE: 2-byte count + 1-byte fill byte)
- Trailer: b"EOF"
"""
from __future__ import annotations

import io
import json
from typing import BinaryIO, Iterator


class IPSError(Exception):
    pass


class RomConflict(Exception):
    """Raised by apply_validated when input ROM has unexpected bytes at one or
    more patch sites. The randomizer (or another modder) has changed bytes the
    patch needs to overwrite; applying anyway would silently corrupt that
    upstream change. mismatches is a list of (offset, expected, actual) tuples.
    """

    def __init__(self, mismatches: list[tuple[int, bytes, bytes]]) -> None:
        self.mismatches = mismatches
        offsets = ", ".join(f"0x{o:06X}" for o, _, _ in mismatches[:6])
        more = f" (+{len(mismatches) - 6} more)" if len(mismatches) > 6 else ""
        super().__init__(
            f"ROM conflicts with patch at {len(mismatches)} site(s): {offsets}{more}"
        )


def parse(stream: BinaryIO) -> Iterator[tuple[int, bytes]]:
    """Yield (offset, data) records from an IPS stream."""
    header = stream.read(5)
    if header != b"PATCH":
        raise IPSError(f"invalid IPS header: {header!r}")
    while True:
        offset_bytes = stream.read(3)
        if offset_bytes == b"EOF":
            return
        if len(offset_bytes) != 3:
            raise IPSError("unexpected end of patch (offset)")
        offset = int.from_bytes(offset_bytes, "big")
        length_bytes = stream.read(2)
        if len(length_bytes) != 2:
            raise IPSError("unexpected end of patch (length)")
        length = int.from_bytes(length_bytes, "big")
        if length == 0:
            # RLE: 2-byte count + 1-byte fill
            rle_count_bytes = stream.read(2)
            rle_fill_bytes = stream.read(1)
            if len(rle_count_bytes) != 2 or len(rle_fill_bytes) != 1:
                raise IPSError("unexpected end of patch (RLE)")
            count = int.from_bytes(rle_count_bytes, "big")
            data = rle_fill_bytes * count
        else:
            data = stream.read(length)
            if len(data) != length:
                raise IPSError("unexpected end of patch (data)")
        yield offset, data


def apply(rom_bytes: bytes, patch_bytes: bytes) -> bytes:
    """Apply IPS patch to ROM bytes; return new bytes."""
    out = bytearray(rom_bytes)
    for offset, data in parse(io.BytesIO(patch_bytes)):
        end = offset + len(data)
        if end > len(out):
            out.extend(b"\x00" * (end - len(out)))
        out[offset:end] = data
    return bytes(out)


def is_patched(rom_bytes: bytes, patch_bytes: bytes) -> bool:
    """Return True if rom_bytes already contains the bytes from patch_bytes."""
    for offset, data in parse(io.BytesIO(patch_bytes)):
        if offset + len(data) > len(rom_bytes):
            return False
        if rom_bytes[offset:offset + len(data)] != data:
            return False
    return True


def load_expected_manifest(manifest_bytes: bytes) -> dict[int, bytes]:
    """Decode an expected-vanilla manifest (JSON sidecar) into {offset: bytes}.

    The manifest is produced by relocate_patch.py at build time and ships next
    to the IPS. Schema:
        {
          "expected": {"0xNNNNNN": "<hex>", ...},
          ...
        }
    """
    data = json.loads(manifest_bytes)
    expected = data.get("expected") or {}
    return {int(k, 16): bytes.fromhex(v) for k, v in expected.items()}


def apply_validated(
    rom_bytes: bytes,
    patch_bytes: bytes,
    expected: dict[int, bytes],
) -> bytes:
    """Apply IPS patch only if every patch site in rom_bytes contains the
    expected vanilla bytes. Raises RomConflict listing every divergence.

    expected maps each IPS record offset to the bytes the input ROM should
    have at that offset. Generate it at build time from a vanilla ROM and
    ship it as a sidecar; see relocate_patch.py for the producer.
    """
    records = list(parse(io.BytesIO(patch_bytes)))
    mismatches: list[tuple[int, bytes, bytes]] = []
    for offset, data in records:
        end = offset + len(data)
        actual = bytes(rom_bytes[offset:end])
        want = expected.get(offset)
        if want is None or actual != want:
            mismatches.append((offset, want or b"", actual))
    if mismatches:
        raise RomConflict(mismatches)
    return apply(rom_bytes, patch_bytes)
