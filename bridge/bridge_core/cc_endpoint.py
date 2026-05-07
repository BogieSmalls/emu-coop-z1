"""MemoryEndpoint adapter for the EDN8 Crowd Control USB client."""
from __future__ import annotations

from bridge_core.cc_client import CCClient


class CCMemoryEndpoint:
    def __init__(self, client: CCClient) -> None:
        self._client = client

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        return self._client.read_ranges(ranges, timeout_ms=timeout_ms)

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        self._client.send_read_addrs([addr])
        result = self._client.poll_response(timeout_ms=timeout_ms)
        if result and len(result) >= 1:
            return result[0]
        return None

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        self._client.send_write_pairs(pairs)
        return True

    def close(self) -> None:
        self._client.close()
