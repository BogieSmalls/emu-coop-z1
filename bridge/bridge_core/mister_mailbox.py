"""MiSTer DDRAM write mailbox for the custom NES core POC."""
from __future__ import annotations

import mmap
import os
import time
from pathlib import Path
from typing import Protocol

from bridge_core.memory_endpoint import MemoryEndpoint
from bridge_core.mister_ra import RA_DDRAM_PHYS_BASE


MAILBOX_CTRL_OFFSET = 0x58000
MAILBOX_PAIR_OFFSET = 0x58008
MAILBOX_MAP_SIZE = 0x60000
MAILBOX_MAX_PAIRS = 32

STATUS_OK = 0
STATUS_INVALID_ADDR = 1
STATUS_TIMEOUT = 2


class MailboxMemory(Protocol):
    def read_u64(self, offset: int) -> int: ...

    def write_u64(self, offset: int, value: int) -> None: ...

    def close(self) -> None: ...


class BufferMailboxMemory:
    def __init__(self, raw: bytearray | memoryview) -> None:
        self._raw = memoryview(raw)

    def read_u64(self, offset: int) -> int:
        self._check_range(offset)
        return int.from_bytes(self._raw[offset:offset + 8], "little")

    def write_u64(self, offset: int, value: int) -> None:
        self._check_range(offset)
        self._raw[offset:offset + 8] = int(value & 0xFFFFFFFFFFFFFFFF).to_bytes(
            8,
            "little",
        )

    def close(self) -> None:
        self._raw.release()

    def _check_range(self, offset: int) -> None:
        if offset < 0 or offset + 8 > len(self._raw):
            raise ValueError(f"mailbox offset out of range: 0x{offset:X}")


class FileMailboxMemory:
    def __init__(self, path: str | Path, size: int = MAILBOX_MAP_SIZE) -> None:
        self._path = Path(path)
        self._size = size

    def read_u64(self, offset: int) -> int:
        self._check_range(offset)
        with self._path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(8)
        if len(data) != 8:
            raise ValueError(f"mailbox file too short at offset 0x{offset:X}")
        return int.from_bytes(data, "little")

    def write_u64(self, offset: int, value: int) -> None:
        self._check_range(offset)
        with self._path.open("r+b") as fh:
            fh.seek(offset)
            fh.write(int(value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"))

    def close(self) -> None:
        return None

    def _check_range(self, offset: int) -> None:
        if offset < 0 or offset + 8 > self._size:
            raise ValueError(f"mailbox offset out of range: 0x{offset:X}")


class DevMemMailboxMemory:
    """Map the MiSTer RA DDRAM window read/write for the mailbox."""

    def __init__(
        self,
        phys_base: int = RA_DDRAM_PHYS_BASE,
        size: int = MAILBOX_MAP_SIZE,
        devmem_path: str = "/dev/mem",
    ) -> None:
        self._phys_base = phys_base
        self._size = size
        self._devmem_path = devmem_path
        self._fd: int | None = None
        self._map: mmap.mmap | None = None

    def read_u64(self, offset: int) -> int:
        self._check_range(offset)
        self._ensure_map()
        assert self._map is not None
        return int.from_bytes(self._map[offset:offset + 8], "little")

    def write_u64(self, offset: int, value: int) -> None:
        self._check_range(offset)
        self._ensure_map()
        assert self._map is not None
        self._map[offset:offset + 8] = int(value & 0xFFFFFFFFFFFFFFFF).to_bytes(
            8,
            "little",
        )

    def close(self) -> None:
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _check_range(self, offset: int) -> None:
        if offset < 0 or offset + 8 > self._size:
            raise ValueError(f"mailbox offset out of range: 0x{offset:X}")

    def _ensure_map(self) -> None:
        if self._map is not None:
            return
        if os.name == "nt":
            raise OSError("/dev/mem mailbox writes are only available on MiSTer/Linux")
        flags = os.O_RDWR | getattr(os, "O_SYNC", 0)
        self._fd = os.open(self._devmem_path, flags)
        self._map = mmap.mmap(
            self._fd,
            self._size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
            offset=self._phys_base,
        )


class MisterWriteMailbox:
    def __init__(
        self,
        memory: MailboxMemory,
        *,
        max_pairs: int = MAILBOX_MAX_PAIRS,
        ack_timeout_ms: int = 100,
        ack_poll_interval_s: float = 0.001,
    ) -> None:
        self._memory = memory
        self._max_pairs = max_pairs
        self._ack_timeout_ms = ack_timeout_ms
        self._ack_poll_interval_s = ack_poll_interval_s
        self._sequence = 0

    def submit_pairs(self, pairs: list[tuple[int, int]]) -> int:
        checked = self._validate_pairs(pairs)
        if not checked:
            return 0
        sequence = self._next_sequence()
        for index, (addr, value) in enumerate(checked):
            word = (addr & 0xFFFF) | ((value & 0xFF) << 16)
            self._memory.write_u64(MAILBOX_PAIR_OFFSET + index * 8, word)
        self._memory.write_u64(MAILBOX_CTRL_OFFSET, sequence | (len(checked) << 8))
        return sequence

    def wait_for_ack(self, sequence: int, timeout_ms: int | None = None) -> bool:
        if sequence == 0:
            return True
        timeout = self._ack_timeout_ms if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + (timeout / 1000.0)
        while True:
            control = self._memory.read_u64(MAILBOX_CTRL_OFFSET)
            ack_sequence = (control >> 16) & 0xFF
            status = (control >> 24) & 0xFF
            if ack_sequence == sequence:
                return status == STATUS_OK
            if timeout <= 0 or time.monotonic() >= deadline:
                return False
            time.sleep(self._ack_poll_interval_s)

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        sequence = self.submit_pairs(pairs)
        return self.wait_for_ack(sequence)

    def close(self) -> None:
        self._memory.close()

    def _validate_pairs(self, pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
        checked = [(int(addr), int(value) & 0xFF) for addr, value in pairs]
        if len(checked) > self._max_pairs:
            raise ValueError(f"write mailbox supports at most {self._max_pairs} pairs")
        for addr, _ in checked:
            if addr < 0 or addr >= 0x2000:
                raise ValueError(f"address 0x{addr:04X} is outside CPU RAM")
        return checked

    def _next_sequence(self) -> int:
        self._sequence += 1
        if self._sequence > 0xFF:
            self._sequence = 1
        return self._sequence


class MisterMailboxMemoryEndpoint:
    """Read through the RA mirror and write through the DDRAM mailbox."""

    def __init__(self, reader: MemoryEndpoint, mailbox: MisterWriteMailbox) -> None:
        self._reader = reader
        self._mailbox = mailbox
        self.last_frame = 0

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        snapshot = self._reader.read_ranges(ranges, timeout_ms=timeout_ms)
        self.last_frame = int(getattr(self._reader, "last_frame", self.last_frame))
        return snapshot

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        value = self._reader.read_byte(addr, timeout_ms=timeout_ms)
        self.last_frame = int(getattr(self._reader, "last_frame", self.last_frame))
        return value

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        return self._mailbox.write_pairs(pairs)

    def close(self) -> None:
        self._reader.close()
        self._mailbox.close()
