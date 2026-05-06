"""Pyserial-compatible in-memory mock for unit tests."""
from __future__ import annotations

from collections import deque


class MockSerial:
    """Implements the pyserial subset bridge_core uses: write, read, in_waiting, close."""

    def __init__(self) -> None:
        self._tx_buf = bytearray()  # bytes the test code "wrote" (i.e., what bridge sends)
        self._rx_buf: deque[int] = deque()  # bytes the test should "read back" from the cart
        self.is_open = True
        self.timeout = 0
        self.write_timeout = 0
        self.baudrate = 115200

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise IOError("port closed")
        self._tx_buf += data
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if not self.is_open:
            raise IOError("port closed")
        out = bytearray()
        for _ in range(min(n, len(self._rx_buf))):
            out.append(self._rx_buf.popleft())
        return bytes(out)

    @property
    def in_waiting(self) -> int:
        return len(self._rx_buf)

    def close(self) -> None:
        self.is_open = False

    def reset_input_buffer(self) -> None:
        self._rx_buf.clear()

    def reset_output_buffer(self) -> None:
        self._tx_buf.clear()

    # Test helpers (not part of the pyserial API)

    def feed_rx(self, data: bytes) -> None:
        """Push bytes into the simulated cart-to-host RX buffer."""
        self._rx_buf.extend(data)

    def take_tx(self) -> bytes:
        """Drain and return everything the bridge has written so far."""
        out = bytes(self._tx_buf)
        self._tx_buf.clear()
        return out
