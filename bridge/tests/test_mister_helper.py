import pytest
import threading

from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint
from bridge_core.mister_helper import (
    MisterHelperMemoryEndpoint,
    MisterHelperServer,
    handle_helper_request,
)

from .mister_mirror_factory import make_nes_ra_mirror


def test_helper_request_reads_ranges_as_pairs_with_frame():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0657] = 0x01
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(cpu_ram=cpu_ram, frame=42))

    response = handle_helper_request(
        {"op": "read_ranges", "ranges": [[0x0012, 1], [0x0657, 1]]},
        endpoint,
    )

    assert response == {
        "ok": True,
        "frame": 42,
        "values": [[0x0012, 0x05], [0x0657, 0x01]],
    }


def test_helper_request_reports_busy_snapshot():
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(busy=True, frame=9))

    response = handle_helper_request({"op": "read_ranges", "ranges": [[0x0012, 1]]}, endpoint)

    assert response == {"ok": False, "error": "mirror_busy_or_inactive", "frame": 9}


def test_helper_request_rejects_writes_until_write_channel_exists():
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror())

    response = handle_helper_request({"op": "write_pairs", "pairs": [[0x0657, 1]]}, endpoint)

    assert response == {"ok": False, "error": "writes_not_supported"}


def test_helper_request_returns_ok_for_write_capable_endpoint():
    class WriteEndpoint:
        def __init__(self):
            self.pairs = []

        def read_ranges(self, ranges, timeout_ms=300):
            return {}

        def read_byte(self, addr, timeout_ms=200):
            return 0

        def write_pairs(self, pairs):
            self.pairs.append(pairs)
            return True

        def close(self):
            return None

    endpoint = WriteEndpoint()

    response = handle_helper_request({"op": "write_pairs", "pairs": [[0x0657, 1]]}, endpoint)

    assert response == {"ok": True}
    assert endpoint.pairs == [[(0x0657, 1)]]


def test_helper_request_reports_failed_write_capable_endpoint():
    class FailingWriteEndpoint:
        def write_pairs(self, pairs):
            return False

    response = handle_helper_request(
        {"op": "write_pairs", "pairs": [[0x0657, 1]]},
        FailingWriteEndpoint(),
    )

    assert response == {"ok": False, "error": "write_failed"}


def test_helper_client_reads_ranges_from_helper_response():
    requests = []

    def request(payload):
        requests.append(payload)
        return {"ok": True, "frame": 77, "values": [[0x0012, 0x05], [0x0657, 0x01]]}

    endpoint = MisterHelperMemoryEndpoint(request=request)

    assert endpoint.read_ranges([(0x0012, 1), (0x0657, 1)]) == {
        0x0012: 0x05,
        0x0657: 0x01,
    }
    assert endpoint.last_frame == 77
    assert requests == [{"op": "read_ranges", "ranges": [[0x0012, 1], [0x0657, 1]]}]


def test_helper_client_returns_none_for_busy_or_inactive_response():
    endpoint = MisterHelperMemoryEndpoint(
        request=lambda payload: {"ok": False, "error": "mirror_busy_or_inactive", "frame": 88}
    )

    assert endpoint.read_byte(0x0012) is None
    assert endpoint.last_frame == 88
    assert endpoint.last_error == "mirror_busy_or_inactive"


def test_helper_client_preserves_write_not_supported_contract():
    endpoint = MisterHelperMemoryEndpoint(
        request=lambda payload: {"ok": False, "error": "writes_not_supported"}
    )

    with pytest.raises(NotImplementedError):
        endpoint.write_pairs([(0x0657, 1)])


def test_helper_client_returns_false_for_failed_write():
    endpoint = MisterHelperMemoryEndpoint(
        request=lambda payload: {"ok": False, "error": "write_failed"}
    )

    assert endpoint.write_pairs([(0x0657, 1)]) is False


def test_helper_client_sends_write_pairs_to_helper():
    requests = []

    def request(payload):
        requests.append(payload)
        return {"ok": True}

    endpoint = MisterHelperMemoryEndpoint(request=request)

    assert endpoint.write_pairs([(0x0657, 1), (0x0671, 3)]) is True
    assert requests == [
        {"op": "write_pairs", "pairs": [[0x0657, 1], [0x0671, 3]]}
    ]


def test_helper_server_serves_json_line_reads_over_tcp():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    read_endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(cpu_ram=cpu_ram))
    server = MisterHelperServer(("127.0.0.1", 0), read_endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        client = MisterHelperMemoryEndpoint(host=host, port=port)

        assert client.read_byte(0x0012) == 0x05
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
