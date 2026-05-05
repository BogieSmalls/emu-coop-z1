"""emu-coop relay server.

State machine per session code:
  WAITING (1 peer) -> PAIRED (2 peers) -> closed

(HALF_BROKEN/grace-window logic is added in Task 17.)
"""
import asyncio
import json
import logging
import os
import struct
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("relay")
MAX_PAYLOAD = 4096
PORT = int(os.environ.get("RELAY_PORT", "9999"))
MAX_PAIRS = int(os.environ.get("RELAY_MAX_PAIRS", "100"))
TTL_SECONDS = int(os.environ.get("RELAY_TTL_SECONDS", "600"))
IDLE_SECONDS = int(os.environ.get("RELAY_IDLE_SECONDS", "30"))


@dataclass
class Peer:
    peer_id: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    forward_task: Optional[asyncio.Task] = None
    watcher_task: Optional[asyncio.Task] = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class Session:
    code: str
    peers: dict = field(default_factory=dict)  # peer_id -> Peer
    state: str = "WAITING"
    ttl_task: Optional[asyncio.Task] = None


_sessions: dict = {}  # code -> Session


def _reset_state():
    """Test helper: clear in-memory state."""
    _sessions.clear()


def encode_frame(obj):
    payload = json.dumps(obj).encode()
    return struct.pack(">I", len(payload)) + payload


async def read_frame(reader):
    header = await reader.readexactly(4)
    (n,) = struct.unpack(">I", header)
    if n > MAX_PAYLOAD:
        raise ValueError(f"frame too large: {n}")
    body = await reader.readexactly(n)
    return json.loads(body)


async def send_abort_close(writer, reason):
    try:
        writer.write(encode_frame({"kind": "abort", "reason": reason}))
        await writer.drain()
    except Exception:
        pass
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def handle_client(reader, writer):
    try:
        join = await asyncio.wait_for(read_frame(reader), timeout=10)
    except Exception as e:
        logger.info("malformed first frame: %s", e)
        writer.close()
        return

    if join.get("kind") != "join":
        await send_abort_close(writer, "expected join")
        return

    code = join.get("code", "")
    peer_id = join.get("peer_id", "")
    if not isinstance(code, str) or len(code) < 6:
        await send_abort_close(writer, "session code too short")
        return
    if not isinstance(peer_id, str) or not peer_id:
        await send_abort_close(writer, "missing peer_id")
        return

    sess = _sessions.get(code)
    peer = Peer(peer_id=peer_id, reader=reader, writer=writer)

    if sess is None:
        if len(_sessions) >= MAX_PAIRS:
            await send_abort_close(writer, "relay full")
            return
        sess = Session(code=code)
        sess.peers[peer_id] = peer
        sess.state = "WAITING"
        sess.ttl_task = asyncio.create_task(_ttl_expire(sess))
        _sessions[code] = sess
        peer.watcher_task = asyncio.create_task(_watch_for_eof(peer))
        await peer.done.wait()
        await _on_peer_disconnect(sess, peer)
        return

    if sess.state == "WAITING":
        if peer_id in sess.peers:
            # Same peer re-arriving (should be rare without peer-id reconnect logic).
            old = sess.peers[peer_id]
            if old.watcher_task:
                old.watcher_task.cancel()
            old.writer.close()
            sess.peers[peer_id] = peer
            peer.watcher_task = asyncio.create_task(_watch_for_eof(peer))
            await peer.done.wait()
            await _on_peer_disconnect(sess, peer)
            return
        # Second peer; pair them.
        if sess.ttl_task:
            sess.ttl_task.cancel()
        # Cancel the first peer's watcher; forwarding will own the read side now.
        for p in sess.peers.values():
            if p.watcher_task:
                p.watcher_task.cancel()
                p.watcher_task = None
        sess.peers[peer_id] = peer
        sess.state = "PAIRED"
        await _send_joined(sess)
        await _start_forwarding(sess)
        await peer.done.wait()
        await _on_peer_disconnect(sess, peer)
        return

    if sess.state == "PAIRED":
        # Third party with different peer_id (matching peer_id reconnect is Task 17)
        await send_abort_close(writer, "code in use")
        return


async def _send_joined(sess):
    for p in sess.peers.values():
        try:
            p.writer.write(encode_frame({"kind": "joined"}))
            await p.writer.drain()
        except Exception:
            pass


async def _start_forwarding(sess):
    peers = list(sess.peers.values())
    a, b = peers[0], peers[1]
    a.forward_task = asyncio.create_task(_forward(a, b))
    b.forward_task = asyncio.create_task(_forward(b, a))


async def _forward(src, dst):
    """Shuttle bytes from src.reader to dst.writer until EOF or error.
    Sets src.done so handle_client knows this peer's session is over."""
    try:
        while True:
            data = await asyncio.wait_for(src.reader.read(4096), timeout=IDLE_SECONDS)
            if not data:
                break
            dst.writer.write(data)
            await dst.writer.drain()
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
        pass
    except Exception as e:
        logger.info("forward error: %s", e)
    finally:
        src.done.set()


async def _watch_for_eof(peer):
    """Read from peer until EOF or error, then set peer.done.
    Used during WAITING (before forwarding owns the read side). If cancelled
    (because we're transitioning to PAIRED), do NOT set done — forwarding takes over."""
    try:
        while True:
            data = await peer.reader.read(4096)
            if not data:
                break
            # Pre-pair traffic from a misbehaving peer; ignore.
    except asyncio.CancelledError:
        return  # transitioning to PAIRED; don't signal disconnect
    except Exception:
        pass
    peer.done.set()


async def _on_peer_disconnect(sess, peer):
    if peer.peer_id not in sess.peers or sess.peers[peer.peer_id] is not peer:
        return  # already replaced
    if peer.watcher_task:
        peer.watcher_task.cancel()
    if peer.forward_task:
        peer.forward_task.cancel()
    try:
        peer.writer.close()
    except Exception:
        pass
    if sess.state == "WAITING":
        sess.peers.pop(peer.peer_id, None)
        if sess.ttl_task:
            sess.ttl_task.cancel()
        _sessions.pop(sess.code, None)
        return
    if sess.state == "PAIRED":
        # Without HALF_BROKEN (Task 17), a disconnect tears down the whole session.
        for p in list(sess.peers.values()):
            if p is peer:
                continue
            if p.forward_task:
                p.forward_task.cancel()
            p.done.set()  # unblock that peer's handle_client
            try:
                p.writer.close()
            except Exception:
                pass
        sess.peers.clear()
        _sessions.pop(sess.code, None)


async def _ttl_expire(sess):
    try:
        await asyncio.sleep(TTL_SECONDS)
        for p in sess.peers.values():
            await send_abort_close(p.writer, "no partner")
        _sessions.pop(sess.code, None)
    except asyncio.CancelledError:
        pass


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    logger.info("relay listening on 0.0.0.0:%d", PORT)
    async with s:
        await s.serve_forever()
