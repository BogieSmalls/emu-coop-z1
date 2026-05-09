"""Rate limiter for EDN8 map writes.

The relay speaks in per-address updates, but a map burst can still translate
into many rapid CC write transactions. This gate coalesces map-byte updates and
drains them at a conservative rate.
"""
from __future__ import annotations

from collections import OrderedDict, deque
import time


class MapWriteGate:
    def __init__(
        self,
        *,
        drain_interval_s: float = 0.075,
        burst_window_s: float = 0.25,
        burst_threshold: int = 16,
    ) -> None:
        self.drain_interval_s = drain_interval_s
        self.burst_window_s = burst_window_s
        self.burst_threshold = burst_threshold
        self._pending: OrderedDict[int, int] = OrderedDict()
        self._recent_enqueues: deque[float] = deque()
        self._last_drain_at: float | None = None
        self.burst_count = 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def enqueue(self, addr: int, value: int, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._pending[addr] = value & 0xFF
        self._recent_enqueues.append(now)
        while self._recent_enqueues and now - self._recent_enqueues[0] > self.burst_window_s:
            self._recent_enqueues.popleft()
        if len(self._recent_enqueues) == self.burst_threshold:
            self.burst_count += 1

    def is_due(self, *, now: float | None = None) -> bool:
        if not self._pending:
            return False
        if self._last_drain_at is None:
            return True
        now = time.monotonic() if now is None else now
        return now - self._last_drain_at >= self.drain_interval_s

    def pop_due(self, *, now: float | None = None) -> tuple[int, int] | None:
        now = time.monotonic() if now is None else now
        if not self.is_due(now=now):
            return None
        addr, value = self._pending.popitem(last=False)
        self._last_drain_at = now
        return addr, value
