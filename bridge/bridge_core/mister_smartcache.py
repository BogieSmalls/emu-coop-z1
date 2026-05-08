"""Read endpoint for odelot's NES RA smart-cache mailbox."""
from __future__ import annotations

import time
from dataclasses import dataclass

from bridge_core.mister_mailbox import MailboxMemory


ADDRLIST_CTRL_OFFSET = 0x40000
ADDRLIST_VALUES_OFFSET = 0x40008
VALCACHE_CTRL_OFFSET = 0x48000
VALCACHE_VALUES_OFFSET = 0x48008
MAX_READ_ADDRS = 4096


@dataclass(frozen=True)
class SmartCacheRequest:
    request_id: int
    addresses: list[int]


class MisterSmartCacheMemoryEndpoint:
    """Drive odelot's ARM-written address list and FPGA-written value cache."""

    def __init__(
        self,
        memory: MailboxMemory,
        *,
        response_poll_interval_s: float = 0.001,
    ) -> None:
        self._memory = memory
        self._response_poll_interval_s = response_poll_interval_s
        self._request_id = 0
        self.last_frame = 0

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        request = self.submit_read_request(ranges)
        return self.read_response(request, timeout_ms=timeout_ms)

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        snapshot = self.read_ranges([(addr, 1)], timeout_ms=timeout_ms)
        if snapshot is None:
            return None
        return snapshot.get(addr, 0)

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        raise NotImplementedError("MiSTer smart-cache reads do not provide writes")

    def submit_read_request(self, ranges: list[tuple[int, int]]) -> SmartCacheRequest:
        addresses = self._expand_ranges(ranges)
        request_id = self._next_request_id()
        for word_index in range(0, len(addresses), 2):
            low = addresses[word_index] & 0xFFFFFFFF
            high = 0
            if word_index + 1 < len(addresses):
                high = addresses[word_index + 1] & 0xFFFFFFFF
            self._memory.write_u64(ADDRLIST_VALUES_OFFSET + (word_index // 2) * 8, low | (high << 32))
        self._memory.write_u64(ADDRLIST_CTRL_OFFSET, len(addresses) | (request_id << 32))
        return SmartCacheRequest(request_id=request_id, addresses=addresses)

    def read_response(
        self,
        request: SmartCacheRequest,
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while True:
            control = self._memory.read_u64(VALCACHE_CTRL_OFFSET)
            response_id = control & 0xFFFFFFFF
            if response_id == request.request_id:
                self.last_frame = (control >> 32) & 0xFFFFFFFF
                return self._read_values(request.addresses)
            if timeout_ms <= 0 or time.monotonic() >= deadline:
                return None
            time.sleep(self._response_poll_interval_s)

    def close(self) -> None:
        self._memory.close()

    def _read_values(self, addresses: list[int]) -> dict[int, int]:
        snapshot: dict[int, int] = {}
        for index, addr in enumerate(addresses):
            word = self._memory.read_u64(VALCACHE_VALUES_OFFSET + (index // 8) * 8)
            value = (word >> ((index % 8) * 8)) & 0xFF
            snapshot[addr] = value
        return snapshot

    def _expand_ranges(self, ranges: list[tuple[int, int]]) -> list[int]:
        addresses: list[int] = []
        for base, length in ranges:
            for offset in range(length):
                addresses.append((int(base) + offset) & 0xFFFF)
        if len(addresses) > MAX_READ_ADDRS:
            raise ValueError(f"smart-cache supports at most {MAX_READ_ADDRS} addresses")
        return addresses

    def _next_request_id(self) -> int:
        self._request_id += 1
        if self._request_id > 0xFFFFFFFF:
            self._request_id = 1
        return self._request_id
