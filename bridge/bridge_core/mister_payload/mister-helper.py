#!/usr/bin/env python3
"""Standalone MiSTer memory helper for z1rr-coop.

This script intentionally uses only Python stdlib so it can run on MiSTer's
Linux side without installing the full PC bridge package.
"""

import argparse
import json
import mmap
import os
import socketserver
import time
from typing import Any, Dict, List, Optional, Tuple


RA_DDRAM_PHYS_BASE = 0x3D000000
RA_DDRAM_MAP_SIZE = 0x60000

ADDRLIST_CTRL_OFFSET = 0x40000
ADDRLIST_VALUES_OFFSET = 0x40008
VALCACHE_CTRL_OFFSET = 0x48000
VALCACHE_VALUES_OFFSET = 0x48008
MAX_READ_ADDRS = 4096

MAILBOX_CTRL_OFFSET = 0x58000
MAILBOX_PAIR_OFFSET = 0x58008
MAILBOX_MAX_PAIRS = 32
STATUS_OK = 0


class DevMemWindow:
    def __init__(
        self,
        *,
        phys_base: int = RA_DDRAM_PHYS_BASE,
        size: int = RA_DDRAM_MAP_SIZE,
        devmem_path: str = "/dev/mem",
    ) -> None:
        self._phys_base = phys_base
        self._size = size
        self._devmem_path = devmem_path
        self._fd = None  # type: Optional[int]
        self._map = None  # type: Optional[mmap.mmap]

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
            raise ValueError(f"DDRAM offset out of range: 0x{offset:X}")

    def _ensure_map(self) -> None:
        if self._map is not None:
            return
        flags = os.O_RDWR | getattr(os, "O_SYNC", 0)
        self._fd = os.open(self._devmem_path, flags)
        self._map = mmap.mmap(
            self._fd,
            self._size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
            offset=self._phys_base,
        )


