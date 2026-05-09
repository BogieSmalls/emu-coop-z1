import asyncio
import json
import logging
import struct
import pytest

from relay import server

@pytest.fixture
async def relay_running():
    """Start a relay on an ephemeral port and yield (host, port)."""
    s = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    server._reset_state()
    task = asyncio.create_task(s.serve_forever())
    yield ("127.0.0.1", port)
    task.cancel()
    s.close()
    await s.wait_closed()

def encode_frame(obj):
    payload = json.dumps(obj).encode()
    return struct.pack(">I", len(payload)) + payload

async def read_frame(reader):
    header = await reader.readexactly(4)
    (n,) = struct.unpack(">I", header)
    body = await reader.readexactly(n)
    return json.loads(body)

async def open_peer(host, port):
    return await asyncio.open_connection(host, port)


def make_peer(peer_id):
    return server.Peer(peer_id=peer_id, reader=None, writer=None)


def test_frame_tracer_logs_full_payload_by_default(caplog):
    caplog.set_level(logging.INFO, logger="relay")
    tracer = server.FrameTracer("abcdef", make_peer("peer-one"), make_peer("peer-two"))

    tracer.feed(
        encode_frame(
            {
                "kind": "data",
                "body": {"addr": 0x0661, "value": 1, "extra": "kept"},
            }
        )
    )

    assert "peer-o->peer-t" in caplog.text
    assert '"addr":1633' in caplog.text
    assert '"extra":"kept"' in caplog.text


def test_frame_tracer_summarizes_payload_when_full_payload_logging_disabled(caplog, monkeypatch):
    monkeypatch.setattr(server, "TRACE_PAYLOADS", False)
    caplog.set_level(logging.INFO, logger="relay")
    tracer = server.FrameTracer("abcdef", make_peer("peer-one"), make_peer("peer-two"))

    tracer.feed(
        encode_frame(
            {
                "kind": "data",
                "body": {"addr": 0x0661, "value": 1, "extra": "omitted"},
            }
        )
    )

    assert '"addr":1633' in caplog.text
    assert '"value":1' in caplog.text
    assert "omitted" not in caplog.text


def test_frame_tracer_can_be_disabled(caplog, monkeypatch):
    monkeypatch.setattr(server, "TRACE_FRAMES", False)
    caplog.set_level(logging.INFO, logger="relay")
    tracer = server.FrameTracer("abcdef", make_peer("peer-one"), make_peer("peer-two"))

    tracer.feed(encode_frame({"kind": "ping"}))

    assert caplog.text == ""

