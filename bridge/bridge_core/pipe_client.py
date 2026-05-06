"""Pipe client — Python equivalent of pipe_relay.lua + pipe.lua's RelayPipe.

This module's first commit ships only the framing helpers; the connection
state machine (hello/heartbeat/reconnect) comes in subsequent tasks.
"""
from __future__ import annotations

import json


MAX_PAYLOAD = 4096


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
