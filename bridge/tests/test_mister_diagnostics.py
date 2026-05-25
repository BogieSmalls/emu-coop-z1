from pathlib import Path

from bridge_core.mister_diagnostics import run_mister_diagnostics
from bridge_core.mister_health import MisterHelperHealth
from bridge_core.modes import tloz_progress


class FakeService:
    def __init__(
        self,
        *,
        missing_tools=None,
        remote_hashes=None,
        port_ok=True,
        connect_error=None,
        restart_error=None,
        log_tail="",
    ):
        self.missing_tools = missing_tools or []
        self.remote_hashes = remote_hashes or {}
        self.port_ok = port_ok
        self.connect_error = connect_error
        self.restart_error = restart_error
        self.log_tail = log_tail
        self.closed = False
        self.commands = []
        self.restart_calls = []

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error

    def missing_required_tools(self):
        return self.missing_tools

    def remote_exists(self, remote_path):
        return remote_path in self.remote_hashes

    def remote_sha256(self, remote_path):
        return self.remote_hashes.get(remote_path)

    def local_sha256(self, local_path):
        return Path(local_path).read_text(encoding="utf-8")

    def run(self, command, timeout_s=10.0):
        self.commands.append((command, timeout_s))
        if "nc -z 127.0.0.1" in command:
            return (0 if self.port_ok else 1, "", "")
        if "tail -n" in command:
            return (0, self.log_tail, "")
        raise AssertionError(command)

    def restart_helper(self, remote_helper_path, port=55355):
        self.restart_calls.append((remote_helper_path, port))
        if self.restart_error is not None:
            raise self.restart_error
        self.port_ok = True

    def close(self):
        self.closed = True


