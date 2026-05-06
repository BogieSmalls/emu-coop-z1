"""CC USB serial protocol client.

Wraps a serial.Serial-like object and exposes methods to send CC frames
(read/write/freeze) and parse responses.

CC frame format (host -> cart, wrapped in a USB MEM_WR to ADDR_FIFO):
    L (1 byte) = total body length + 1
    MID (1 byte) = monotonic message id, 1..255
    ACTION (1 byte) = 0x00 read addrs, 0x01 read array, 0x02 write pairs,
                       0x03 write array, 0x04 freeze, 0x05 return
    body...

CC response (cart -> host):
    0x20, MID, ACTION, values...
"""
from __future__ import annotations

import time
from typing import Protocol


# USB-level constants
ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B


class SerialLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, n: int = 1) -> bytes: ...
    @property
    def in_waiting(self) -> int: ...
    def close(self) -> None: ...


def _make_usb_header(cmd: int) -> bytes:
    return bytes([P, P ^ 0xFF, cmd & 0xFF, (cmd ^ 0xFF) & 0xFF])


def _u32le(v: int) -> bytes:
    return bytes([(v >> 0) & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])


def _make_cc_frame(mid: int, action: int, payload: bytes) -> bytes:
    body = bytes((mid & 0xFF, action & 0xFF)) + payload
    L = 1 + len(body)
    if L > 255:
        raise ValueError(f"CC frame too large: {L}")
    return bytes((L,)) + body


def _strip_status_pairs(b: bytes) -> bytes:
    """Cart firmware periodically sends 0x00 0xA5 or 0x04 0xA5 status pairs;
    strip them from any received byte stream."""
    out = bytearray()
    i = 0
    while i < len(b):
        if i + 1 < len(b) and b[i] in (0x00, 0x04) and b[i + 1] == 0xA5:
            i += 2
            continue
        out.append(b[i])
        i += 1
    return bytes(out)


class CCClient:
    """Wraps a serial port and exposes the CC USB protocol primitives."""

    def __init__(self, serial_port: SerialLike) -> None:
        self._sp = serial_port
        self._msg_id = 0
        self._rx_buf = bytearray()
        self._expected_mid = 0
        self._expected_action = 0
        self._expected_values = 0

    def _next_mid(self) -> int:
        self._msg_id = (self._msg_id + 1) & 0xFF
        if self._msg_id == 0:
            self._msg_id = 1
        return self._msg_id

    def _usb_mem_wr(self, addr: int, data: bytes) -> None:
        self._sp.write(_make_usb_header(CMD_MEM_WR))
        self._sp.write(_u32le(addr))
        self._sp.write(_u32le(len(data)))
        self._sp.write(b"\x00")
        self._sp.write(data)

    def send_read_addrs(self, addrs: list[int]) -> None:
        mid = self._next_mid()
        payload = bytes((len(addrs),))
        for a in addrs:
            payload += bytes((a & 0xFF, (a >> 8) & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x00, payload))
        self._expected_mid = mid
        self._expected_action = 0x00
        self._expected_values = len(addrs)

    def send_read_array(self, base: int, length: int) -> None:
        mid = self._next_mid()
        payload = bytes((length & 0xFF, base & 0xFF, (base >> 8) & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x01, payload))
        self._expected_mid = mid
        self._expected_action = 0x01
        self._expected_values = length

    def send_write_pairs(self, pairs: list[tuple[int, int]]) -> None:
        mid = self._next_mid()
        payload = bytes((len(pairs),))
        for addr, val in pairs:
            payload += bytes((addr & 0xFF, (addr >> 8) & 0xFF, val & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x02, payload))

    def send_write_array(self, base: int, data: bytes) -> None:
        mid = self._next_mid()
        payload = bytes((len(data) & 0xFF, base & 0xFF, (base >> 8) & 0xFF)) + data
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x03, payload))

    def poll_response(self, timeout_ms: int = 100) -> bytes | None:
        """Wait up to timeout_ms for a response matching the last send_read_*."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            n = self._sp.in_waiting
            if n:
                self._rx_buf += self._sp.read(n)
            filt = _strip_status_pairs(bytes(self._rx_buf))
            for i in range(len(filt) - 3):
                if (
                    filt[i] == 0x20
                    and filt[i + 1] == (self._expected_mid & 0xFF)
                    and filt[i + 2] in (self._expected_action & 0xFF, 0x00)
                ):
                    start = i + 3
                    end = start + self._expected_values
                    if end <= len(filt):
                        result = bytes(filt[start:end])
                        self._rx_buf.clear()
                        return result
            time.sleep(0.001)
        return None

    def close(self) -> None:
        self._sp.close()
