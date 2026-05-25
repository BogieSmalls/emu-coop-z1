"""Structured MiSTer setup diagnostics."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shlex

from bridge_core.mister_deploy import MisterDeployService, MisterSshConfig
from bridge_core.mister_health import MisterHelperHealth, probe_mister_helper
from bridge_core.sync_probe import endpoint_error


REQUIRED_TOOLS = ("python3", "nohup", "nc")


@dataclass(frozen=True)
class MisterDiagnosticReport:
    host: str
    ssh_ok: bool
    ssh_error: str | None
    tool_status: dict[str, bool] | None
    helper_file: str
    core_file: str
    helper_port: str
    helper_start: str
    helper_log_tail: str | None
    helper_health: MisterHelperHealth | None

    def render_text(self) -> str:
        lines = [
            f"MiSTer host: {self.host}",
            f"SSH: {'ok' if self.ssh_ok else f'failed ({self.ssh_error or "unknown error"})'}",
            f"Required tools: {_format_tools(self.tool_status)}",
            f"Helper file: {self.helper_file}",
            f"Core file: {self.core_file}",
            f"Helper start: {self.helper_start}",
            f"Helper port: {self.helper_port}",
        ]
        health = self.helper_health
        if health is None:
            lines.extend(
                [
                    "PC -> helper: not checked",
                    "Mirror read: not checked",
                    "Frame: -",
                    "0x0012: -",
                    "Running: unknown",
                ]
            )
        else:
            lines.append(f"PC -> helper: {'ok' if health.helper_reachable else 'failed'}")
            if health.mirror_ok:
                lines.append("Mirror read: ok")
            else:
                lines.append(f"Mirror read: {health.error or 'failed'}")
            lines.append(f"Frame: {health.frame}")
            if health.value is None:
                lines.append(f"0x{health.addr:04X}: -")
            else:
                lines.append(f"0x{health.addr:04X}: 0x{health.value & 0xFF:02X}")
            lines.append(f"Running: {_format_running(health.running)}")
        if self.helper_log_tail:
            lines.append("Helper log tail:")
            lines.extend(self.helper_log_tail.rstrip().splitlines())
        return "\n".join(lines)


def run_mister_diagnostics(
    *,
    host: str,
    username: str,
    password: str,
    helper_local_path: Path,
    helper_remote_path: str,
    helper_log_path: str | None = None,
    core_local_path: Path,
    core_remote_path: str,
    port: int = 55355,
    mode: Any | None = None,
    start_helper_if_needed: bool = False,
    service_factory: Callable[[MisterSshConfig], Any] = MisterDeployService,
    health_probe: Callable[..., MisterHelperHealth] = probe_mister_helper,
) -> MisterDiagnosticReport:
    config = MisterSshConfig(host=host, username=username.strip() or "root", password=password or "1")
    service = service_factory(config)
    try:
        try:
            service.connect()
        except Exception as exc:
            return MisterDiagnosticReport(
                host=host,
                ssh_ok=False,
                ssh_error=endpoint_error(exc),
                tool_status=None,
                helper_file="not checked",
                core_file="not checked",
                helper_start="not checked",
                helper_port="not checked",
                helper_log_tail=None,
                helper_health=None,
            )

        missing = set(service.missing_required_tools())
        tool_status = {tool: tool not in missing for tool in REQUIRED_TOOLS}
        helper_file = _remote_asset_status(service, helper_local_path, helper_remote_path)
        core_file = _remote_asset_status(service, core_local_path, core_remote_path)
        helper_port = _helper_port_status(service, port)
        helper_start = "not needed" if helper_port == "listening" else "not attempted"
        helper_log_tail = None
        if start_helper_if_needed and helper_port != "listening" and helper_file != "missing":
            try:
                service.restart_helper(helper_remote_path, port=port)
                helper_start = "started"
            except Exception as exc:
                helper_start = f"failed ({endpoint_error(exc)})"
            helper_port = _helper_port_status(service, port)
            if helper_port != "listening" and helper_log_path:
                helper_log_tail = _helper_log_tail(service, helper_log_path)
        health = health_probe(host=host, port=port, timeout=2.0, mode=mode)
        if not helper_log_tail and helper_log_path and health is not None and not health.helper_reachable:
            helper_log_tail = _helper_log_tail(service, helper_log_path)
        return MisterDiagnosticReport(
            host=host,
            ssh_ok=True,
            ssh_error=None,
            tool_status=tool_status,
            helper_file=helper_file,
            core_file=core_file,
            helper_start=helper_start,
            helper_port=helper_port,
            helper_log_tail=helper_log_tail,
            helper_health=health,
        )
    finally:
        close = getattr(service, "close", None)
        if close is not None:
            close()


def _remote_asset_status(service: Any, local_path: Path, remote_path: str) -> str:
    if not Path(local_path).is_file():
        return "local missing"
    if not service.remote_exists(remote_path):
        return "missing"
    local_hash = service.local_sha256(Path(local_path))
    remote_hash = service.remote_sha256(remote_path)
    if remote_hash == local_hash:
        return "current"
    return "outdated"


def _helper_port_status(service: Any, port: int) -> str:
    rc, _out, _err = service.run(f"nc -z 127.0.0.1 {int(port)}")
    return "listening" if rc == 0 else "not listening"


def _helper_log_tail(service: Any, log_path: str) -> str | None:
    rc, out, err = service.run(
        f"if test -f {shlex.quote(log_path)}; then tail -n 40 {shlex.quote(log_path)}; fi"
    )
    if rc != 0:
        return (err or out).strip() or None
    return out.strip() or None


def _format_tools(tool_status: dict[str, bool] | None) -> str:
    if tool_status is None:
        return "not checked"
    return ", ".join(
        f"{tool} {'ok' if tool_status.get(tool) else 'missing'}" for tool in REQUIRED_TOOLS
    )


def _format_running(running: bool | None) -> str:
    if running is True:
        return "yes"
    if running is False:
        return "no"
    return "unknown"
