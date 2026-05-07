"""RetroAchievements RAM mirror parsing for MiSTer NES POCs."""
from __future__ import annotations

import mmap
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


RA_MAGIC = 0x52414348
RA_DDRAM_PHYS_BASE = 0x3D000000
RA_DDRAM_MAP_SIZE = 0x00010000
RA_FLAG_BUSY = 0x01
RA_MAX_REGIONS = 4
RA_NES_CPURAM_REGION = 0
RA_NES_CARTRAM_REGION = 1

_HEADER_SIZE = 0x10
_REGION_DESC_SIZE = 8


class RAMirrorSource(Protocol):
    def read_mirror(self) -> bytes | bytearray | memoryview: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class RARegion:
    sdram_addr: int
    size: int
    ddram_offset: int


class RAMirror:
    """Read odelot's console-agnostic RA mirror header and NES regions."""

    def __init__(self, raw: bytes | bytearray | memoryview) -> None:
        self._raw = memoryview(raw)

    @property
    def active(self) -> bool:
        return len(self._raw) >= _HEADER_SIZE and self._u32(0x00) == RA_MAGIC

    @property
    def busy(self) -> bool:
        return self.active and bool(self._raw[0x05] & RA_FLAG_BUSY)

    @property
    def frame(self) -> int:
        if not self.active:
            return 0
        return self._u32(0x08)

    @property
    def regions(self) -> list[RARegion]:
        if not self.active:
            return []
        count = min(int(self._raw[0x04]), RA_MAX_REGIONS)
        regions: list[RARegion] = []
        for index in range(count):
            offset = _HEADER_SIZE + index * _REGION_DESC_SIZE
            if offset + _REGION_DESC_SIZE > len(self._raw):
                break
            regions.append(
                RARegion(
                    sdram_addr=self._u32(offset),
                    size=self._u16(offset + 4),
                    ddram_offset=self._u16(offset + 6),
                )
            )
        return regions

    def read_nes_byte(self, addr: int) -> int:
        if not self.active:
            return 0
        addr &= 0xFFFF
        if addr < 0x2000:
            return self._read_region_byte(RA_NES_CPURAM_REGION, addr & 0x07FF)
        if 0x6000 <= addr <= 0x7FFF:
            return self._read_region_byte(RA_NES_CARTRAM_REGION, addr - 0x6000)
        return 0

    def read_nes(self, addr: int, length: int) -> bytes:
        return bytes(self.read_nes_byte(addr + offset) for offset in range(length))

    def snapshot_ranges(self, ranges: list[tuple[int, int]]) -> dict[int, int]:
        snapshot: dict[int, int] = {}
        for base, length in ranges:
            for offset in range(length):
                addr = base + offset
                snapshot[addr] = self.read_nes_byte(addr)
        return snapshot

    def _read_region_byte(self, region_index: int, offset: int) -> int:
        data = self._region_data(region_index)
        if data is None or offset >= len(data):
            return 0
        return int(data[offset])

    def _region_data(self, region_index: int) -> memoryview | None:
        regions = self.regions
        if region_index < 0 or region_index >= len(regions):
            return None
        region = regions[region_index]
        if region.size <= 0:
            return None
        start = region.ddram_offset
        end = start + region.size
        if start < 0 or end > len(self._raw):
            return None
        return self._raw[start:end]

    def _u16(self, offset: int) -> int:
        return int.from_bytes(self._raw[offset:offset + 2], "little")

    def _u32(self, offset: int) -> int:
        return int.from_bytes(self._raw[offset:offset + 4], "little")


class BufferRAMirrorSource:
    def __init__(self, raw: bytes | bytearray | memoryview) -> None:
        self._raw = raw

    def read_mirror(self) -> bytes | bytearray | memoryview:
        return self._raw

    def close(self) -> None:
        return None


class FileRAMirrorSource:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def read_mirror(self) -> bytes:
        return self._path.read_bytes()

    def close(self) -> None:
        return None


class DevMemRAMirrorSource:
    """Map MiSTer's RA mirror from /dev/mem.

    This is intended for MiSTer's Linux side. Tests use BufferRAMirrorSource.
    """

    def __init__(
        self,
        phys_base: int = RA_DDRAM_PHYS_BASE,
        size: int = RA_DDRAM_MAP_SIZE,
        devmem_path: str = "/dev/mem",
    ) -> None:
        self._phys_base = phys_base
        self._size = size
        self._devmem_path = devmem_path
        self._fd: int | None = None
        self._map: mmap.mmap | None = None

    def read_mirror(self) -> memoryview:
        self._ensure_map()
        assert self._map is not None
        return memoryview(self._map)

    def close(self) -> None:
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _ensure_map(self) -> None:
        if self._map is not None:
            return
        if os.name == "nt":
            raise OSError("/dev/mem RA mirror reads are only available on MiSTer/Linux")
        flags = os.O_RDONLY | getattr(os, "O_SYNC", 0)
        self._fd = os.open(self._devmem_path, flags)
        self._map = mmap.mmap(
            self._fd,
            self._size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ,
            offset=self._phys_base,
        )
