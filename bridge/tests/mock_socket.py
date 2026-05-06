"""Paired in-memory mock for socket.socket — for unit tests of pipe_client."""
from __future__ import annotations

from collections import deque


class MockSocketPair:
    """Two MockSockets that share buffers cross-wise.

    Use mock_pair() to create a pair where what side A writes is readable by B
    and vice versa.
    """

    def __init__(self) -> None:
        self.a_to_b: deque[int] = deque()
        self.b_to_a: deque[int] = deque()
        self.a_closed = False
        self.b_closed = False


class MockSocket:
    def __init__(self, pair: MockSocketPair, side: str) -> None:
        self._pair = pair
        self._side = side  # "a" or "b"
        self._timeout: float | None = 0.0
        self._closed = False

    def settimeout(self, t: float | None) -> None:
        self._timeout = t

    def setblocking(self, blocking: bool) -> None:
        self._timeout = None if blocking else 0.0

    def send(self, data: bytes) -> int:
        if self._closed:
            raise OSError("socket closed")
        if self._side == "a":
            if self._pair.b_closed:
                raise OSError("peer closed")
            self._pair.a_to_b.extend(data)
        else:
            if self._pair.a_closed:
                raise OSError("peer closed")
            self._pair.b_to_a.extend(data)
        return len(data)

    def recv(self, n: int) -> bytes:
        if self._closed:
            raise OSError("socket closed")
        buf = self._pair.b_to_a if self._side == "a" else self._pair.a_to_b
        peer_closed = self._pair.b_closed if self._side == "a" else self._pair.a_closed
        if not buf:
            if peer_closed:
                return b""
            if self._timeout == 0.0:
                # Non-blocking: would block → raise as pyserial does
                import errno
                raise BlockingIOError(errno.EAGAIN, "would block")
            return b""
        out = bytearray()
        for _ in range(min(n, len(buf))):
            out.append(buf.popleft())
        return bytes(out)

    def close(self) -> None:
        self._closed = True
        if self._side == "a":
            self._pair.a_closed = True
        else:
            self._pair.b_closed = True


def mock_pair() -> tuple[MockSocket, MockSocket]:
    pair = MockSocketPair()
    return MockSocket(pair, "a"), MockSocket(pair, "b")
