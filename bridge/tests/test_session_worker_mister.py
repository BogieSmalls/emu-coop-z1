import queue

import pytest

import bridge_gui.session_worker as session_worker
from bridge_core.mister_helper import MisterHelperMemoryEndpoint
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine
from bridge_gui.session_worker import SessionWorker, edn8_overload_options


def test_session_worker_uses_edn8_endpoint_for_edn8_config(monkeypatch):
    calls = {}

    class FakeSerial:
        def __init__(self, port, baudrate, timeout):
            calls["serial"] = {
                "port": port,
                "baudrate": baudrate,
                "timeout": timeout,
            }

        def close(self):
            calls["serial_closed"] = True

    class FakeCCClient:
        def __init__(self, serial_port):
            self.serial_port = serial_port

    class FakeCCEndpoint:
        def __init__(self, client):
            self.client = client

    monkeypatch.setattr(session_worker.serial, "Serial", FakeSerial)
    monkeypatch.setattr(session_worker, "CCClient", FakeCCClient)
    monkeypatch.setattr(session_worker, "CCMemoryEndpoint", FakeCCEndpoint)

    worker = SessionWorker({}, queue.Queue())
    endpoint = worker._open_endpoint(
        {
            "endpoint_type": "edn8",
            "com_port": "COM5",
        }
    )

    assert isinstance(endpoint, FakeCCEndpoint)
    assert calls["serial"] == {"port": "COM5", "baudrate": 115200, "timeout": 0}
    assert endpoint.client.serial_port.__class__ is FakeSerial


def test_session_worker_uses_mister_endpoint_for_mister_config(monkeypatch):
    created = {}

    def fail_serial(*_args, **_kwargs):
        raise AssertionError("serial should not be opened for MiSTer")

    class FakeMisterEndpoint:
        def __init__(self, host, port, timeout):
            created["endpoint"] = {
                "host": host,
                "port": port,
                "timeout": timeout,
            }

    monkeypatch.setattr(session_worker.serial, "Serial", fail_serial)
    monkeypatch.setattr(session_worker, "MisterHelperMemoryEndpoint", FakeMisterEndpoint, raising=False)

    worker = SessionWorker({}, queue.Queue())
    endpoint = worker._open_endpoint(
        {
            "endpoint_type": "mister",
            "mister_host": "192.168.0.130",
            "mister_port": 55355,
            "mister_timeout": 1.25,
        }
    )

    assert isinstance(endpoint, FakeMisterEndpoint)
    assert created["endpoint"] == {
        "host": "192.168.0.130",
        "port": 55355,
        "timeout": 1.25,
    }


def test_session_worker_rejects_unknown_endpoint_type():
    worker = SessionWorker({}, queue.Queue())

    with pytest.raises(ValueError, match="unknown endpoint"):
        worker._open_endpoint({"endpoint_type": "unknown"})


def test_edn8_tloz_all_enables_overload_protection():
    options = edn8_overload_options({"endpoint_type": "edn8", "mode": "tloz_all"})

    assert options == {
        "resync_send_limit": 2,
        "defer_full_poll_while_map_pending": True,
    }


def test_non_edn8_or_non_tloz_all_keeps_default_sync_behavior():
    assert edn8_overload_options({"endpoint_type": "mister", "mode": "tloz_all"}) == {}
    assert edn8_overload_options({"endpoint_type": "edn8", "mode": "tloz_progress"}) == {}


def test_mister_session_applies_incoming_writes_through_helper_endpoint():
    requests = []

    def request(payload):
        requests.append(payload)
        if payload["op"] == "read_byte":
            if payload["addr"] == tloz_all.RUNNING_ADDR:
                return {"ok": True, "frame": 1, "value": 0x05}
            return {"ok": True, "frame": 1, "value": 0}
        if payload["op"] == "write_pairs":
            return {"ok": True}
        raise AssertionError(payload)

    endpoint = MisterHelperMemoryEndpoint(request=request)
    engine = SyncEngine(endpoint=endpoint, mode=tloz_all)
    engine.cache[0x0657] = 0

    messages = engine.handle_table({"addr": 0x0657, "value": 1})

    assert any("Wood Sword" in message for message in messages)
    assert requests == [
        {"op": "read_byte", "addr": 0x0012},
        {"op": "read_byte", "addr": 0x0657},
        {"op": "write_pairs", "pairs": [[0x0657, 1]]},
    ]


