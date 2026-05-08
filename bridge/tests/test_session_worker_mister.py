import queue

import pytest

import bridge_gui.session_worker as session_worker
from bridge_core.mister_helper import MisterHelperMemoryEndpoint
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine
from bridge_gui.session_worker import SessionWorker


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


def test_mister_session_applies_incoming_writes_through_helper_endpoint():
    requests = []

    def request(payload):
        requests.append(payload)
        if payload["op"] == "read_byte":
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
        {"op": "read_byte", "addr": 0x0657},
        {"op": "write_pairs", "pairs": [[0x0657, 1]]},
    ]
