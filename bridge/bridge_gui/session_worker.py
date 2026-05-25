"""Worker thread that drives the bridge during a session.

Runs the same loop as bridge_cli.cmd_run, but emits events to a thread-safe
queue that the GUI consumes via tkinter's after() callback.
"""
from __future__ import annotations

import queue
import socket
import threading
import time
import uuid
from importlib import import_module
from typing import Any

import serial

from bridge_core import __version__
from bridge_core.cc_client import CCClient
from bridge_core.cc_endpoint import CCMemoryEndpoint
from bridge_core.edn8_overload import tloz_all_overload_options
from bridge_core.map_write_gate import MapWriteGate
from bridge_core.mister_helper import MisterHelperMemoryEndpoint
from bridge_core.pipe_client import PipeClient
from bridge_core.session_diagnostics import SessionDiagnostics
from bridge_core.sync_engine import SyncEngine
from bridge_core.sync_probe import endpoint_error, read_running_probe_detail


MISTER_RAM_SAMPLE_RANGES = [
    (0x0012, 1),
    (0x0657, 1),
    (0x065A, 1),
    (0x0660, 1),
    (0x0671, 1),
]
MISTER_RAM_SAMPLE_ADDRS = [addr for addr, _length in MISTER_RAM_SAMPLE_RANGES]


def edn8_overload_options(cfg: dict) -> dict[str, int | bool]:
    return tloz_all_overload_options(
        cfg.get("endpoint_type", "edn8"),
        cfg.get("mode", ""),
    )


class SessionEvent:
    """Tagged event passed from worker to GUI thread."""

    def __init__(self, kind: str, **kwargs: Any) -> None:
        self.kind = kind
        self.data = kwargs


