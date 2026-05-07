"""Tiny MiSTer helper protocol for read-only emu-coop POCs."""
from __future__ import annotations

from typing import Any

from bridge_core.memory_endpoint import MemoryEndpoint


def handle_helper_request(request: dict[str, Any], endpoint: MemoryEndpoint) -> dict[str, Any]:
    op = request.get("op")
    if op == "read_ranges":
        ranges = _coerce_pairs(request.get("ranges", []))
        snapshot = endpoint.read_ranges(ranges)
        frame = getattr(endpoint, "last_frame", 0)
        if snapshot is None:
            return {"ok": False, "error": "mirror_busy_or_inactive", "frame": frame}
        return {
            "ok": True,
            "frame": frame,
            "values": [[addr, value] for addr, value in snapshot.items()],
        }
    if op == "read_byte":
        addr = int(request.get("addr", 0))
        value = endpoint.read_byte(addr)
        frame = getattr(endpoint, "last_frame", 0)
        if value is None:
            return {"ok": False, "error": "mirror_busy_or_inactive", "frame": frame}
        return {"ok": True, "frame": frame, "value": value}
    if op == "write_pairs":
        try:
            endpoint.write_pairs(_coerce_pairs(request.get("pairs", [])))
        except NotImplementedError:
            return {"ok": False, "error": "writes_not_supported"}
        return {"ok": True}
    return {"ok": False, "error": "unknown_op"}


def _coerce_pairs(raw_pairs: Any) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2:
            raise ValueError(f"invalid pair: {raw_pair!r}")
        pairs.append((int(raw_pair[0]), int(raw_pair[1])))
    return pairs
