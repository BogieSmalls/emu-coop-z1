"""IPS patch builder: emit an IPS file that transforms `original` into `modified`.

Inverse of `bridge_core.ips.parse`. Greedily emits one IPS record per contiguous
run of differing bytes; falls back to RLE when a run is a single repeated byte
and the savings are worth it.

Spec recap:
- Header: b"PATCH"
- Records: 3-byte big-endian offset, 2-byte big-endian length, length bytes data
  (length=0 means RLE: 2-byte big-endian count + 1-byte fill byte)
- Trailer: b"EOF"
- Records cannot start at offset 0x454F46 (the bytes "EOF" — IPS terminator
  ambiguity). If a diff requires that exact offset we shift one byte earlier.
"""
from __future__ import annotations

from typing import Iterator

EOF_OFFSET = 0x454F46  # ASCII "EOF" - illegal as an IPS record offset


def _diff_runs(orig: bytes, modified: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield (offset, payload) for each maximal contiguous run of differing bytes."""
    if len(modified) < len(orig):
        raise ValueError("modified must be at least as long as original (IPS doesn't shrink)")
    n = len(modified)
    i = 0
    while i < n:
        orig_byte = orig[i] if i < len(orig) else None
        if modified[i] != orig_byte:
            start = i
            while i < n and (i >= len(orig) or modified[i] != orig[i]):
                i += 1
            yield start, modified[start:i]
        else:
            i += 1


def _encode_record(offset: int, payload: bytes) -> bytes:
    """Encode one IPS record. Use RLE when it saves space (length=0 marker + 2B count + 1B fill)."""
    if not payload:
        raise ValueError("empty payload")
    if len(payload) > 0xFFFF:
        # split into chunks (IPS length is 16-bit)
        out = bytearray()
        chunk_size = 0xFFFF
        for chunk_start in range(0, len(payload), chunk_size):
            chunk = payload[chunk_start:chunk_start + chunk_size]
            out += _encode_record(offset + chunk_start, chunk)
        return bytes(out)
    if offset == EOF_OFFSET:
        raise ValueError(f"offset 0x{offset:06X} collides with IPS EOF marker; shift the modification by 1 byte")
    # Try RLE: only beneficial when payload is all the same byte AND length >= 4
    # (RLE encoding cost = 5 bytes header; raw cost = 5 + len; break-even at len=8 conservatively)
    use_rle = len(payload) >= 8 and len(set(payload)) == 1
    out = bytearray()
    out += offset.to_bytes(3, "big")
    if use_rle:
        out += (0).to_bytes(2, "big")  # length=0 marks RLE
        out += len(payload).to_bytes(2, "big")
        out += bytes((payload[0],))
    else:
        out += len(payload).to_bytes(2, "big")
        out += payload
    return bytes(out)


def make_ips(original: bytes, modified: bytes) -> bytes:
    """Build an IPS patch that transforms `original` into `modified`."""
    out = bytearray(b"PATCH")
    for offset, payload in _diff_runs(original, modified):
        out += _encode_record(offset, payload)
    out += b"EOF"
    return bytes(out)
