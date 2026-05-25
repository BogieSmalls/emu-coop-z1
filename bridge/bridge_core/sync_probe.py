"""Small helpers for probing whether a mode is safe to sync."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunningProbeDetail:
    running: bool | None
    addr: int | None = None
    value: int | None = None


def endpoint_error(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def running_probe_ranges(mode: Any) -> list[tuple[int, int]] | None:
    addr = getattr(mode, "RUNNING_ADDR", None)
    if addr is None:
        return None
    return [(int(addr), 1)]


def read_running_probe(endpoint: Any, mode: Any, timeout_ms: int = 300) -> bool | None:
    return read_running_probe_detail(endpoint, mode, timeout_ms=timeout_ms).running


def read_running_probe_detail(
    endpoint: Any,
    mode: Any,
    timeout_ms: int = 300,
) -> RunningProbeDetail:
    ranges = running_probe_ranges(mode)
    if ranges is None:
        return RunningProbeDetail(running=True)
    addr = ranges[0][0]
    snapshot = endpoint.read_ranges(ranges, timeout_ms=timeout_ms)
    if snapshot is None:
        return RunningProbeDetail(running=None, addr=addr)
    raw_value = snapshot.get(addr)
    value = None if raw_value is None else int(raw_value) & 0xFF
    return RunningProbeDetail(
        running=bool(mode.is_running(snapshot)),
        addr=addr,
        value=value,
    )


def read_running_byte(endpoint: Any, mode: Any, timeout_ms: int = 200) -> bool | None:
    addr = getattr(mode, "RUNNING_ADDR", None)
    if addr is None:
        return True
    value = endpoint.read_byte(int(addr), timeout_ms=timeout_ms)
    if value is None:
        return None
    return bool(mode.is_running({int(addr): value}))
