"""Mode-parity tests: tloz_progress.py must agree with modes/tloz_progress.lua on guid + addresses."""
from bridge_core.modes import tloz_basic, tloz_progress


def test_guid_matches_lua_mode():
    assert tloz_progress.GUID == "658ed546-4984-4203-9e10-5866d2bc05c0"


def test_format_matches_lua_mode():
    assert tloz_progress.FORMAT == "1.1"


def test_inherits_all_basic_inventory_addresses():
    """tloz_progress = tloz_basic.sync + progress flags."""
    for addr in tloz_basic.SYNC:
        assert addr in tloz_progress.SYNC, f"tloz_progress missing tloz_basic addr 0x{addr:04X}"


def test_includes_progress_flags():
    expected = [0x0667, 0x0668, 0x0669, 0x066A, 0x0671, 0x0672]
    for addr in expected:
        assert addr in tloz_progress.SYNC, f"missing progress addr 0x{addr:04X}"


def test_compasses_use_bitmap():
    record = tloz_progress.SYNC[0x0667]
    assert record["kind"] == "bitOr"
    assert "name_bitmap" in record
    assert len(record["name_bitmap"]) == 8


def test_triforce_pieces_use_bitmap():
    record = tloz_progress.SYNC[0x0671]
    assert record["kind"] == "bitOr"
    assert "name_bitmap" in record
    assert len(record["name_bitmap"]) == 8


def test_excludes_map_ranges():
    """tloz_progress should NOT include the overworld / dungeon map ranges — that's tloz_all."""
    for addr in [0x067F, 0x06FF, 0x0780, 0x07FE]:
        assert addr not in tloz_progress.SYNC, f"tloz_progress should not include map addr 0x{addr:04X}"


def test_running_predicate_for_z1_states():
    assert tloz_progress.is_running({0x12: 0x4}) is True
    assert tloz_progress.is_running({0x12: 0xD}) is True
    assert tloz_progress.is_running({0x12: 0x0}) is False


def test_read_ranges_cover_all_sync_keys():
    covered = set()
    for base, length in tloz_progress.READ_RANGES:
        for i in range(length):
            covered.add(base + i)
    assert tloz_progress.RUNNING_ADDR in covered
    for addr in tloz_progress.SYNC:
        assert addr in covered, f"SYNC addr 0x{addr:04X} not in any READ_RANGES"
