"""Pipe client — Python equivalent of pipe_relay.lua + pipe.lua's RelayPipe.

This module's first commit ships only the framing helpers; the connection
state machine (hello/heartbeat/reconnect) comes in subsequent tasks.
"""
from __future__ import annotations

import json


MAX_PAYLOAD = 4096

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0


class WireError(Exception):
    pass


def encode_frame(obj: dict) -> bytes:
    payload = json.dumps(obj).encode()
    if len(payload) > MAX_PAYLOAD:
        raise WireError(f"frame too large: {len(payload)} > {MAX_PAYLOAD}")
    return len(payload).to_bytes(4, "big") + payload


def try_decode_frame(buf: bytes) -> tuple[dict | None, int]:
    """Returns (decoded_frame_or_None, bytes_consumed).

    If buf doesn't yet contain a full frame, returns (None, 0). On oversized
    or malformed JSON, raises WireError.
    """
    if len(buf) < 4:
        return None, 0
    length = int.from_bytes(buf[:4], "big")
    if length > MAX_PAYLOAD:
        raise WireError(f"frame too large: {length}")
    if len(buf) < 4 + length:
        return None, 0
    payload = buf[4:4 + length]
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as e:
        raise WireError(f"malformed JSON: {e}")
    return obj, 4 + length


PROTOCOL_VERSION = 1


class PipeClient:
    """Python equivalent of RelayPipe in pipe_relay.lua.

    States: INIT → CONNECTING → JOIN_SENT → JOINED → HELLO_SENT → ESTABLISHED
                                                                ↓
                                                           FAILED / RECONNECTING
    """

    def __init__(self, socket, code: str, peer_id: str, clock=None) -> None:
        import time
        self._sock = socket
        self.code = code
        self.peer_id = peer_id
        self.state = "INIT"
        self._rx_buf = bytearray()
        self._hello_sent = False
        self._hello_received = False
        self._joined = False
        self._clock = clock or time.monotonic
        self._last_rx = self._clock()
        self._last_ping = self._clock()
        self.on_data = None
        self.on_partner_reconnected = None
        self.on_abort = None

    def send_join(self) -> None:
        self.state = "JOIN_SENT"
        self._send_frame({"kind": "join", "code": self.code, "peer_id": self.peer_id})

    def send_hello(self) -> None:
        if self._hello_sent:
            return
        self._hello_sent = True
        self.state = "HELLO_SENT"
        self._send_frame({"kind": "hello", "v": PROTOCOL_VERSION})

    def send_data(self, body: dict) -> None:
        if self.state != "ESTABLISHED":
            return
        self._send_frame({"kind": "data", "body": body})

    def abort(self, reason: str) -> None:
        self._send_frame({"kind": "abort", "reason": reason})
        self._fail(f"Aborted: {reason}")

    def tick(self) -> None:
        if self.state in ("FAILED", "CLOSED"):
            return
        # Drain any pending bytes
        try:
            chunk = self._sock.recv(4096)
            if chunk:
                self._rx_buf += chunk
            elif self.state in ("ESTABLISHED", "HELLO_SENT", "JOINED"):
                # Peer closed
                self._fail("Connection lost")
                return
        except BlockingIOError:
            pass
        except OSError:
            self._fail("Connection lost")
            return
        # Process whole frames
        while True:
            try:
                frame, consumed = try_decode_frame(bytes(self._rx_buf))
            except WireError as e:
                self._fail(f"Wire protocol error: {e}")
                return
            if frame is None:
                break
            del self._rx_buf[:consumed]
            self._handle_frame(frame)
            if self.state in ("FAILED", "CLOSED"):
                return

    def _init_heartbeat(self) -> None:
        self._last_rx = self._clock()
        self._last_ping = self._clock()

    def heartbeat_tick(self) -> None:
        if self.state not in ("ESTABLISHED", "HELLO_SENT"):
            return
        now = self._clock()
        if (now - self._last_rx) > HEARTBEAT_TIMEOUT:
            self._fail("Connection lost (heartbeat timeout)")
            return
        if (now - self._last_ping) > HEARTBEAT_INTERVAL:
            self._send_frame({"kind": "ping"})
            self._last_ping = now

    def _handle_frame(self, frame: dict) -> None:
        # Any received frame resets the liveness timer
        self._last_rx = self._clock()
        kind = frame.get("kind")
        if kind == "joined":
            if not self._joined:
                self._joined = True
                self.state = "JOINED"
                self.send_hello()
        elif kind == "hello":
            if self._hello_received:
                self._fail("duplicate hello")
                return
            if frame.get("v") != PROTOCOL_VERSION:
                self._send_frame({"kind": "abort", "reason": "version mismatch"})
                self._fail(f"Partner version mismatch: v={frame.get('v')}, expected v={PROTOCOL_VERSION}")
                return
            self._hello_received = True
            if self._hello_sent and self.state != "ESTABLISHED":
                self.state = "ESTABLISHED"
        elif kind == "data":
            if self.state == "ESTABLISHED" and self.on_data:
                self.on_data(frame.get("body", {}))
        elif kind == "ping":
            self._send_frame({"kind": "pong"})
        elif kind == "pong":
            pass
        elif kind == "abort":
            reason = frame.get("reason", "unknown")
            if self.on_abort:
                self.on_abort(reason)
            self._fail(f"Partner aborted: {reason}")
        elif kind == "partner-reconnected":
            self._hello_sent = False
            self._hello_received = False
            self.state = "JOINED"
            self.send_hello()
            if self.on_partner_reconnected:
                self.on_partner_reconnected()

    def _send_frame(self, obj: dict) -> None:
        try:
            self._sock.send(encode_frame(obj))
        except OSError:
            self._fail("send failed")

    def _fail(self, msg: str) -> None:
        if self.state in ("FAILED", "CLOSED"):
            return
        self.state = "FAILED"
        try:
            self._sock.close()
        except Exception:
            pass

    def close(self) -> None:
        self.state = "CLOSED"
        try:
            self._sock.close()
        except Exception:
            pass