class MisterMemory:
    def __init__(
        self,
        window: DevMemWindow,
        *,
        enable_writes: bool = False,
        response_timeout_ms: int = 300,
        write_timeout_ms: int = 100,
    ) -> None:
        self._window = window
        self._enable_writes = enable_writes
        self._response_timeout_ms = response_timeout_ms
        self._write_timeout_ms = write_timeout_ms
        self._request_id = 0
        self._write_seq = 0
        self.last_frame = 0

    def read_ranges(self, ranges: List[Tuple[int, int]]) -> Optional[Dict[int, int]]:
        addresses = self._expand_ranges(ranges)
        if not addresses:
            return {}
        request_id = self._next_request_id()
        for word_index in range(0, len(addresses), 2):
            low = addresses[word_index] & 0xFFFFFFFF
            high = 0
            if word_index + 1 < len(addresses):
                high = addresses[word_index + 1] & 0xFFFFFFFF
            self._window.write_u64(
                ADDRLIST_VALUES_OFFSET + (word_index // 2) * 8,
                low | (high << 32),
            )
        self._window.write_u64(ADDRLIST_CTRL_OFFSET, len(addresses) | (request_id << 32))
        deadline = time.monotonic() + (self._response_timeout_ms / 1000.0)
        while True:
            control = self._window.read_u64(VALCACHE_CTRL_OFFSET)
            response_id = control & 0xFFFFFFFF
            if response_id == request_id:
                self.last_frame = (control >> 32) & 0xFFFFFFFF
                return self._read_values(addresses)
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.001)

    def read_byte(self, addr: int) -> Optional[int]:
        snapshot = self.read_ranges([(addr, 1)])
        if snapshot is None:
            return None
        return snapshot.get(addr, 0)

    def write_pairs(self, pairs: List[Tuple[int, int]]) -> bool:
        if not self._enable_writes:
            raise NotImplementedError("writes_not_supported")
        checked = self._validate_write_pairs(pairs)
        if not checked:
            return True
        sequence = self._next_write_seq()
        for index, (addr, value) in enumerate(checked):
            word = (addr & 0xFFFF) | ((value & 0xFF) << 16)
            self._window.write_u64(MAILBOX_PAIR_OFFSET + index * 8, word)
        self._window.write_u64(MAILBOX_CTRL_OFFSET, sequence | (len(checked) << 8))
        deadline = time.monotonic() + (self._write_timeout_ms / 1000.0)
        while True:
            control = self._window.read_u64(MAILBOX_CTRL_OFFSET)
            ack_sequence = (control >> 16) & 0xFF
            status = (control >> 24) & 0xFF
            if ack_sequence == sequence:
                return status == STATUS_OK
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.001)

    def close(self) -> None:
        self._window.close()

    def _expand_ranges(self, ranges: List[Tuple[int, int]]) -> List[int]:
        addresses = []  # type: List[int]
        for base, length in ranges:
            for offset in range(length):
                addresses.append((int(base) + offset) & 0xFFFF)
        if len(addresses) > MAX_READ_ADDRS:
            raise ValueError(f"smart-cache supports at most {MAX_READ_ADDRS} addresses")
        return addresses

    def _read_values(self, addresses: List[int]) -> Dict[int, int]:
        snapshot = {}  # type: Dict[int, int]
        for index, addr in enumerate(addresses):
            word = self._window.read_u64(VALCACHE_VALUES_OFFSET + (index // 8) * 8)
            snapshot[addr] = (word >> ((index % 8) * 8)) & 0xFF
        return snapshot

    def _validate_write_pairs(
        self,
        pairs: List[Tuple[int, int]],
    ) -> List[Tuple[int, int]]:
        checked = [(int(addr), int(value) & 0xFF) for addr, value in pairs]
        if len(checked) > MAILBOX_MAX_PAIRS:
            raise ValueError(f"write mailbox supports at most {MAILBOX_MAX_PAIRS} pairs")
        for addr, _value in checked:
            if addr < 0 or addr >= 0x2000:
                raise ValueError(f"address 0x{addr:04X} is outside CPU RAM")
        return checked

    def _next_request_id(self) -> int:
        self._request_id += 1
        if self._request_id > 0xFFFFFFFF:
            self._request_id = 1
        return self._request_id

    def _next_write_seq(self) -> int:
        self._write_seq += 1
        if self._write_seq > 0xFF:
            self._write_seq = 1
        return self._write_seq


class HelperServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address: Tuple[str, int], memory: MisterMemory) -> None:
        self.memory = memory
        super().__init__(server_address, HelperRequestHandler)


class HelperRequestHandler(socketserver.StreamRequestHandler):
    server: HelperServer

    def handle(self) -> None:
        for line in self.rfile:
            try:
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                response = handle_request(request, self.server.memory)
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            self.wfile.write(
                json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
            )


def handle_request(request: Dict[str, Any], memory: MisterMemory) -> Dict[str, Any]:
    op = request.get("op")
    if op == "read_ranges":
        snapshot = memory.read_ranges(_coerce_pairs(request.get("ranges", [])))
        if snapshot is None:
            return {
                "ok": False,
                "error": "mirror_busy_or_inactive",
                "frame": memory.last_frame,
            }
        return {
            "ok": True,
            "frame": memory.last_frame,
            "values": [[addr, value] for addr, value in snapshot.items()],
        }
    if op == "read_byte":
        value = memory.read_byte(int(request.get("addr", 0)))
        if value is None:
            return {
                "ok": False,
                "error": "mirror_busy_or_inactive",
                "frame": memory.last_frame,
            }
        return {"ok": True, "frame": memory.last_frame, "value": value}
    if op == "write_pairs":
        try:
            ok = memory.write_pairs(_coerce_pairs(request.get("pairs", [])))
        except NotImplementedError:
            return {"ok": False, "error": "writes_not_supported"}
        if not ok:
            return {"ok": False, "error": "write_failed"}
        return {"ok": True}
    return {"ok": False, "error": "unknown_op"}


def _coerce_pairs(raw_pairs: Any) -> List[Tuple[int, int]]:
    pairs = []  # type: List[Tuple[int, int]]
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2:
            raise ValueError(f"invalid pair: {raw_pair!r}")
        pairs.append((int(raw_pair[0]), int(raw_pair[1])))
    return pairs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mister-helper.py")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=55355)
    parser.add_argument("--devmem", default="/dev/mem")
    parser.add_argument("--enable-writes", action="store_true")
    parser.add_argument("--read-timeout-ms", type=int, default=300)
    parser.add_argument("--write-timeout-ms", type=int, default=100)
    args = parser.parse_args(argv)

    window = DevMemWindow(devmem_path=args.devmem)
    memory = MisterMemory(
        window,
        enable_writes=args.enable_writes,
        response_timeout_ms=args.read_timeout_ms,
        write_timeout_ms=args.write_timeout_ms,
    )
    server = HelperServer((args.host, args.port), memory)
    try:
        print(f"emu-coop MiSTer helper listening on {args.host}:{args.port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
