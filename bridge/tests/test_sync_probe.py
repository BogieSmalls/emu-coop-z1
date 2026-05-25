from bridge_core.modes import tloz_progress
from bridge_core.sync_probe import read_running_probe, read_running_probe_detail


class FakeEndpoint:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.read_ranges_calls = []

    def read_ranges(self, ranges, timeout_ms=300):
        self.read_ranges_calls.append((ranges, timeout_ms))
        return self.snapshot


def test_read_running_probe_detail_includes_running_byte_value():
    endpoint = FakeEndpoint({0x0012: 0x00})

    result = read_running_probe_detail(endpoint, tloz_progress, timeout_ms=123)

    assert result.running is False
    assert result.addr == 0x0012
    assert result.value == 0x00
    assert endpoint.read_ranges_calls == [([(0x0012, 1)], 123)]


def test_read_running_probe_keeps_boolean_compatibility():
    endpoint = FakeEndpoint({0x0012: 0x05})

    assert read_running_probe(endpoint, tloz_progress) is True
