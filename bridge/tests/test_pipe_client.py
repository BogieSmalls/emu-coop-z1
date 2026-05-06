import json
import struct

import pytest

from bridge_core import pipe_client

from .mock_socket import mock_pair


def test_encode_frame_format():
    raw = pipe_client.encode_frame({"kind": "hello", "v": 1})
    length = int.from_bytes(raw[:4], "big")
    body = raw[4:].decode()
    assert json.loads(body) == {"kind": "hello", "v": 1}
    assert length == len(body)


def test_decode_full_frame():
    raw = pipe_client.encode_frame({"kind": "ping"})
    decoded, consumed = pipe_client.try_decode_frame(raw)
    assert decoded == {"kind": "ping"}
    assert consumed == len(raw)


def test_decode_partial_frame_returns_none():
    raw = pipe_client.encode_frame({"kind": "ping"})
    decoded, consumed = pipe_client.try_decode_frame(raw[:5])
    assert decoded is None
    assert consumed == 0


def test_decode_oversized_frame_raises():
    # Header claims 1 MB
    raw = (1024 * 1024).to_bytes(4, "big") + b"x"
    with pytest.raises(pipe_client.WireError):
        pipe_client.try_decode_frame(raw)


def test_decode_invalid_json_raises():
    raw = (4).to_bytes(4, "big") + b"badd"
    with pytest.raises(pipe_client.WireError):
        pipe_client.try_decode_frame(raw)
