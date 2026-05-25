from pathlib import Path

import pytest

from bridge_core.mister_deploy import DeployAsset, MisterDeployService, MisterSshConfig


class FakeAutoAddPolicy:
    pass


class FakeStream:
    def __init__(self, data: str = "", exit_status: int = 0) -> None:
        self._data = data
        self.channel = self
        self._exit_status = exit_status

    def read(self) -> bytes:
        return self._data.encode("utf-8")

    def recv_exit_status(self) -> int:
        return self._exit_status


class FakeSftp:
    def __init__(self) -> None:
        self.puts = []
        self.closed = False

    def put(self, local_path, remote_path):
        self.puts.append((str(local_path), remote_path))

    def close(self):
        self.closed = True


class FakeSshClient:
    def __init__(self) -> None:
        self.policy = None
        self.connect_calls = []
        self.commands = []
        self.sftp = FakeSftp()
        self.sftp_error: Exception | None = None
        self.responses: list[tuple[int, str, str]] = []
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connect_calls.append(kwargs)

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        rc, stdout, stderr = self.responses.pop(0) if self.responses else (0, "", "")
        return (None, FakeStream(stdout, rc), FakeStream(stderr, rc))

    def open_sftp(self):
        if self.sftp_error:
            raise self.sftp_error
        return self.sftp

    def close(self):
        self.closed = True


class FakeParamiko:
    AutoAddPolicy = FakeAutoAddPolicy

    def __init__(self, client: FakeSshClient) -> None:
        self.client = client

    def SSHClient(self):
        return self.client


def make_service(client: FakeSshClient) -> MisterDeployService:
    return MisterDeployService(
        MisterSshConfig(host="192.168.0.130"),
        paramiko_module=FakeParamiko(client),
        sleep=lambda _seconds: None,
    )


def test_connect_uses_password_defaults_and_auto_add_host_key_policy():
    client = FakeSshClient()
    service = make_service(client)

    service.connect()

    assert isinstance(client.policy, FakeAutoAddPolicy)
    assert client.connect_calls == [
        {
            "hostname": "192.168.0.130",
            "port": 22,
            "username": "root",
            "password": "1",
            "timeout": 8.0,
            "look_for_keys": False,
            "allow_agent": False,
        }
    ]


def test_upload_skips_remote_file_when_hash_matches(tmp_path: Path):
    local = tmp_path / "mister-helper.py"
    local.write_text("helper", encoding="utf-8")
    client = FakeSshClient()
    service = make_service(client)
    digest = service.local_sha256(local)
    client.responses = [
        (0, "exists\n", ""),
        (0, f"{digest}  /media/fat/Scripts/z1rr-coop/mister-helper.py\n", ""),
    ]

    uploaded = service.ensure_file(
        DeployAsset(local, "/media/fat/Scripts/z1rr-coop/mister-helper.py")
    )

    assert uploaded is False
    assert client.sftp.puts == []


def test_uploads_remote_file_when_missing_or_hash_differs(tmp_path: Path):
    local = tmp_path / "mister-helper.py"
    local.write_text("helper", encoding="utf-8")
    client = FakeSshClient()
    service = make_service(client)
    client.responses = [
        (1, "", "missing"),
        (0, "", ""),
        (0, "", ""),
    ]

    uploaded = service.ensure_file(
        DeployAsset(local, "/media/fat/Scripts/z1rr-coop/mister-helper.py")
    )

    assert uploaded is True
    assert any("mkdir -p /media/fat/Scripts/z1rr-coop" in cmd for cmd, _ in client.commands)
    assert client.sftp.puts == [
        (str(local), "/media/fat/Scripts/z1rr-coop/mister-helper.py")
    ]


def test_restart_helper_uses_nohup_and_existing_helper_port():
    client = FakeSshClient()
    service = make_service(client)
    client.responses = [
        (0, "", ""),
        (0, "ready\n", ""),
    ]

    service.restart_helper("/media/fat/Scripts/z1rr-coop/mister-helper.py", port=55355)

    commands = [cmd for cmd, _ in client.commands]
    assert "pkill -f 'z1rr-coop.*mister-helper.py' || true" in commands[0]
    assert "nohup python3 /media/fat/Scripts/z1rr-coop/mister-helper.py" in commands[0]
    assert "--port 55355" in commands[0]
    assert "nc -z 127.0.0.1 55355" in commands[1]


def test_deploy_checks_required_remote_tools_before_assets(tmp_path: Path):
    helper = tmp_path / "mister-helper.py"
    helper.write_text("helper", encoding="utf-8")
    client = FakeSshClient()
    service = make_service(client)
    client.responses = [
        (0, "", ""),
        (1, "", "missing"),
        (0, "", ""),
        (0, "", ""),
    ]

    service.deploy([DeployAsset(helper, "/media/fat/Scripts/z1rr-coop/mister-helper.py")])

    assert client.commands[0][0] == (
        "for tool in python3 nohup nc; do "
        "command -v \"$tool\" >/dev/null 2>&1 || echo \"$tool\"; "
        "done"
    )


def test_deploy_reports_missing_required_remote_tools():
    client = FakeSshClient()
    service = make_service(client)
    client.responses = [(0, "nc\n", "")]

    with pytest.raises(RuntimeError, match="MiSTer missing required tools: nc"):
        service.deploy([])


def test_sftp_fallback_uploads_with_base64_cat_when_open_sftp_fails(tmp_path: Path):
    local = tmp_path / "mister-helper.py"
    local.write_text("helper", encoding="utf-8")
    client = FakeSshClient()
    client.sftp_error = OSError("no sftp")
    service = make_service(client)
    client.responses = [
        (1, "", "missing"),
        (0, "", ""),
        (0, "", ""),
    ]

    uploaded = service.ensure_file(
        DeployAsset(local, "/media/fat/Scripts/z1rr-coop/mister-helper.py")
    )

    assert uploaded is True
    commands = [cmd for cmd, _ in client.commands]
    assert any("base64 -d > /media/fat/Scripts/z1rr-coop/mister-helper.py" in cmd for cmd in commands)


def test_stage_rom_uploads_to_standard_mister_rom_folder(tmp_path: Path):
    rom = tmp_path / "zelda.nes"
    rom.write_bytes(b"NES\x1a" + bytes(16))
    client = FakeSshClient()
    service = make_service(client)
    client.responses = [
        (1, "", "missing"),
        (0, "", ""),
        (0, "", ""),
    ]

    remote_path = service.stage_rom(rom, "/media/fat/games/NES/z1rr-coop")

    assert remote_path == "/media/fat/games/NES/z1rr-coop/zelda.nes"
    assert client.sftp.puts == [(str(rom), remote_path)]
