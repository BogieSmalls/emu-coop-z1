import bridge_cli.__main__ as cli

from .mister_mirror_factory import make_nes_ra_mirror


def test_mister_deploy_cli_passes_ssh_defaults(monkeypatch, capsys):
    captured = {}

    class FakeDeployService:
        def __init__(self, config, on_event=None):
            captured["config"] = config
            captured["on_event"] = on_event

        def connect(self):
            captured["connected"] = True

        def deploy(self, assets):
            captured["assets"] = assets

        def restart_helper(self, remote_helper_path, port=55355):
            captured["restart"] = (remote_helper_path, port)

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(cli, "MisterDeployService", FakeDeployService, raising=False)
    monkeypatch.setattr(cli, "_build_mister_deploy_assets", lambda manifest: ["asset"], raising=False)
    monkeypatch.setattr(
        cli,
        "_load_mister_payload_manifest",
        lambda: {
            "helper": {"remote_path": "/media/fat/Scripts/z1rr-coop/mister-helper.py", "port": 55355},
            "roms": {"remote_dir": "/media/fat/games/NES/z1rr-coop"},
        },
        raising=False,
    )

    rc = cli.main(["mister-deploy", "--host", "192.168.1.50"])

    assert rc == 0
    assert captured["config"].host == "192.168.1.50"
    assert captured["config"].username == "root"
    assert captured["config"].password == "1"
    assert captured["config"].port == 22
    assert captured["assets"] == ["asset"]
    assert captured["restart"] == ("/media/fat/Scripts/z1rr-coop/mister-helper.py", 55355)
    assert captured["closed"] is True
    assert "MiSTer deploy complete" in capsys.readouterr().out


def test_mister_deploy_cli_accepts_custom_username_password_and_rom(
    tmp_path,
    monkeypatch,
):
    rom = tmp_path / "zelda.nes"
    rom.write_bytes(b"NES\x1a" + bytes(16))
    captured = {}

    class FakeDeployService:
        def __init__(self, config, on_event=None):
            captured["config"] = config

        def connect(self):
            return None

        def deploy(self, assets):
            captured["assets"] = assets

        def stage_rom(self, local_rom_path, remote_rom_dir):
            captured["stage_rom"] = (local_rom_path, remote_rom_dir)
            return f"{remote_rom_dir}/zelda.nes"

        def restart_helper(self, remote_helper_path, port=55355):
            captured["restart"] = (remote_helper_path, port)

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(cli, "MisterDeployService", FakeDeployService, raising=False)
    monkeypatch.setattr(cli, "_build_mister_deploy_assets", lambda manifest: ["asset"], raising=False)
    monkeypatch.setattr(
        cli,
        "_load_mister_payload_manifest",
        lambda: {
            "helper": {"remote_path": "/helper.py", "port": 55355},
            "roms": {"remote_dir": "/media/fat/games/NES/z1rr-coop"},
        },
        raising=False,
    )

    rc = cli.main(
        [
            "mister-deploy",
            "--host",
            "192.168.1.50",
            "--username",
            "admin",
            "--password",
            "secret",
            "--ssh-port",
            "2222",
            "--rom",
            str(rom),
        ]
    )

    assert rc == 0
    assert captured["config"].username == "admin"
    assert captured["config"].password == "secret"
    assert captured["config"].port == 2222
    assert captured["stage_rom"] == (rom, "/media/fat/games/NES/z1rr-coop")


def test_mister_deploy_cli_reports_missing_local_core(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "_load_mister_payload_manifest",
        lambda: {"helper": {"remote_path": "/helper.py", "port": 55355}},
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "_build_mister_deploy_assets",
        lambda manifest: (_ for _ in ()).throw(FileNotFoundError("NES_z1rr-coop.rbf")),
        raising=False,
    )

    rc = cli.main(["mister-deploy", "--host", "192.168.1.50"])

    assert rc == 2
    assert "NES_z1rr-coop.rbf" in capsys.readouterr().err


def test_mister_read_cli_reads_hex_bytes_from_mirror_file(tmp_path, capsys):
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0013] = 0x06
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror(cpu_ram=cpu_ram))

    rc = cli.main(
        [
            "mister-read",
            "--mirror-file",
            str(mirror_path),
            "--addr",
            "0x0012",
            "--length",
            "2",
        ]
    )

    assert rc == 0
    assert capsys.readouterr().out.strip() == "05 06"


