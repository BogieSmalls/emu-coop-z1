"""emu-coop relay server.

State machine per session code:
  WAITING (1 peer) -> PAIRED (2 peers) -> closed

(HALF_BROKEN/grace-window logic is added in Task 17.)
"""
import asyncio
import hashlib
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
GRACE_SECONDS = int(os.environ.get("RELAY_GRACE_SECONDS", "60"))


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using %d", name, raw, default)
        return default


TRACE_FRAMES = _env_bool("RELAY_TRACE_FRAMES", True)
TRACE_PAYLOADS = _env_bool("RELAY_TRACE_PAYLOADS", True)
TRACE_PAYLOAD_CHARS = _env_int("RELAY_TRACE_PAYLOAD_CHARS", MAX_PAYLOAD)
SENSITIVE_KEYS = {"code", "session_code"}
PEER_ID_KEYS = {"peer_id", "partner_peer_id"}


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
    grace_task: Optional[asyncio.Task] = None
    broken_peer_id: Optional[str] = None  # peer_id that dropped during HALF_BROKEN


_sessions: dict = {}  # code -> Session


def _reset_state():
    """Test helper: clear in-memory state."""
    _sessions.clear()


def encode_frame(obj):
    payload = json.dumps(obj).encode()
    return struct.pack(">I", len(payload)) + payload


def _session_label(code):
    return hashlib.sha256(code.encode()).hexdigest()[:8]


def _peer_label(peer):
    return peer.peer_id[:6]


def _redact_value(value):
    if isinstance(value, str) and value:
        return f"<redacted:{hashlib.sha256(value.encode()).hexdigest()[:8]}>"
    return "<redacted>"


def _short_peer_value(value):
    if isinstance(value, str):
        return value[:6]
    return value


