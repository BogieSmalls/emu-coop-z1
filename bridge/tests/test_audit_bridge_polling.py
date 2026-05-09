from audit_bridge_polling import (
    _read_ranges_with_timings,
    addresses_for_ranges,
    analyze_snapshot,
    ranges_for_pattern,
)
from bridge_core.modes import tloz_all


def test_ranges_for_pattern_replays_tloz_all_bridge_polling():
    assert ranges_for_pattern("tloz_all") == tloz_all.READ_RANGES


def test_ranges_for_pattern_can_isolate_inventory():
    assert ranges_for_pattern("inventory") == [(0x0657, 0x26)]


def test_addresses_for_ranges_flattens_ranges():
    assert addresses_for_ranges([(0x0012, 1), (0x0657, 3)]) == [
        0x0012,
        0x0657,
        0x0658,
        0x0659,
    ]


def test_analyze_snapshot_reports_implausible_inventory_value():
    snapshot = {0x0012: 0x05, 0x065A: 0xFF}

    anomalies = analyze_snapshot(snapshot, [(0x0657, 0x26)])

    assert "0x065A Bow value 255 exceeds max 1" in anomalies


def test_analyze_snapshot_reports_mostly_ff_range():
    snapshot = {0x067F + offset: 0xFF for offset in range(0x80)}

    anomalies = analyze_snapshot(snapshot, [(0x067F, 0x80)])

    assert "0x067F+128 is 100% FF" in anomalies


def test_analyze_snapshot_allows_mostly_zero_range():
    snapshot = {0x067F + offset: 0x00 for offset in range(0x80)}

    anomalies = analyze_snapshot(snapshot, [(0x067F, 0x80)])

    assert anomalies == []


class FakeCCClient:
    def __init__(self) -> None:
        self.array_calls: list[tuple[int, int, int]] = []
        self.addrs_calls: list[tuple[list[int], int]] = []

    def read_array(self, base: int, length: int, timeout_ms: int) -> bytes:
        self.array_calls.append((base, length, timeout_ms))
        return bytes(range(length))

    def read_addrs(self, addrs: list[int], timeout_ms: int) -> bytes:
        self.addrs_calls.append((addrs, timeout_ms))
        return bytes(range(len(addrs)))


def test_read_ranges_with_timings_can_use_array_method():
    client = FakeCCClient()

    snapshot, timings = _read_ranges_with_timings(client, [(0x0657, 3)], 300, method="array")

    assert client.array_calls == [(0x0657, 3, 300)]
    assert client.addrs_calls == []
    assert snapshot == {0x0657: 0, 0x0658: 1, 0x0659: 2}
    assert timings[0][0:2] == (0x0657, 3)


def test_read_ranges_with_timings_can_use_individual_address_method():
    client = FakeCCClient()

    snapshot, timings = _read_ranges_with_timings(client, [(0x0657, 3)], 300, method="addrs")

    assert client.array_calls == []
    assert client.addrs_calls == [([0x0657, 0x0658, 0x0659], 300)]
    assert snapshot == {0x0657: 0, 0x0658: 1, 0x0659: 2}
    assert timings[0][0:2] == (0x0657, 3)