def test_mister_read_cli_reports_busy_mirror_file(tmp_path, capsys):
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror(busy=True))

    rc = cli.main(
        [
            "mister-read",
            "--mirror-file",
            str(mirror_path),
            "--addr",
            "0x0012",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "mirror busy or inactive" in captured.err


def test_mister_read_cli_uses_smart_cache_without_mirror_file(monkeypatch, capsys):
    captured = {}

    class FakeMailboxMemory:
        pass

    class FakeSmartCacheEndpoint:
        def __init__(self, memory):
            captured["memory"] = memory

        def read_ranges(self, ranges):
            captured["ranges"] = ranges
            return {0x0012: 0x05}

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(cli, "DevMemMailboxMemory", FakeMailboxMemory, raising=False)
    monkeypatch.setattr(cli, "MisterSmartCacheMemoryEndpoint", FakeSmartCacheEndpoint, raising=False)

    rc = cli.main(["mister-read", "--addr", "0x0012"])

    assert rc == 0
    assert captured["ranges"] == [(0x0012, 1)]
    assert captured["closed"] is True
    assert capsys.readouterr().out.strip() == "05"


def test_mister_helper_cli_starts_server_until_interrupted(tmp_path, monkeypatch, capsys):
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror(cpu_ram=cpu_ram))
    started = {}

    class FakeServer:
        def __init__(self, server_address, endpoint):
            started["address"] = server_address
            started["endpoint"] = endpoint
            self.server_address = server_address

        def serve_forever(self):
            started["served"] = True
            raise KeyboardInterrupt

        def server_close(self):
            started["closed"] = True

    monkeypatch.setattr(cli, "MisterHelperServer", FakeServer, raising=False)

    rc = cli.main(
        [
            "mister-helper",
            "--mirror-file",
            str(mirror_path),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ]
    )

    assert rc == 0
    assert started["address"] == ("127.0.0.1", 0)
    assert started["served"] is True
    assert started["closed"] is True
    assert started["endpoint"].read_byte(0x0012) == 0x05
    assert "MiSTer helper listening" in capsys.readouterr().out


def test_mister_helper_cli_uses_smart_cache_without_mirror_file(monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, server_address, endpoint):
            captured["endpoint"] = endpoint
            self.server_address = server_address

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            return None

    class FakeMailboxMemory:
        pass

    class FakeSmartCacheEndpoint:
        def __init__(self, memory):
            captured["memory"] = memory

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(cli, "MisterHelperServer", FakeServer, raising=False)
    monkeypatch.setattr(cli, "DevMemMailboxMemory", FakeMailboxMemory, raising=False)
    monkeypatch.setattr(cli, "MisterSmartCacheMemoryEndpoint", FakeSmartCacheEndpoint, raising=False)

    rc = cli.main(["mister-helper"])

    assert rc == 0
    assert isinstance(captured["memory"], FakeMailboxMemory)
    assert captured["endpoint"] is not None
    assert captured["closed"] is True


def test_mister_helper_cli_can_enable_write_mailbox(tmp_path, monkeypatch):
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror())
    mailbox_path = tmp_path / "mailbox.bin"
    mailbox_path.write_bytes(bytes(0x60000))
    captured = {}

    class FakeServer:
        def __init__(self, server_address, endpoint):
            captured["endpoint"] = endpoint
            self.server_address = server_address

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            return None

    class FakeMailboxMemory:
        def __init__(self, path):
            captured["mailbox_path"] = path

    class FakeWriteMailbox:
        def __init__(self, memory, ack_timeout_ms=100):
            captured["mailbox_memory"] = memory
            captured["ack_timeout_ms"] = ack_timeout_ms

    class FakeMailboxEndpoint:
        def __init__(self, reader, mailbox):
            captured["endpoint_reader"] = reader
            captured["endpoint_mailbox"] = mailbox

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(cli, "MisterHelperServer", FakeServer, raising=False)
    monkeypatch.setattr(cli, "FileMailboxMemory", FakeMailboxMemory, raising=False)
    monkeypatch.setattr(cli, "MisterWriteMailbox", FakeWriteMailbox, raising=False)
    monkeypatch.setattr(cli, "MisterMailboxMemoryEndpoint", FakeMailboxEndpoint, raising=False)

    rc = cli.main(
        [
            "mister-helper",
            "--mirror-file",
            str(mirror_path),
            "--enable-writes",
            "--mailbox-file",
            str(mailbox_path),
            "--write-timeout-ms",
            "250",
        ]
    )

    assert rc == 0
    assert captured["mailbox_path"] == str(mailbox_path)
    assert captured["ack_timeout_ms"] == 250
    assert captured["endpoint_reader"].read_byte(0x0012) == 0x00
    assert captured["endpoint_mailbox"] is not None
    assert captured["closed"] is True