async def test_pair_basic(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    await w1.drain()
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await w2.drain()
    f1 = await asyncio.wait_for(read_frame(r1), 2)
    f2 = await asyncio.wait_for(read_frame(r2), 2)
    assert f1["kind"] == "joined"
    assert f2["kind"] == "joined"
    w1.close(); w2.close()

async def test_code_too_short(relay_running):
    host, port = relay_running
    r, w = await open_peer(host, port)
    w.write(encode_frame({"kind": "join", "code": "abc", "peer_id": "p1"}))
    await w.drain()
    f = await asyncio.wait_for(read_frame(r), 2)
    assert f["kind"] == "abort"
    assert "too short" in f["reason"].lower()
    w.close()

async def test_code_collision(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    r3, w3 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)  # joined
    w3.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p3"}))
    await w3.drain()
    f = await asyncio.wait_for(read_frame(r3), 2)
    assert f["kind"] == "abort"
    assert "in use" in f["reason"].lower()
    for w in (w1, w2, w3): w.close()

async def test_byte_forwarding(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    w1.write(encode_frame({"kind": "hello", "v": 1}))
    await w1.drain()
    f = await asyncio.wait_for(read_frame(r2), 2)
    assert f["kind"] == "hello"
    assert f["v"] == 1
    for w in (w1, w2): w.close()


async def test_half_broken_rejoin_within_grace(relay_running, monkeypatch):
    monkeypatch.setattr(server, "GRACE_SECONDS", 5)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)  # joined

    # Peer 1 disconnects.
    w1.close(); await w1.wait_closed()
    await asyncio.sleep(0.5)  # allow relay to notice

    # Peer 1 reconnects within grace window.
    r1b, w1b = await open_peer(host, port)
    w1b.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    await w1b.drain()
    f1b = await asyncio.wait_for(read_frame(r1b), 3)
    assert f1b["kind"] == "joined"

    # Peer 2 should see partner-reconnected.
    f2 = await asyncio.wait_for(read_frame(r2), 3)
    assert f2["kind"] == "partner-reconnected"
    assert f2["peer_id"] == "p1"
    w1b.close(); w2.close()


async def test_grace_expires_closes_survivor(relay_running, monkeypatch):
    monkeypatch.setattr(server, "GRACE_SECONDS", 1)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    w1.close(); await w1.wait_closed()
    # Peer 2 should receive abort within ~1 second.
    f = await asyncio.wait_for(read_frame(r2), 3)
    assert f["kind"] == "abort"
    assert "did not return" in f["reason"].lower()
    w2.close()


async def test_one_peer_drop_does_not_tear_down_session(relay_running, monkeypatch):
    """Regression: when one peer drops, the survivor's session must be kept
    alive so it can rejoin or wait out the grace window. Previously the
    _forward task signaled the survivor's done event when its writes to the
    dead peer failed, which caused _on_peer_disconnect to tear down the
    HALF_BROKEN session immediately."""
    monkeypatch.setattr(server, "GRACE_SECONDS", 5)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    # Peer 1 drops uncleanly.
    w1.close(); await w1.wait_closed()
    # Give the relay time to process the drop and any cascading forward errors.
    await asyncio.sleep(1.0)
    # Session should still exist in HALF_BROKEN with peer 2 connected.
    sess = server._sessions.get("abcdef")
    assert sess is not None, "session was torn down when only one peer dropped"
    assert sess.state == "HALF_BROKEN"
    assert "p2" in sess.peers
    w2.close()


async def test_survivor_reconnect_during_half_broken(relay_running, monkeypatch):
    """Regression: when the survivor's socket drops during HALF_BROKEN (e.g.
    bridge's heartbeat timeout closed its end), and the survivor reconnects
    with the same peer_id, we must SWAP the socket and stay in HALF_BROKEN —
    not promote to PAIRED (which has no second peer and crashed the handler)."""
    monkeypatch.setattr(server, "GRACE_SECONDS", 10)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    # Peer 1 drops -> session HALF_BROKEN, p2 is survivor.
    w1.close(); await w1.wait_closed()
    await asyncio.sleep(0.5)
    sess = server._sessions.get("abcdef")
    assert sess is not None and sess.state == "HALF_BROKEN"
    # Now the survivor (p2) drops too, then reconnects with the SAME peer_id.
    w2.close(); await w2.wait_closed()
    await asyncio.sleep(0.5)
    # Session should still exist (grace timer keeps it).
    sess = server._sessions.get("abcdef")
    assert sess is not None and sess.state == "HALF_BROKEN"
    # Survivor reconnects with same peer_id.
    r2b, w2b = await open_peer(host, port)
    w2b.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await w2b.drain()
    f = await asyncio.wait_for(read_frame(r2b), 3)
    assert f["kind"] == "joined", f"expected joined, got {f}"
    # Session should still be HALF_BROKEN (waiting for p1 to return).
    sess = server._sessions.get("abcdef")
    assert sess is not None
    assert sess.state == "HALF_BROKEN", f"expected HALF_BROKEN, got {sess.state}"
    assert "p2" in sess.peers
    w2b.close()


async def test_half_broken_accepts_different_peer_id(relay_running, monkeypatch):
    """Regression: clients (Lua, bridge) generate a fresh peer_id on each
    process launch, so HALF_BROKEN must allow ANY peer_id to claim the
    broken slot — strict peer_id matching prevented restart-and-reconnect."""
    monkeypatch.setattr(server, "GRACE_SECONDS", 5)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1-original"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    # Peer 1 drops, then comes back with a NEW peer_id (simulating restart).
    w1.close(); await w1.wait_closed()
    await asyncio.sleep(0.5)
    r1b, w1b = await open_peer(host, port)
    w1b.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1-fresh-uuid"}))
    await w1b.drain()
    # Should be welcomed with 'joined', not aborted with 'code in use'.
    f1b = await asyncio.wait_for(read_frame(r1b), 3)
    assert f1b["kind"] == "joined", f"expected joined, got {f1b}"
    # Survivor should see partner-reconnected with the NEW peer_id.
    f2 = await asyncio.wait_for(read_frame(r2), 3)
    assert f2["kind"] == "partner-reconnected"
    assert f2["peer_id"] == "p1-fresh-uuid"
    w1b.close(); w2.close()
