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

from bridge_core.cc_client import CCClient
from bridge_core.pipe_client import PipeClient
from bridge_core.sync_engine import SyncEngine


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

    def _run(self) -> None:
        cfg = self._config
        try:
            self._emit("log", text=f"Loading mode: {cfg['mode']}")
            mode = import_module(f"bridge_core.modes.{cfg['mode']}")

            self._emit("log", text=f"Opening serial port {cfg['com_port']}")
            sp = serial.Serial(cfg["com_port"], baudrate=115200, timeout=0)
            cc = CCClient(sp)
            self._emit("cart_usb", connected=True)

            self._emit("log", text=f"Connecting to relay {cfg['relay']}:{cfg['relay_port']}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((cfg["relay"], cfg["relay_port"]))
            sock.setblocking(False)

            peer_id = uuid.uuid4().hex
            pipe = PipeClient(socket=sock, code=cfg["code"], peer_id=peer_id)
            pipe._reconnect_enabled = True
            engine = SyncEngine(cc_client=cc, mode=mode)
            if cfg.get("force_send"):
                engine.force_send = True

            pipe.on_data = lambda body: self._on_data(engine, body)
            pipe.on_abort = lambda reason: self._emit("message", text=f"Partner aborted: {reason}")
            pipe.on_partner_reconnected = lambda: self._on_partner_reconnected(engine)
            pipe.send_join()
            self._emit("net_relay", connected=True)

            app_hello_sent = False
            last_state: str | None = None

            # Loop until user stops the worker or the pipe is fully closed.
            # We deliberately keep going through FAILED/RECONNECTING so the
            # underlying PipeClient can re-handshake with the relay on its own
            # backoff schedule and we keep updating the GUI accordingly.
            while not self._stop_flag.is_set() and pipe.state != "CLOSED":
                loop_start = time.monotonic()
                pipe.tick()
                pipe.heartbeat_tick()

                # Surface every state transition to the GUI
                if pipe.state != last_state:
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
                    pipe.send_data({"op": "hello", "guid": mode.GUID, "version": "0.1.0"})
                    app_hello_sent = True
                    self._emit("net_partner", paired=True)

                if pipe.state == "ESTABLISHED":
                    full_snapshot = cc.read_ranges(mode.READ_RANGES, timeout_ms=300)
                    if full_snapshot is not None:
                        running = engine.is_game_running(full_snapshot)
                        self._emit("cart_game", running=running)
                        if running:
                            if not engine.did_cache:
                                to_send = engine.check_first_running(full_snapshot)
                                for addr, value in to_send:
                                    pipe.send_data({"addr": addr, "value": value})
                            for addr, send_value, msg in engine.diff(full_snapshot):
                                pipe.send_data({"addr": addr, "value": send_value})
                                if msg:
                                    self._emit("message", text=msg)
                        else:
                            if engine.did_cache:
                                self._emit("log", text="Game stopped running; pausing sync")
                                engine.did_cache = False

                elapsed = time.monotonic() - loop_start
                sleep = self.POLL_PERIOD - elapsed
                if sleep > 0:
                    time.sleep(sleep)

            pipe.close()
            sp.close()
            sock.close()
            self._emit("state", state="DISCONNECTED")
        except Exception as e:
            self._emit("log", text=f"ERROR: {e}", level="ERROR")
            self._emit("state", state="FAILED")

    def _on_partner_reconnected(self, engine: SyncEngine) -> None:
        """Fired by PipeClient when the relay reports the partner is back.
        Resync re-broadcasts our full state to the new partner."""
        self._emit("message", text="Partner reconnected — re-syncing state")
        engine.resync()

    def _on_data(self, engine: SyncEngine, body: dict) -> None:
        if body.get("op") == "hello":
            if body.get("guid") != engine.mode.GUID:
                self._emit("message", text=f"Partner has incompatible mode (guid mismatch)")
                return
            self._emit("log", text=f"Partner app hello OK (guid={body['guid']})")
            return
        for msg in engine.handle_table(body):
            self._emit("message", text=msg)
