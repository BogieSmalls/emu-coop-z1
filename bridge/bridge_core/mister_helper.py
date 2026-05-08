"""Tiny MiSTer helper protocol for read-only emu-coop POCs."""
from __future__ import annotations

import json
import socket
import socketserver
from collections.abc import Callable
from typing import Any

from bridge_core.memory_endpoint import MemoryEndpoint


class MisterHelperServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], endpoint: MemoryEndpoint) -> None:
        self.endpoint = endpoint
        super().__init__(server_address, _MisterHelperRequestHandler)


class _MisterHelperRequestHandler(socketserver.StreamRequestHandler):
    server: MisterHelperServer

    def handle(self) -> None:
        for line in self.rfile:
            try:
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError(f"invalid helper request: {request!r}")
                response = handle_helper_request(request, self.server.endpoint)
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            self.wfile.write(
                json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
            )


class MisterHelperMemoryEndpoint:
    """PC-side MemoryEndpoint adapter for a tiny MiSTer helper."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 55355,
        timeout: float = 1.0,
        request: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._request_override = request
        self.last_frame = 0

    def read_ranges(
        self,
        ranges: list[tuple[int, int]],
        timeout_ms: int = 300,
    ) -> dict[int, int] | None:
        response = self._request(
            {"op": "read_ranges", "ranges": [[base, length] for base, length in ranges]}
        )
        self.last_frame = int(response.get("frame", self.last_frame))
        if not response.get("ok"):
            return None
        return {int(addr): int(value) & 0xFF for addr, value in response.get("values", [])}

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        response = self._request({"op": "read_byte", "addr": addr})
        self.last_frame = int(response.get("frame", self.last_frame))
        if not response.get("ok"):
            return None
        return int(response.get("value", 0)) & 0xFF

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        response = self._request(
            {"op": "write_pairs", "pairs": [[addr, value] for addr, value in pairs]}
        )
        if response.get("ok"):
            return True
        if response.get("error") == "writes_not_supported":
            raise NotImplementedError("MiSTer writes require the custom NES core write channel")
        return False

    def close(self) -> None:
        return None

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._request_override is not None:
            return self._request_override(payload)
        wire = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        with socket.create_connection((self._host, self._port), timeout=self._timeout) as sock:
            sock.sendall(wire)
            response = sock.makefile("rb").readline()
        if not response:
            raise ConnectionError("MiSTer helper closed without a response")
        decoded = json.loads(response.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError(f"invalid helper response: {decoded!r}")
        return decoded


def handle_helper_request(request: dict[str, Any], endpoint: MemoryEndpoint) -> dict[str, Any]:
    op = request.get("op")
    if op == "read_ranges":
        ranges = _coerce_pairs(request.get("ranges", []))
        snapshot = endpoint.read_ranges(ranges)
        frame = getattr(endpoint, "last_frame", 0)
        if snapshot is None:
            return {"ok": False, "error": "mirror_busy_or_inactive", "frame": frame}
        return {
            "ok": True,
            "frame": frame,
            "values": [[addr, value] for addr, value in snapshot.items()],
        }
    if op == "read_byte":
        addr = int(request.get("addr", 0))
        value = endpoint.read_byte(addr)
        frame = getattr(endpoint, "last_frame", 0)
        if value is None:
            return {"ok": False, "error": "mirror_busy_or_inactive", "frame": frame}
        return {"ok": True, "frame": frame, "value": value}
    if op == "write_pairs":
        try:
            endpoint.write_pairs(_coerce_pairs(request.get("pairs", [])))
        except NotImplementedError:
            return {"ok": False, "error": "writes_not_supported"}
        return {"ok": True}
    return {"ok": False, "error": "unknown_op"}


def _coerce_pairs(raw_pairs: Any) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2:
            raise ValueError(f"invalid pair: {raw_pair!r}")
        pairs.append((int(raw_pair[0]), int(raw_pair[1])))
    return pairs