def _sanitize_payload(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in SENSITIVE_KEYS:
                out[key] = _redact_value(value)
            elif key in PEER_ID_KEYS:
                out[key] = _short_peer_value(value)
            else:
                out[key] = _sanitize_payload(value)
        return out
    if isinstance(obj, list):
        return [_sanitize_payload(item) for item in obj]
    return obj


def _frame_summary(frame):
    if not isinstance(frame, dict):
        return {"type": type(frame).__name__}

    summary = {}
    if "kind" in frame:
        summary["kind"] = frame["kind"]

    for key in ("v", "version", "reason", "op", "addr", "value", "peer_id"):
        if key in frame:
            summary[key] = frame[key]

    body = frame.get("body")
    if isinstance(body, dict):
        body_summary = {}
        for key in (
            "op",
            "addr",
            "value",
            "mask",
            "bits",
            "slot",
            "item",
            "flag",
            "guid",
            "version",
        ):
            if key in body:
                body_summary[key] = body[key]
        if body_summary:
            summary["body"] = body_summary

    return _sanitize_payload(summary)


def _json_for_log(obj):
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    if TRACE_PAYLOAD_CHARS > 0 and len(text) > TRACE_PAYLOAD_CHARS:
        return text[:TRACE_PAYLOAD_CHARS] + "...<truncated>"
    return text


def _payload_for_log(frame):
    if TRACE_PAYLOADS:
        return _json_for_log(_sanitize_payload(frame))
    return _json_for_log(_frame_summary(frame))


class FrameTracer:
    def __init__(self, session_code, src, dst):
        self.session_code = session_code
        self.src = src
        self.dst = dst
        self.buffer = bytearray()
        self.frame_count = 0

    def feed(self, data):
        if not TRACE_FRAMES:
            return
        self.buffer.extend(data)
        while len(self.buffer) >= 4:
            size = struct.unpack(">I", self.buffer[:4])[0]
            if size > MAX_PAYLOAD:
                logger.warning(
                    "wire session=%s %s->%s malformed_frame size=%d buffered=%d",
                    _session_label(self.session_code),
                    _peer_label(self.src),
                    _peer_label(self.dst),
                    size,
                    len(self.buffer),
                )
                self.buffer.clear()
                return
            if len(self.buffer) < 4 + size:
                return
            raw = bytes(self.buffer[4 : 4 + size])
            del self.buffer[: 4 + size]
            self.frame_count += 1
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(
                    "wire session=%s %s->%s frame=%d bytes=%d malformed_json=%s raw=%s",
                    _session_label(self.session_code),
                    _peer_label(self.src),
                    _peer_label(self.dst),
                    self.frame_count,
                    size,
                    e,
                    raw[:64].hex(),
                )
                continue
            kind = frame.get("kind") if isinstance(frame, dict) else type(frame).__name__
            logger.info(
                "wire session=%s %s->%s frame=%d bytes=%d kind=%s payload=%s",
                _session_label(self.session_code),
                _peer_label(self.src),
                _peer_label(self.dst),
                self.frame_count,
                size,
                kind,
                _payload_for_log(frame),
            )


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
    logger.info(
        "join session=%s peer=%s remote=%s state=%s",
        _session_label(code),
        _peer_label(peer),
        writer.get_extra_info("peername"),
        sess.state if sess else "NEW",
    )

    if sess is None:
        if len(_sessions) >= MAX_PAIRS:
            await send_abort_close(writer, "relay full")
            return
        sess = Session(code=code)
        sess.peers[peer_id] = peer
        sess.state = "WAITING"
        sess.ttl_task = asyncio.create_task(_ttl_expire(sess))
        _sessions[code] = sess
        logger.info("session=%s state=WAITING peer=%s", _session_label(code), _peer_label(peer))
        peer.watcher_task = asyncio.create_task(_watch_for_eof(peer))
        await peer.done.wait()
        await _on_peer_disconnect(sess, peer)
        return

    if sess.state == "WAITING":
        if peer_id in sess.peers:
            # Same peer re-arriving (still waiting, partner hadn't shown)
            old = sess.peers[peer_id]
            if old.watcher_task:
                old.watcher_task.cancel()
            old.writer.close()
            sess.peers[peer_id] = peer
            logger.info("session=%s waiting_peer_replaced peer=%s", _session_label(code), _peer_label(peer))
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
        logger.info(
            "session=%s state=PAIRED peers=%s",
            _session_label(code),
            ",".join(_peer_label(p) for p in sess.peers.values()),
        )
        await _send_joined(sess)
        await _start_forwarding(sess)
        await peer.done.wait()
        await _on_peer_disconnect(sess, peer)
        return

    if sess.state == "PAIRED":
        if peer_id in sess.peers:
            # Reconnect of an existing paired peer; swap socket.
            old = sess.peers[peer_id]
            if old.forward_task:
                old.forward_task.cancel()
            try:
                old.writer.close()
            except Exception:
                pass
            sess.peers[peer_id] = peer
            logger.info("session=%s paired_peer_reconnected peer=%s", _session_label(code), _peer_label(peer))
            # Send partner-reconnected to the other peer
            other = next(p for pid, p in sess.peers.items() if pid != peer_id)
            try:
                other.writer.write(encode_frame({"kind": "partner-reconnected", "peer_id": peer_id}))
                await other.writer.drain()
            except Exception:
                pass
            # Send joined to the rejoining peer so it can re-do its hello
            try:
                peer.writer.write(encode_frame({"kind": "joined"}))
                await peer.writer.drain()
            except Exception:
                pass
            # Restart forwarding for the rejoining peer
            peer.forward_task = asyncio.create_task(_forward(sess, peer, other))
            # Restart partner's forward task too if it ended on the dead socket
            if not other.forward_task or other.forward_task.done():
                other.forward_task = asyncio.create_task(_forward(sess, other, peer))
            await peer.done.wait()
            await _on_peer_disconnect(sess, peer)
            return
        # Third party with different peer_id
        logger.info("session=%s rejected peer=%s reason=code_in_use", _session_label(code), _peer_label(peer))
        await send_abort_close(writer, "code in use")
        return

    if sess.state == "HALF_BROKEN":
        if peer_id in sess.peers:
            # Survivor reconnecting — their socket dropped during the grace
            # window (e.g., bridge's heartbeat timeout closed its end). Swap
            # the survivor's socket and stay in HALF_BROKEN waiting for the
            # broken peer to return.
            old = sess.peers[peer_id]
            if old.watcher_task:
                old.watcher_task.cancel()
            if old.forward_task:
                old.forward_task.cancel()
            try:
                old.writer.close()
            except Exception:
                pass
            # Unblock the old handle_client so it can RTS cleanly.
            old.done.set()
            sess.peers[peer_id] = peer
            logger.info("session=%s half_broken_survivor_replaced peer=%s", _session_label(code), _peer_label(peer))
            try:
                peer.writer.write(encode_frame({"kind": "joined"}))
                await peer.writer.drain()
            except Exception:
                pass
            # Watcher keeps the new survivor's socket EOF detectable
            peer.watcher_task = asyncio.create_task(_watch_for_eof(peer))
            await peer.done.wait()
            await _on_peer_disconnect(sess, peer)
            return

        # Different peer_id — it's the broken peer returning (under any
        # peer_id, since clients generate a fresh uuid each launch). Promote
        # back to PAIRED.
        if sess.grace_task:
            sess.grace_task.cancel()
            sess.grace_task = None
        sess.peers[peer_id] = peer
        sess.state = "PAIRED"
        sess.broken_peer_id = None
        logger.info("session=%s state=PAIRED recovered_peer=%s", _session_label(code), _peer_label(peer))
        other = next(p for pid, p in sess.peers.items() if pid != peer_id)
        # Stop the survivor's watcher_task — forwarding takes back over.
        if other.watcher_task:
            other.watcher_task.cancel()
            other.watcher_task = None
        # Send partner-reconnected to the survivor
        try:
            other.writer.write(encode_frame({"kind": "partner-reconnected", "peer_id": peer_id}))
            await other.writer.drain()
        except Exception:
            pass
        try:
            peer.writer.write(encode_frame({"kind": "joined"}))
            await peer.writer.drain()
        except Exception:
            pass
        peer.forward_task = asyncio.create_task(_forward(sess, peer, other))
        if not other.forward_task or other.forward_task.done():
            other.forward_task = asyncio.create_task(_forward(sess, other, peer))
        await peer.done.wait()
        await _on_peer_disconnect(sess, peer)
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
    a.forward_task = asyncio.create_task(_forward(sess, a, b))
    b.forward_task = asyncio.create_task(_forward(sess, b, a))


async def _forward(sess, src, dst):
    """Shuttle bytes from src.reader to dst.writer.

    Sets src.done ONLY when src disconnected (reader EOF or read error). If
    the WRITE side fails (dst is dead), exit silently — the OTHER _forward
    task will detect dst's read EOF and set dst.done. Conflating the two
    causes the relay to tear down a session when only one peer dropped, which
    leaves the survivor's reconnect attempts unable to find their slot.
    """
    src_disconnected = False
    tracer = FrameTracer(sess.code, src, dst)
    try:
        while True:
            try:
                data = await asyncio.wait_for(src.reader.read(4096), timeout=IDLE_SECONDS)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError):
                logger.info("session=%s forward_read_closed peer=%s", _session_label(sess.code), _peer_label(src))
                src_disconnected = True
                break
            if not data:
                logger.info("session=%s forward_eof peer=%s", _session_label(sess.code), _peer_label(src))
                src_disconnected = True
                break
            tracer.feed(data)
            try:
                dst.writer.write(data)
                await dst.writer.drain()
            except (ConnectionError, BrokenPipeError, OSError):
                # dst died; let the other forwarder handle dst.done.
                logger.info(
                    "session=%s forward_write_closed src=%s dst=%s",
                    _session_label(sess.code),
                    _peer_label(src),
                    _peer_label(dst),
                )
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.info("forward error: %s", e)
        src_disconnected = True
    finally:
        if src_disconnected:
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
    logger.info("watcher_eof peer=%s", _peer_label(peer))
    peer.done.set()


