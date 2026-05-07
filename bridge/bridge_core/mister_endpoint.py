"""Read-only MiSTer memory endpoint for the RA mirror POC."""
from __future__ import annotations

from bridge_core.mister_ra import BufferRAMirrorSource, RAMirror, RAMirrorSource


class ReadOnlyMisterMemoryEndpoint:
    def __init__(
        self,
        mirror: bytes | bytearray | memoryview | RAMirrorSource,
    ) -> None:
        if hasattr(mirror, "read_mirror"):
            self._source = mirror
        else:
            self._source = BufferRAMirrorSource(mirror)
        self.last_frame = 0

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        mirror = self._read_mirror()
        if not mirror.active or mirror.busy:
            return None
        return mirror.snapshot_ranges(ranges)

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        mirror = self._read_mirror()
        if not mirror.active or mirror.busy:
            return None
        return mirror.read_nes_byte(addr)

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        raise NotImplementedError("MiSTer writes require the custom NES core write channel")

    def close(self) -> None:
        self._source.close()

    def _read_mirror(self) -> RAMirror:
        mirror = RAMirror(self._source.read_mirror())
        self.last_frame = mirror.frame
        return mirror
