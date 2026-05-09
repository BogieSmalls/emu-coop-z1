"""Relay sync loop for endpoints that support reads and writes."""
from __future__ import annotations

import time
from typing import Any

from bridge_core import __version__
from bridge_core.map_write_gate import MapWriteGate
from bridge_core.memory_endpoint import MemoryEndpoint
from bridge_core.status_sink import StatusSink
from bridge_core.sync_engine import SyncEngine
from bridge_core.sync_probe import endpoint_error, read_running_probe


class SyncSession:
    def __init__(
        self,
        *,
        endpoint: MemoryEndpoint,
        pipe: Any,
        mode: Any,
        sink: StatusSink,
        version: str = __version__,
        map_write_gate: MapWriteGate | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.pipe = pipe
        self.mode = mode
        self.sink = sink
        self.version = version
        self.engine = SyncEngine(endpoint=endpoint, mode=mode, map_write_gate=map_write_gate)
        self.app_hello_sent = False
        self.last_state: str | None = None
        self.pipe.on_data = self.on_data
        self.pipe.on_abort = lambda reason: self.sink.message(f"Partner aborted: {reason}")
        self.pipe.on_partner_reconnected = self._on_partner_reconnected

    def tick_once(self) -> None:
        self.pipe.tick()
        self.pipe.heartbeat_tick()
        if self.pipe.state != self.last_state:
            self.sink.state(self.pipe.state)
            self.last_state = self.pipe.state
        if self.pipe.state != "ESTABLISHED":
            return
        if not self.app_hello_sent:
            self.pipe.send_data(
                {"op": "hello", "guid": self.mode.GUID, "version": self.version}
            )
            self.app_hello_sent = True
        try:
            running = read_running_probe(self.endpoint, self.mode, timeout_ms=300)
        except Exception as exc:
            self.sink.log(f"Endpoint read failed: {endpoint_error(exc)}", level="ERROR")
            return
        if running is None:
            return
        if not running:
            if self.engine.did_cache:
                self.sink.log("Game stopped running; pausing sync")
                self.engine.did_cache = False
            return
        for message in self.engine.drain_map_write_gate():
            self.sink.message(message)
        try:
            snapshot = self.endpoint.read_ranges(self.mode.READ_RANGES, timeout_ms=300)
        except Exception as exc:
            self.sink.log(f"Endpoint read failed: {endpoint_error(exc)}", level="ERROR")
            return
        if snapshot is None:
            return
        invalid_reason = self.engine.implausible_snapshot_reason(snapshot)
        if invalid_reason:
            self.sink.log(
                f"Ignoring implausible endpoint snapshot: {invalid_reason}",
                level="WARNING",
            )
            return
        if self.engine.is_game_running(snapshot):
            if not self.engine.did_cache:
                for addr, value in self.engine.check_first_running(snapshot):
                    self.pipe.send_data({"addr": addr, "value": value})
            for message in self.engine.drain_sleep_queue():
                self.sink.message(message)
            for addr, send_value, msg in self.engine.diff(snapshot):
                self.pipe.send_data({"addr": addr, "value": send_value})
                if msg:
                    self.sink.message(msg)
        elif self.engine.did_cache:
            self.sink.log("Game stopped running; pausing sync")
            self.engine.did_cache = False

    def on_data(self, body: dict) -> None:
        if body.get("op") == "hello":
            if body.get("guid") != self.mode.GUID:
                self.sink.message(f"Partner has incompatible mode: {body.get('guid')}")
                return
            self.sink.log(
                f"Partner app hello OK (guid={body['guid']}, version={body.get('version')})"
            )
            return
        for message in self.engine.handle_table(body):
            self.sink.message(message)

    def _on_partner_reconnected(self) -> None:
        self.sink.message("Partner reconnected - re-syncing state")
        self.app_hello_sent = False
        self.engine.resync()


def run_sync_session(
    *,
    endpoint: MemoryEndpoint,
    pipe: Any,
    mode: Any,
    sink: StatusSink,
    poll_hz: int = 10,
) -> int:
    session = SyncSession(endpoint=endpoint, pipe=pipe, mode=mode, sink=sink)
    pipe.send_join()
    poll_period = 1.0 / poll_hz
    try:
        while pipe.state != "CLOSED":
            loop_start = time.monotonic()
            session.tick_once()
            if pipe.state in ("FAILED", "CLOSED"):
                break
            sleep = poll_period - (time.monotonic() - loop_start)
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        sink.log("Interrupted by user")
    finally:
        pipe.close()
        endpoint.close()
    return 0 if pipe.state != "FAILED" else 1