async def _cancel_forward_task(peer):
    if not peer.forward_task:
        return
    task = peer.forward_task
    peer.forward_task = None
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
        logger.info(
            "session=%s state=CLOSED peer=%s reason=waiting_peer_disconnected",
            _session_label(sess.code),
            _peer_label(peer),
        )
        return
    if sess.state == "PAIRED":
        # Enter HALF_BROKEN: keep partner around for the grace window.
        dropped_id = peer.peer_id
        sess.peers.pop(dropped_id, None)
        sess.state = "HALF_BROKEN"
        sess.broken_peer_id = dropped_id
        sess.grace_task = asyncio.create_task(_grace_expire(sess))
        logger.info(
            "session=%s state=HALF_BROKEN dropped=%s grace=%d",
            _session_label(sess.code),
            _peer_label(peer),
            GRACE_SECONDS,
        )
        # Start a watcher on the survivor's socket so we detect if the
        # survivor also disconnects during the grace window (e.g. heartbeat
        # timeout). Without this, the survivor's connection just hangs and
        # the relay never notices, leaving stale state when they reconnect.
        survivor = next(iter(sess.peers.values()), None)
        if survivor and not survivor.watcher_task:
            await _cancel_forward_task(survivor)
            survivor.watcher_task = asyncio.create_task(_watch_for_eof(survivor))
        return
    if sess.state == "HALF_BROKEN":
        # Survivor also dropped. Keep the HALF_BROKEN session until grace
        # expires so the survivor can reconnect with the same peer_id.
        logger.info(
            "session=%s state=HALF_BROKEN peer=%s reason=survivor_offline",
            _session_label(sess.code),
            _peer_label(peer),
        )


async def _ttl_expire(sess):
    try:
        await asyncio.sleep(TTL_SECONDS)
        for p in sess.peers.values():
            await send_abort_close(p.writer, "no partner")
        _sessions.pop(sess.code, None)
        logger.info("session=%s state=CLOSED reason=ttl_expired", _session_label(sess.code))
    except asyncio.CancelledError:
        pass


async def _grace_expire(sess):
    try:
        await asyncio.sleep(GRACE_SECONDS)
        for p in sess.peers.values():
            await send_abort_close(p.writer, "partner did not return")
        _sessions.pop(sess.code, None)
        logger.info("session=%s state=CLOSED reason=grace_expired", _session_label(sess.code))
    except asyncio.CancelledError:
        pass


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    logger.info(
        "relay listening on 0.0.0.0:%d trace_frames=%s trace_payloads=%s trace_payload_chars=%d",
        PORT,
        TRACE_FRAMES,
        TRACE_PAYLOADS,
        TRACE_PAYLOAD_CHARS,
    )
    async with s:
        await s.serve_forever()