class SessionWorker:
    POLL_HZ = 10
    POLL_PERIOD = 1.0 / POLL_HZ

    def __init__(self, config: dict, event_queue: queue.Queue) -> None:
        self._config = config
        self._events = event_queue
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _emit(self, kind: str, **kwargs: Any) -> None:
        self._events.put(SessionEvent(kind, **kwargs))

    def _open_endpoint(self, cfg: dict):
        endpoint_type = cfg.get("endpoint_type", "edn8")
        if endpoint_type == "edn8":
            self._emit("log", text=f"Opening serial port {cfg['com_port']}")
            sp = serial.Serial(cfg["com_port"], baudrate=115200, timeout=0)
            cc = CCClient(sp)
            return CCMemoryEndpoint(cc)

        if endpoint_type == "mister":
            host = cfg.get("mister_host")
            if not host:
                raise ValueError("mister_host is required for MiSTer sessions")
            port = int(cfg.get("mister_port", 55355))
            timeout = float(cfg.get("mister_timeout", 1.0))
            self._emit("log", text=f"Connecting to MiSTer helper {host}:{port}")
            return MisterHelperMemoryEndpoint(host=host, port=port, timeout=timeout)

        raise ValueError(f"unknown endpoint type: {endpoint_type}")

    def _run(self) -> None:
        cfg = self._config
        try:
            self._emit("log", text=f"Loading mode: {cfg['mode']}")
            mode = import_module(f"bridge_core.modes.{cfg['mode']}")

            endpoint = self._open_endpoint(cfg)
            self._emit("cart_usb", connected=True)

            self._emit("log", text=f"Connecting to relay {cfg['relay']}:{cfg['relay_port']}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((cfg["relay"], cfg["relay_port"]))
            sock.setblocking(False)

            peer_id = uuid.uuid4().hex
            pipe = PipeClient(socket=sock, code=cfg["code"], peer_id=peer_id)
            pipe._reconnect_enabled = True
            diagnostics = SessionDiagnostics(
                endpoint_type=cfg.get("endpoint_type", "edn8"),
                mode_name=cfg["mode"],
                com_port=cfg.get("com_port", ""),
                peer_id=peer_id,
            )
            self._emit_diagnostics(diagnostics, force=True)
            map_write_gate = MapWriteGate() if cfg.get("endpoint_type", "edn8") == "edn8" else None
            if map_write_gate is not None:
                self._emit("log", text="EDN8 map write gate enabled")
            overload_options = edn8_overload_options(cfg)
            if overload_options:
                self._emit("log", text="EDN8 tloz_all overload protection enabled")
            defer_full_poll_while_map_pending = bool(
                overload_options.get("defer_full_poll_while_map_pending", False)
            )
            engine = SyncEngine(
                endpoint=endpoint,
                mode=mode,
                map_write_gate=map_write_gate,
                resync_send_limit=overload_options.get("resync_send_limit"),
            )
            if cfg.get("force_send"):
                engine.force_send = True

            pipe.on_data = lambda body: self._on_data(engine, diagnostics, body)
            pipe.on_abort = lambda reason: self._emit("message", text=f"Partner aborted: {reason}")
            pipe.on_partner_reconnected = lambda: self._on_partner_reconnected(engine, diagnostics)
            pipe.send_join()
            self._emit("net_relay", connected=True)

            app_hello_sent = False
            last_state: str | None = None
            last_map_backlog_log_at = 0.0
            last_diagnostics_emit_at = 0.0
            last_mister_sample_at = -999.0

            # Loop until user stops the worker or the pipe is fully closed.
            # We deliberately keep going through FAILED/RECONNECTING so the
            # underlying PipeClient can re-handshake with the relay on its own
            # backoff schedule and we keep updating the GUI accordingly.
            while not self._stop_flag.is_set() and pipe.state != "CLOSED":
                loop_start = time.monotonic()

                # When pipe wants to reconnect, open a fresh socket and re-JOIN.
                if pipe.state == "RECONNECTING":
                    retry_at = pipe._next_retry_at or 0
                    if loop_start >= retry_at:
                        try:
                            new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            new_sock.connect((cfg["relay"], cfg["relay_port"]))
                            new_sock.setblocking(False)
                            pipe.reset_for_reconnect(new_sock)
                            pipe.send_join()
                            self._emit("log", text=f"Relay reconnect attempt #{pipe._reconnect_attempt}")
                            sock = new_sock  # so we can close it on shutdown
                        except Exception as e:
                            self._emit("log", text=f"Reconnect attempt failed: {e}")
                            diagnostics.last_endpoint_error = str(e)
                            # PipeClient already advanced backoff via _next_backoff;
                            # bump _next_retry_at to defer the next try.
                            pipe._next_retry_at = loop_start + pipe._next_backoff()

                pipe.tick()
                pipe.heartbeat_tick()

                # Surface every state transition to the GUI
                if pipe.state != last_state:
                    diagnostics.set_relay_state(
                        pipe.state,
                        reconnect_attempt=getattr(pipe, "_reconnect_attempt", 0),
                    )
                    self._emit_diagnostics(diagnostics, force=True)
                    self._emit("state", state=pipe.state)
                    if pipe.state == "RECONNECTING":
                        self._emit("message", text="Partner disconnected; reconnecting…")
                        self._emit("net_partner", paired=False)
                        # On the next ESTABLISHED, send our app hello again
                        app_hello_sent = False
                    elif pipe.state == "FAILED":
                        self._emit("message", text="Connection failed (no reconnect available).")
                        self._emit("net_partner", paired=False)
                        self._emit("net_relay", connected=False)
                    last_state = pipe.state

                if pipe.state == "ESTABLISHED" and not app_hello_sent:
                    pipe.send_data({"op": "hello", "guid": mode.GUID, "version": __version__})
                    app_hello_sent = True
                    self._emit("net_partner", paired=True)

                if pipe.state == "ESTABLISHED":
                    try:
                        running_probe_detail = read_running_probe_detail(
                            endpoint,
                            mode,
                            timeout_ms=300,
                        )
                        running_probe = running_probe_detail.running
                    except Exception as e:
                        error = endpoint_error(e)
                        diagnostics.record_running_probe(
                            success=False,
                            frame=getattr(endpoint, "last_frame", None),
                            error=error,
                        )
                        self._emit("log", text=f"Endpoint read failed: {error}", level="ERROR")
                        running_probe = None
                    else:
                        probe_error = None
                        if running_probe is None:
                            probe_error = (
                                getattr(endpoint, "last_error", None)
                                or "running probe timed out"
                            )
                        diagnostics.record_running_probe(
                            success=running_probe is not None,
                            running=running_probe,
                            addr=running_probe_detail.addr,
                            value=running_probe_detail.value,
                            frame=getattr(endpoint, "last_frame", None),
                            error=probe_error,
                        )
                    if running_probe is None:
                        full_snapshot = None
                    elif not running_probe:
                        if (
                            cfg.get("endpoint_type") == "mister"
                            and loop_start - last_mister_sample_at >= 1.0
                        ):
                            self._record_mister_ram_sample(endpoint, diagnostics)
                            last_mister_sample_at = loop_start
                        if engine.observe_not_running():
                            self._emit("cart_game", running=False)
                            self._emit("log", text="Game stopped running; pausing sync")
                        full_snapshot = None
                    else:
                        for msg in engine.drain_map_write_gate():
                            self._emit("message", text=msg)
                        diagnostics.set_backlogs(
                            map_backlog=engine.map_write_pending_count,
                            resync_backlog=engine.resync_send_pending_count,
                        )
                        if (
                            defer_full_poll_while_map_pending
                            and engine.map_write_pending_count > 0
                        ):
                            diagnostics.record_deferred_full_poll(
                                map_backlog=engine.map_write_pending_count,
                                resync_backlog=engine.resync_send_pending_count,
                            )
                            if loop_start - last_map_backlog_log_at >= 1.0:
                                self._emit(
                                    "log",
                                    text=(
                                        f"EDN8 map backlog {engine.map_write_pending_count}; "
                                        "throttling full poll"
                                    ),
                                )
                                last_map_backlog_log_at = loop_start
                            self._send_resync_chunk(engine, pipe, diagnostics)
                            full_snapshot = None
                        elif engine.resync_send_pending_count > 0:
                            self._send_resync_chunk(engine, pipe, diagnostics)
                            full_snapshot = None
                        else:
                            try:
                                full_snapshot = endpoint.read_ranges(mode.READ_RANGES, timeout_ms=300)
                            except Exception as e:
                                error = endpoint_error(e)
                                diagnostics.record_full_poll(success=False, error=error)
                                self._emit("log", text=f"Endpoint read failed: {error}", level="ERROR")
                                full_snapshot = None
                            else:
                                diagnostics.record_full_poll(
                                    success=full_snapshot is not None,
                                    error="full poll timed out" if full_snapshot is None else None,
                                )
                                if (
                                    cfg.get("endpoint_type") == "mister"
                                    and full_snapshot is not None
                                ):
                                    self._record_mister_snapshot_sample(
                                        full_snapshot,
                                        diagnostics,
                                    )
                    if full_snapshot is not None:
                        invalid_reason = engine.implausible_snapshot_reason(full_snapshot)
                        if invalid_reason:
                            self._emit(
                                "log",
                                text=f"Ignoring implausible endpoint snapshot: {invalid_reason}",
                                level="WARNING",
                            )
                            full_snapshot = None
                    if full_snapshot is not None:
                        running = engine.is_game_running(full_snapshot)
                        self._emit("cart_game", running=running)
                        if running:
                            engine.observe_running()
                            if not engine.did_cache:
                                to_send = engine.check_first_running(full_snapshot)
                                for addr, value in to_send:
                                    diagnostics.record_outgoing_update(addr, value)
                                    pipe.send_data({"addr": addr, "value": value})
                                if engine.resync_send_pending_count:
                                    self._emit(
                                        "log",
                                        text=(
                                            "EDN8 tloz_all resync queued "
                                            f"{engine.resync_send_pending_count} updates"
                                        ),
                                    )
                            for result in engine.drain_sleep_queue_results():
                                self._record_incoming_result(diagnostics, result)
                                self._emit_result_messages(diagnostics, result)
                            for addr, send_value, msg in engine.diff(full_snapshot):
                                diagnostics.record_outgoing_update(addr, send_value)
                                pipe.send_data({"addr": addr, "value": send_value})
                                if msg:
                                    self._emit("message", text=msg)
                        elif engine.observe_not_running():
                            self._emit("cart_game", running=False)
                            self._emit("log", text="Game stopped running; pausing sync")

                elapsed = time.monotonic() - loop_start
                diagnostics.set_backlogs(
                    map_backlog=engine.map_write_pending_count,
                    resync_backlog=engine.resync_send_pending_count,
                )
                if loop_start - last_diagnostics_emit_at >= 1.0:
                    self._emit_diagnostics(diagnostics)
                    last_diagnostics_emit_at = loop_start
                sleep = self.POLL_PERIOD - elapsed
                if sleep > 0:
                    time.sleep(sleep)

            pipe.close()
            endpoint.close()
            sock.close()
            self._emit("state", state="DISCONNECTED")
        except Exception as e:
            self._emit("log", text=f"ERROR: {e}", level="ERROR")
            self._emit("state", state="FAILED")

    def _emit_diagnostics(self, diagnostics: SessionDiagnostics, *, force: bool = False) -> None:
        self._emit("diagnostics", text=diagnostics.render_text())

    def _record_mister_ram_sample(
        self,
        endpoint,
        diagnostics: SessionDiagnostics,
    ) -> None:
        try:
            snapshot = endpoint.read_ranges(MISTER_RAM_SAMPLE_RANGES, timeout_ms=300)
        except Exception as exc:
            diagnostics.last_endpoint_error = endpoint_error(exc)
            return
        if snapshot is None:
            diagnostics.last_endpoint_error = (
                getattr(endpoint, "last_error", None)
                or "MiSTer RAM sample timed out"
            )
            return
        self._record_mister_snapshot_sample(snapshot, diagnostics)

    @staticmethod
    def _record_mister_snapshot_sample(
        snapshot: dict[int, int],
        diagnostics: SessionDiagnostics,
    ) -> None:
        diagnostics.record_endpoint_sample(
            {
                addr: snapshot[addr]
                for addr in MISTER_RAM_SAMPLE_ADDRS
                if addr in snapshot
            }
        )

    def _on_partner_reconnected(
        self,
        engine: SyncEngine,
        diagnostics: SessionDiagnostics,
    ) -> None:
        """Fired by PipeClient when the relay reports the partner is back.
        Resync re-broadcasts our full state to the new partner."""
        self._emit("message", text="Partner reconnected — re-syncing state")
        diagnostics.record_partner_reconnect()
        engine.resync()
        diagnostics.set_backlogs(
            map_backlog=engine.map_write_pending_count,
            resync_backlog=engine.resync_send_pending_count,
        )
        self._emit_diagnostics(diagnostics, force=True)

    def _send_resync_chunk(
        self,
        engine: SyncEngine,
        pipe: PipeClient,
        diagnostics: SessionDiagnostics,
    ) -> None:
        for addr, value in engine.drain_resync_send_queue():
            diagnostics.record_outgoing_update(addr, value)
            pipe.send_data({"addr": addr, "value": value})

    def _on_data(
        self,
        engine: SyncEngine,
        diagnostics: SessionDiagnostics,
        body: dict,
    ) -> None:
        if body.get("op") == "hello":
            if body.get("guid") != engine.mode.GUID:
                self._emit("message", text=f"Partner has incompatible mode (guid mismatch)")
                return
            self._emit(
                "log",
                text=f"Partner app hello OK (guid={body['guid']}, version={body.get('version')})",
            )
            return
        addr = body.get("addr")
        value = body.get("value")
        if addr is not None and value is not None:
            diagnostics.record_incoming_update(int(addr), int(value))
        result = engine.handle_table_result(body)
        self._record_incoming_result(diagnostics, result)
        self._emit_result_messages(diagnostics, result)
        diagnostics.set_backlogs(
            map_backlog=engine.map_write_pending_count,
            resync_backlog=engine.resync_send_pending_count,
        )
        self._emit_diagnostics(diagnostics, force=True)

    def _record_incoming_result(
        self,
        diagnostics: SessionDiagnostics,
        result,
    ) -> None:
        if result.addr is None or result.incoming_value is None:
            return
        diagnostics.record_incoming_result(
            result.addr,
            result.incoming_value,
            applied=result.applied,
            previous_value=result.previous_value,
            written_value=result.written_value,
            status=result.status,
            messages=result.messages,
        )

    def _emit_result_messages(self, diagnostics: SessionDiagnostics, result) -> None:
        for msg in result.messages:
            if msg.startswith("Could not read address"):
                diagnostics.record_incoming_read_error(msg)
            elif msg.startswith("Could not write address"):
                diagnostics.record_incoming_write_error(msg)
            self._emit("message", text=msg)
