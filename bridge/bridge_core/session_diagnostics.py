"""Live session diagnostics rendered for the hardware bridge UI."""
from __future__ import annotations

from dataclasses import dataclass


def _endpoint_label(endpoint_type: str) -> str:
    if endpoint_type.lower() == "edn8":
        return "EDN8"
    return endpoint_type or "unknown"


@dataclass
class SessionDiagnostics:
    endpoint_type: str
    mode_name: str
    com_port: str = ""
    peer_id: str = ""
    relay_state: str = "CONNECTING"
    reconnect_attempt: int = 0
    running_probe_running: int = 0
    running_probe_not_running: int = 0
    running_probe_failed: int = 0
    full_poll_ok: int = 0
    full_poll_failed: int = 0
    endpoint_failure_streak: int = 0
    incoming_updates: int = 0
    outgoing_updates: int = 0
    incoming_read_errors: int = 0
    incoming_write_errors: int = 0
    map_backlog: int = 0
    resync_backlog: int = 0
    deferred_full_polls: int = 0
    partner_reconnects: int = 0
    last_endpoint_error: str = "-"
    last_partner_update: str = "-"
    last_incoming_result: str = "-"
    last_outgoing_update: str = "-"
    last_running_state: str = "unknown"
    last_running_byte: str = "-"
    last_endpoint_frame: str = "-"
    last_ram_sample: str = "-"

    def set_relay_state(self, state: str, reconnect_attempt: int = 0) -> None:
        self.relay_state = state
        self.reconnect_attempt = reconnect_attempt

    def set_backlogs(self, *, map_backlog: int, resync_backlog: int) -> None:
        self.map_backlog = map_backlog
        self.resync_backlog = resync_backlog

    def record_running_probe(
        self,
        *,
        success: bool,
        running: bool | None = None,
        addr: int | None = None,
        value: int | None = None,
        frame: int | None = None,
        error: str | None = None,
    ) -> None:
        if addr is not None:
            if value is None:
                self.last_running_byte = f"0x{addr:04X}=-"
            else:
                self.last_running_byte = f"0x{addr:04X}=0x{value & 0xFF:02X}"
        if frame is not None:
            self.last_endpoint_frame = str(int(frame))
        if success:
            if running is False:
                self.running_probe_not_running += 1
                self.last_running_state = "not running"
            else:
                self.running_probe_running += 1
                self.last_running_state = "running" if running is True else "unknown"
            self.endpoint_failure_streak = 0
            self.last_endpoint_error = "-"
        else:
            self.running_probe_failed += 1
            self._record_endpoint_failure(error)

    def record_full_poll(self, *, success: bool, error: str | None = None) -> None:
        if success:
            self.full_poll_ok += 1
            self.endpoint_failure_streak = 0
            self.last_endpoint_error = "-"
        else:
            self.full_poll_failed += 1
            self._record_endpoint_failure(error)

    def record_incoming_update(self, addr: int, value: int) -> None:
        self.incoming_updates += 1
        self.last_partner_update = f"0x{addr:04X}=0x{value & 0xFF:02X}"

    def record_incoming_result(
        self,
        addr: int,
        value: int,
        *,
        applied: bool,
        previous_value: int | None = None,
        written_value: int | None = None,
        status: str | None = None,
        messages: list[str] | None = None,
    ) -> None:
        if previous_value is not None and written_value is not None:
            prefix = (
                f"0x{addr:04X} "
                f"0x{previous_value & 0xFF:02X} -> 0x{written_value & 0xFF:02X}"
            )
        else:
            prefix = f"0x{addr:04X}=0x{value & 0xFF:02X}"
        state = "applied" if applied else (status or "ignored")
        suffix = ""
        if messages:
            suffix = "; " + "; ".join(messages)
        self.last_incoming_result = f"{prefix} {state}{suffix}"

    def record_endpoint_sample(self, snapshot: dict[int, int]) -> None:
        if not snapshot:
            self.last_ram_sample = "-"
            return
        self.last_ram_sample = ", ".join(
            f"0x{int(addr):04X}=0x{int(snapshot[addr]) & 0xFF:02X}"
            for addr in sorted(snapshot)
        )

    def record_outgoing_update(self, addr: int, value: int) -> None:
        self.outgoing_updates += 1
        self.last_outgoing_update = f"0x{addr:04X}=0x{value & 0xFF:02X}"

    def record_incoming_read_error(self, message: str) -> None:
        self.incoming_read_errors += 1
        self.last_endpoint_error = message

    def record_incoming_write_error(self, message: str) -> None:
        self.incoming_write_errors += 1
        self.last_endpoint_error = message

    def record_deferred_full_poll(self, *, map_backlog: int, resync_backlog: int) -> None:
        self.deferred_full_polls += 1
        self.set_backlogs(map_backlog=map_backlog, resync_backlog=resync_backlog)

    def record_partner_reconnect(self) -> None:
        self.partner_reconnects += 1

    def render_text(self) -> str:
        lines = [
            f"Endpoint: {_endpoint_label(self.endpoint_type)}",
            f"Mode: {self.mode_name}",
            f"COM port: {self.com_port or '-'}",
            f"Peer ID: {(self.peer_id[:6] if self.peer_id else '-')}",
            "",
            f"Relay state: {self.relay_state}",
            f"Reconnect attempt: {self.reconnect_attempt}",
            f"Partner reconnects: {self.partner_reconnects}",
            "",
            (
                "Running probes: "
                f"{self.running_probe_running} running / "
                f"{self.running_probe_not_running} not running / "
                f"{self.running_probe_failed} failed"
            ),
            f"Running state: {self.last_running_state}",
            f"Last running byte: {self.last_running_byte}",
            f"Last endpoint frame: {self.last_endpoint_frame}",
            f"Last RAM sample: {self.last_ram_sample}",
            f"Full polls: {self.full_poll_ok} ok / {self.full_poll_failed} failed",
            f"Endpoint failure streak: {self.endpoint_failure_streak}",
            "",
            f"Incoming updates: {self.incoming_updates}",
            f"Outgoing updates: {self.outgoing_updates}",
            f"Incoming read errors: {self.incoming_read_errors}",
            f"Incoming write errors: {self.incoming_write_errors}",
            "",
            f"Map backlog: {self.map_backlog}",
            f"Resync backlog: {self.resync_backlog}",
            f"Deferred full polls: {self.deferred_full_polls}",
            "",
            f"Last endpoint error: {self.last_endpoint_error}",
            f"Last partner update: {self.last_partner_update}",
            f"Last incoming result: {self.last_incoming_result}",
            f"Last outgoing update: {self.last_outgoing_update}",
        ]
        return "\n".join(lines)

    def _record_endpoint_failure(self, error: str | None) -> None:
        self.endpoint_failure_streak += 1
        if error:
            self.last_endpoint_error = error
