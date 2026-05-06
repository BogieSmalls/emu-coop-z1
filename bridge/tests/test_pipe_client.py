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


from bridge_core.pipe_client import PipeClient, PROTOCOL_VERSION


def test_pipe_client_sends_join_on_open():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    # Drain partner_sock and decode
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    decoded, _ = pipe_client.try_decode_frame(bytes(raw))
    assert decoded == {"kind": "join", "code": "abcdef", "peer_id": "p1"}


def test_pipe_client_handles_joined_then_sends_hello():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    # Drain join
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    # Partner sends "joined"
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    # Tick the pipe
    for _ in range(5):
        pipe.tick()
    # Now bridge should have sent hello
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    decoded, _ = pipe_client.try_decode_frame(bytes(raw))
    assert decoded == {"kind": "hello", "v": PROTOCOL_VERSION}


def test_pipe_client_reaches_established_after_partner_hello():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    for _ in range(5):
        pipe.tick()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    # Partner sends hello
    partner_sock.send(pipe_client.encode_frame({"kind": "hello", "v": PROTOCOL_VERSION}))
    for _ in range(5):
        pipe.tick()
    assert pipe.state == "ESTABLISHED"


def test_pipe_client_aborts_on_version_mismatch():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    for _ in range(5):
        pipe.tick()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "hello", "v": 999}))
    for _ in range(5):
        pipe.tick()
    assert pipe.state == "FAILED"


def test_heartbeat_sends_ping_after_interval():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Advance clock past 5s interval
    pipe._clock = lambda: 5.1
    pipe.heartbeat_tick()
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    frame, _ = pipe_client.try_decode_frame(bytes(raw))
    assert frame == {"kind": "ping"}


def test_heartbeat_fails_after_timeout():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Advance past 15s timeout
    pipe._clock = lambda: 15.5
    pipe.heartbeat_tick()
    assert pipe.state == "FAILED"


def test_heartbeat_does_not_fail_with_recent_traffic():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Simulate inbound traffic (resets _last_rx)
    pipe._clock = lambda: 10.0
    pipe._last_rx = 10.0
    pipe._clock = lambda: 20.0  # 10s after last RX, well under 15s timeout
    pipe.heartbeat_tick()
    assert pipe.state == "ESTABLISHED"


def test_fail_with_reconnect_enabled_goes_to_reconnecting():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._reconnect_enabled = True
    pipe._fail("test failure")
    assert pipe.state == "RECONNECTING"


def test_backoff_sequence():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    expected = [1, 2, 4, 8, 16, 30, 30, 30]
    for want in expected:
        assert pipe._next_backoff() == want
