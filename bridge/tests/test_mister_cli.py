import bridge_cli.__main__ as cli

from .mister_mirror_factory import make_nes_ra_mirror


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
