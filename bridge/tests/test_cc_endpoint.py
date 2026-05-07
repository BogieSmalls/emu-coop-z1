from bridge_core.cc_client import CCClient
from bridge_core.cc_endpoint import CCMemoryEndpoint

from .mock_cc_server import MockCCServer


class FakeCCClient:
    def __init__(self) -> None:
        self.read_ranges_calls = []
        self.read_addrs_calls = []
        self.write_pairs_calls = []
        self.closed = False

    def read_ranges(self, ranges, timeout_ms=300):
        self.read_ranges_calls.append((ranges, timeout_ms))
        return {0x0012: 0x05}

    def send_read_addrs(self, addrs):
        self.read_addrs_calls.append(addrs)

    def poll_response(self, timeout_ms=200):
        return bytes([0x01])

    def send_write_pairs(self, pairs):
        self.write_pairs_calls.append(pairs)

    def close(self):
        self.closed = True


def test_cc_endpoint_delegates_read_ranges():
    client = FakeCCClient()
    endpoint = CCMemoryEndpoint(client)

    assert endpoint.read_ranges([(0x0012, 1)], timeout_ms=123) == {0x0012: 0x05}
    assert client.read_ranges_calls == [([(0x0012, 1)], 123)]


def test_cc_endpoint_reads_single_byte():
    client = FakeCCClient()
    endpoint = CCMemoryEndpoint(client)

    assert endpoint.read_byte(0x0657, timeout_ms=456) == 0x01
    assert client.read_addrs_calls == [[0x0657]]


def test_cc_endpoint_write_pairs_updates_cart_ram():
    server = MockCCServer()
    endpoint = CCMemoryEndpoint(CCClient(server.serial))

    assert endpoint.write_pairs([(0x0657, 0x01)]) is True
    server.step()

    assert server.ram[0x0657] == 0x01


def test_cc_endpoint_closes_client():
    client = FakeCCClient()
    endpoint = CCMemoryEndpoint(client)

    endpoint.close()

    assert client.closed is True