def test_mister_run_cli_wires_helper_endpoint_and_relay(monkeypatch):
    captured = {}

    class FakeSocket:
        def connect(self, address):
            captured["relay_address"] = address

        def setblocking(self, blocking):
            captured["relay_blocking"] = blocking

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            captured["pipe_socket"] = socket
            captured["pipe_code"] = code
            captured["pipe_peer_id"] = peer_id

    class FakeEndpoint:
        def __init__(self, host, port, timeout=1.0):
            captured["helper"] = (host, port, timeout)

    def fake_socket_factory(*args):
        captured["socket_args"] = args
        return FakeSocket()

    def fake_run_readonly_session(*, endpoint, pipe, mode, sink, poll_hz):
        captured["runner"] = {
            "endpoint": endpoint,
            "pipe": pipe,
            "mode_guid": mode.GUID,
            "mode_name": mode.__name__,
            "poll_hz": poll_hz,
        }
        return 0

    monkeypatch.setattr(cli.socket, "socket", fake_socket_factory)
    monkeypatch.setattr(cli, "PipeClient", FakePipe)
    monkeypatch.setattr(cli, "MisterHelperMemoryEndpoint", FakeEndpoint, raising=False)
    monkeypatch.setattr(cli, "run_readonly_session", fake_run_readonly_session, raising=False)

    rc = cli.main(
        [
            "mister-run",
            "--mode",
            "tloz_all",
            "--mister-host",
            "mister.local",
            "--mister-port",
            "55355",
            "--code",
            "abc123",
            "--relay",
            "relay.local",
            "--relay-port",
            "9999",
        ]
    )

    assert rc == 0
    assert captured["helper"] == ("mister.local", 55355, 1.0)
    assert captured["relay_address"] == ("relay.local", 9999)
    assert captured["relay_blocking"] is False
    assert captured["pipe_code"] == "abc123"
    assert captured["runner"]["mode_name"].endswith(".tloz_all")
    assert captured["runner"]["poll_hz"] == 10


def test_mister_run_cli_can_use_write_capable_session(monkeypatch):
    captured = {}

    class FakeSocket:
        def connect(self, address):
            captured["relay_address"] = address

        def setblocking(self, blocking):
            captured["relay_blocking"] = blocking

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            captured["pipe_code"] = code

    class FakeEndpoint:
        def __init__(self, host, port, timeout=1.0):
            captured["helper"] = (host, port, timeout)

    def fake_socket_factory(*args):
        return FakeSocket()

    def fake_run_readonly_session(**kwargs):
        captured["readonly_runner"] = kwargs
        return 0

    def fake_run_sync_session(**kwargs):
        captured["sync_runner"] = kwargs
        return 0

    monkeypatch.setattr(cli.socket, "socket", fake_socket_factory)
    monkeypatch.setattr(cli, "PipeClient", FakePipe)
    monkeypatch.setattr(cli, "MisterHelperMemoryEndpoint", FakeEndpoint, raising=False)
    monkeypatch.setattr(cli, "run_readonly_session", fake_run_readonly_session, raising=False)
    monkeypatch.setattr(cli, "run_sync_session", fake_run_sync_session, raising=False)

    rc = cli.main(
        [
            "mister-run",
            "--mode",
            "tloz_all",
            "--mister-host",
            "mister.local",
            "--code",
            "abc123",
            "--enable-writes",
        ]
    )

    assert rc == 0
    assert "readonly_runner" not in captured
    assert captured["sync_runner"]["poll_hz"] == 10
    assert captured["helper"] == ("mister.local", 55355, 1.0)
    assert captured["relay_address"] == ("coop.z1rracing.com", 9999)


def test_edn8_run_cli_defaults_to_public_relay_hostname(monkeypatch):
    captured = {}

    class FakeSerial:
        def __init__(self, port, baudrate, timeout):
            captured["serial"] = (port, baudrate, timeout)

        def close(self):
            captured["serial_closed"] = True

    class FakeSocket:
        def connect(self, address):
            captured["relay_address"] = address

        def setblocking(self, blocking):
            captured["relay_blocking"] = blocking

        def close(self):
            captured["socket_closed"] = True

    class FakeCCClient:
        def __init__(self, serial_port):
            captured["cc_serial"] = serial_port

    class FakeEndpoint:
        def __init__(self, client):
            captured["endpoint_client"] = client

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            captured["pipe_code"] = code
            self.state = "CLOSED"
            self.on_data = None
            self.on_abort = None
            self.on_partner_reconnected = None
            self._reconnect_enabled = False

        def send_join(self):
            captured["join_sent"] = True

        def close(self):
            captured["pipe_closed"] = True

    monkeypatch.setattr(cli.serial, "Serial", FakeSerial)
    monkeypatch.setattr(cli.socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(cli, "CCClient", FakeCCClient)
    monkeypatch.setattr(cli, "CCMemoryEndpoint", FakeEndpoint)
    monkeypatch.setattr(cli, "PipeClient", FakePipe)

    rc = cli.main(
        [
            "run",
            "--mode",
            "tloz_all",
            "--port",
            "COM5",
            "--code",
            "abc123",
        ]
    )

    assert rc == 0
    assert captured["relay_address"] == ("coop.z1rracing.com", 9999)
    assert captured["relay_blocking"] is False
    assert captured["pipe_code"] == "abc123"
