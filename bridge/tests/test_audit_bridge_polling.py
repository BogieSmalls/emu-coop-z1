from audit_bridge_polling import analyze_snapshot, ranges_for_pattern
from bridge_core.modes import tloz_all


def test_ranges_for_pattern_replays_tloz_all_bridge_polling():
    assert ranges_for_pattern("tloz_all") == tloz_all.READ_RANGES


def test_ranges_for_pattern_can_isolate_inventory():
    assert ranges_for_pattern("inventory") == [(0x0657, 0x26)]


def test_analyze_snapshot_reports_implausible_inventory_value():
    snapshot = {0x0012: 0x05, 0x065A: 0xFF}

    anomalies = analyze_snapshot(snapshot, [(0x0657, 0x26)])

    assert "0x065A Bow value 255 exceeds max 1" in anomalies


def test_analyze_snapshot_reports_mostly_ff_range():
    snapshot = {0x067F + offset: 0xFF for offset in range(0x80)}

    anomalies = analyze_snapshot(snapshot, [(0x067F, 0x80)])

    assert "0x067F+128 is 100% FF" in anomalies