def test_mister_diagnostics_formats_successful_report(tmp_path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper-hash", encoding="utf-8")
    core = tmp_path / "NES_z1rr-coop.rbf"
    core.write_text("core-hash", encoding="utf-8")
    service = FakeService(
        remote_hashes={
            "/helper.py": "helper-hash",
            "/NES_z1rr-coop.rbf": "core-hash",
        },
        port_ok=True,
    )

    report = run_mister_diagnostics(
        host="192.168.0.130",
        username="root",
        password="1",
        helper_local_path=helper,
        helper_remote_path="/helper.py",
        core_local_path=core,
        core_remote_path="/NES_z1rr-coop.rbf",
        mode=tloz_progress,
        service_factory=lambda _config: service,
        health_probe=lambda **_kwargs: MisterHelperHealth(
            helper_reachable=True,
            mirror_ok=True,
            addr=0x0012,
            value=0x05,
            frame=42,
            running=True,
            error=None,
        ),
    )

    text = report.render_text()

    assert "MiSTer host: 192.168.0.130" in text
    assert "SSH: ok" in text
    assert "Required tools: python3 ok, nohup ok, nc ok" in text
    assert "Helper file: current" in text
    assert "Core file: current" in text
    assert "Helper port: listening" in text
    assert "PC -> helper: ok" in text
    assert "Mirror read: ok" in text
    assert "Frame: 42" in text
    assert "0x0012: 0x05" in text
    assert "Running: yes" in text
    assert service.closed is True


def test_mister_diagnostics_reports_outdated_files_and_busy_mirror(tmp_path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper-hash", encoding="utf-8")
    core = tmp_path / "NES_z1rr-coop.rbf"
    core.write_text("core-hash", encoding="utf-8")
    service = FakeService(
        missing_tools=["nc"],
        remote_hashes={
            "/helper.py": "old-helper",
        },
        port_ok=False,
    )

    report = run_mister_diagnostics(
        host="mister.local",
        username="root",
        password="1",
        helper_local_path=helper,
        helper_remote_path="/helper.py",
        core_local_path=core,
        core_remote_path="/NES_z1rr-coop.rbf",
        mode=tloz_progress,
        service_factory=lambda _config: service,
        health_probe=lambda **_kwargs: MisterHelperHealth(
            helper_reachable=True,
            mirror_ok=False,
            addr=0x0012,
            value=None,
            frame=0,
            running=None,
            error="mirror_busy_or_inactive",
        ),
    )

    text = report.render_text()

    assert "Required tools: python3 ok, nohup ok, nc missing" in text
    assert "Helper file: outdated" in text
    assert "Core file: missing" in text
    assert "Helper port: not listening" in text
    assert "PC -> helper: ok" in text
    assert "Mirror read: mirror_busy_or_inactive" in text
    assert "Frame: 0" in text
    assert "0x0012: -" in text
    assert "Running: unknown" in text


def test_mister_diagnostics_can_start_helper_when_port_is_closed(tmp_path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper-hash", encoding="utf-8")
    core = tmp_path / "NES_z1rr-coop.rbf"
    core.write_text("core-hash", encoding="utf-8")
    service = FakeService(
        remote_hashes={
            "/helper.py": "helper-hash",
            "/NES_z1rr-coop.rbf": "core-hash",
        },
        port_ok=False,
    )

    report = run_mister_diagnostics(
        host="mister.local",
        username="root",
        password="1",
        helper_local_path=helper,
        helper_remote_path="/helper.py",
        helper_log_path="/helper.log",
        core_local_path=core,
        core_remote_path="/NES_z1rr-coop.rbf",
        mode=tloz_progress,
        start_helper_if_needed=True,
        service_factory=lambda _config: service,
        health_probe=lambda **_kwargs: MisterHelperHealth(
            helper_reachable=True,
            mirror_ok=False,
            addr=0x0012,
            value=None,
            frame=0,
            running=None,
            error="mirror_busy_or_inactive",
        ),
    )

    text = report.render_text()

    assert service.restart_calls == [("/helper.py", 55355)]
    assert "Helper start: started" in text
    assert "Helper port: listening" in text
    assert "PC -> helper: ok" in text


def test_mister_diagnostics_reports_helper_start_failure_with_log_tail(tmp_path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper-hash", encoding="utf-8")
    core = tmp_path / "NES_z1rr-coop.rbf"
    core.write_text("core-hash", encoding="utf-8")
    service = FakeService(
        remote_hashes={
            "/helper.py": "helper-hash",
            "/NES_z1rr-coop.rbf": "core-hash",
        },
        port_ok=False,
        restart_error=TimeoutError("helper did not start"),
        log_tail="Traceback\nmissing MiSTer mirror\n",
    )

    report = run_mister_diagnostics(
        host="mister.local",
        username="root",
        password="1",
        helper_local_path=helper,
        helper_remote_path="/helper.py",
        helper_log_path="/helper.log",
        core_local_path=core,
        core_remote_path="/NES_z1rr-coop.rbf",
        mode=tloz_progress,
        start_helper_if_needed=True,
        service_factory=lambda _config: service,
        health_probe=lambda **_kwargs: MisterHelperHealth(
            helper_reachable=False,
            mirror_ok=False,
            addr=0x0012,
            value=None,
            frame=0,
            running=None,
            error="timed out",
        ),
    )

    text = report.render_text()

    assert "Helper start: failed (helper did not start)" in text
    assert "Helper log tail:" in text
    assert "missing MiSTer mirror" in text
    assert "Helper port: not listening" in text


def test_mister_diagnostics_reports_ssh_failure_without_followup_checks(tmp_path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper-hash", encoding="utf-8")
    core = tmp_path / "NES_z1rr-coop.rbf"
    core.write_text("core-hash", encoding="utf-8")
    service = FakeService(connect_error=TimeoutError("ssh timed out"))

    report = run_mister_diagnostics(
        host="mister.local",
        username="root",
        password="1",
        helper_local_path=helper,
        helper_remote_path="/helper.py",
        core_local_path=core,
        core_remote_path="/NES_z1rr-coop.rbf",
        mode=tloz_progress,
        service_factory=lambda _config: service,
        health_probe=lambda **_kwargs: None,
    )

    text = report.render_text()

    assert "SSH: failed (ssh timed out)" in text
    assert "Required tools: not checked" in text
    assert "Helper file: not checked" in text
    assert "PC -> helper: not checked" in text
    assert service.closed is True
