"""MiSTer helper and mirror health checks."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bridge_core.mister_helper import MisterHelperMemoryEndpoint
from bridge_core.sync_probe import endpoint_error


@dataclass(frozen=True)
class MisterHelperHealth:
    helper_reachable: bool
    mirror_ok: bool
    addr: int
    value: int | None
    frame: int
    running: bool | None
    error: str | None


def probe_mister_helper(
    host: str,
    *,
    port: int = 55355,
    timeout: float = 1.0,
    mode: Any | None = None,
    addr: int = 0x0012,
    endpoint_factory: Callable[..., Any] = MisterHelperMemoryEndpoint,
) -> MisterHelperHealth:
    endpoint = endpoint_factory(host=host, port=port, timeout=timeout)
    try:
        value = endpoint.read_byte(addr, timeout_ms=300)
    except Exception as exc:
        return MisterHelperHealth(
            helper_reachable=False,
            mirror_ok=False,
            addr=addr,
            value=None,
            frame=int(getattr(endpoint, "last_frame", 0)),
            running=None,
            error=endpoint_error(exc),
        )
    finally:
        close = getattr(endpoint, "close", None)
        if close is not None:
            close()

    frame = int(getattr(endpoint, "last_frame", 0))
    if value is None:
        return MisterHelperHealth(
            helper_reachable=True,
            mirror_ok=False,
            addr=addr,
            value=None,
            frame=frame,
            running=None,
            error=getattr(endpoint, "last_error", None) or "mirror_busy_or_inactive",
        )

    running = None
    if mode is not None:
        running = bool(mode.is_running({addr: value}))
    return MisterHelperHealth(
        helper_reachable=True,
        mirror_ok=True,
        addr=addr,
        value=value & 0xFF,
        frame=frame,
        running=running,
        error=None,
    )


def format_mister_health_summary(health: MisterHelperHealth) -> str:
    if not health.helper_reachable:
        return f"MiSTer helper unreachable: {health.error or 'unknown error'}"
    if not health.mirror_ok:
        return (
            "MiSTer helper reachable; mirror read failed: "
            f"{health.error or 'unknown error'} frame={health.frame}"
        )
    running = "unknown"
    if health.running is True:
        running = "yes"
    elif health.running is False:
        running = "no"
    return (
        "MiSTer helper/mirror OK: "
        f"0x{health.addr:04X}=0x{health.value or 0:02X} "
        f"frame={health.frame} running={running}"
    )
