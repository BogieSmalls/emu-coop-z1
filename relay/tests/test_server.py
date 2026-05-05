import asyncio
import json
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
