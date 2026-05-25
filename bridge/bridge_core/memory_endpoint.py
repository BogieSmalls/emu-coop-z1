"""Generic memory endpoint interface for non-Lua Z1RR-coop clients."""
from __future__ import annotations

from typing import Protocol


class MemoryEndpoint(Protocol):
    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None: ...

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None: ...

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool: ...

    def close(self) -> None: ...


class DictMemoryEndpoint:
    """In-memory endpoint for unit tests and dry-run prototypes."""

    def __init__(self, memory: dict[int, int] | None = None) -> None:
        self.memory = dict(memory or {})

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        snapshot: dict[int, int] = {}
        for base, length in ranges:
            for offset in range(length):
                addr = base + offset
                snapshot[addr] = self.memory.get(addr, 0)
        return snapshot

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        return self.memory.get(addr, 0)

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        for addr, value in pairs:
            self.memory[addr] = value & 0xFF
        return True

    def close(self) -> None:
        return None