def test_session_worker_does_not_fail_when_endpoint_poll_times_out(monkeypatch):
    events = queue.Queue()
    fake_pipe = None

    class FakeSocket:
        def connect(self, address):
            self.address = address

        def setblocking(self, blocking):
            self.blocking = blocking

        def close(self):
            pass

    class FakeEndpoint:
        def read_ranges(self, ranges, timeout_ms=300):
            fake_pipe.state = "CLOSED"
            raise TimeoutError("timed out")

        def close(self):
            pass

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            nonlocal fake_pipe
            fake_pipe = self
            self.state = "ESTABLISHED"
            self.sent = []
            self.on_data = None
            self.on_abort = None
            self.on_partner_reconnected = None
            self._reconnect_enabled = False

        def send_join(self):
            pass

        def tick(self):
            pass

        def heartbeat_tick(self):
            pass

        def send_data(self, body):
            self.sent.append(body)

        def close(self):
            self.state = "CLOSED"

    monkeypatch.setattr(session_worker.socket, "socket", lambda *args, **kwargs: FakeSocket())
    monkeypatch.setattr(session_worker, "MisterHelperMemoryEndpoint", lambda **kwargs: FakeEndpoint())
    monkeypatch.setattr(session_worker, "PipeClient", FakePipe)

    worker = SessionWorker(
        {
            "endpoint_type": "mister",
            "mister_host": "192.168.0.130",
            "mister_port": 55355,
            "mode": "tloz_all",
            "relay": "coop.z1rracing.com",
            "relay_port": 9999,
            "code": "abcdef",
        },
        events,
    )

    worker._run()

    collected = []
    while not events.empty():
        collected.append(events.get())

    assert not any(
        event.kind == "state" and event.data["state"] == "FAILED"
        for event in collected
    )
    assert any(
        event.kind == "log"
        and event.data.get("level") == "ERROR"
        and event.data["text"] == "Endpoint read failed: timed out"
        for event in collected
    )


def test_session_worker_skips_full_poll_when_running_probe_is_not_running(monkeypatch):
    events = queue.Queue()
    read_ranges_calls = []
    fake_pipe = None

    class FakeSocket:
        def connect(self, address):
            self.address = address

        def setblocking(self, blocking):
            self.blocking = blocking

        def close(self):
            pass

    class FakeEndpoint:
        def read_ranges(self, ranges, timeout_ms=300):
            read_ranges_calls.append(ranges)
            fake_pipe.state = "CLOSED"
            return {0x0012: 0x00}

        def close(self):
            pass

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            nonlocal fake_pipe
            fake_pipe = self
            self.state = "ESTABLISHED"
            self.sent = []
            self.on_data = None
            self.on_abort = None
            self.on_partner_reconnected = None
            self._reconnect_enabled = False

        def send_join(self):
            pass

        def tick(self):
            pass

        def heartbeat_tick(self):
            pass

        def send_data(self, body):
            self.sent.append(body)

        def close(self):
            self.state = "CLOSED"

    monkeypatch.setattr(session_worker.socket, "socket", lambda *args, **kwargs: FakeSocket())
    monkeypatch.setattr(session_worker, "MisterHelperMemoryEndpoint", lambda **kwargs: FakeEndpoint())
    monkeypatch.setattr(session_worker, "PipeClient", FakePipe)

    worker = SessionWorker(
        {
            "endpoint_type": "mister",
            "mister_host": "192.168.0.130",
            "mister_port": 55355,
            "mode": "tloz_all",
            "relay": "coop.z1rracing.com",
            "relay_port": 9999,
            "code": "abcdef",
        },
        events,
    )

    worker._run()

    assert read_ranges_calls == [[(tloz_all.RUNNING_ADDR, 1)]]


def test_session_worker_emits_edn8_diagnostics(monkeypatch):
    events = queue.Queue()
    fake_pipe = None

    class FakeSocket:
        def connect(self, address):
            self.address = address

        def setblocking(self, blocking):
            self.blocking = blocking

        def close(self):
            pass

    class FakeEndpoint:
        def __init__(self, client):
            pass

        def read_ranges(self, ranges, timeout_ms=300):
            fake_pipe.state = "CLOSED"
            return {0x0012: 0x05}

        def close(self):
            pass

    class FakeSerial:
        def __init__(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

    class FakeCCClient:
        def __init__(self, serial_port):
            self.serial_port = serial_port

    class FakePipe:
        def __init__(self, socket, code, peer_id):
            nonlocal fake_pipe
            fake_pipe = self
            self.state = "ESTABLISHED"
            self.sent = []
            self.on_data = None
            self.on_abort = None
            self.on_partner_reconnected = None
            self._reconnect_enabled = False
            self._reconnect_attempt = 0

        def send_join(self):
            pass

        def tick(self):
            pass

        def heartbeat_tick(self):
            pass

        def send_data(self, body):
            self.sent.append(body)

        def close(self):
            self.state = "CLOSED"

    monkeypatch.setattr(session_worker.socket, "socket", lambda *args, **kwargs: FakeSocket())
    monkeypatch.setattr(session_worker.serial, "Serial", FakeSerial)
    monkeypatch.setattr(session_worker, "CCClient", FakeCCClient)
    monkeypatch.setattr(session_worker, "CCMemoryEndpoint", FakeEndpoint)
    monkeypatch.setattr(session_worker, "PipeClient", FakePipe)

    worker = SessionWorker(
        {
            "endpoint_type": "edn8",
            "com_port": "COM7",
            "mode": "tloz_progress",
            "relay": "coop.z1rracing.com",
            "relay_port": 9999,
            "code": "abcdef",
        },
        events,
    )

    worker._run()

    diagnostics = [
        event.data["text"]
        for event in list(events.queue)
        if event.kind == "diagnostics"
    ]

    assert diagnostics
    assert "Endpoint: EDN8" in diagnostics[-1]
    assert "Mode: tloz_progress" in diagnostics[-1]
    assert "COM port: COM7" in diagnostics[-1]
