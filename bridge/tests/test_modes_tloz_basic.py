"""Mode-parity tests: tloz_basic.py must agree with modes/tloz_basic.lua on guid + addresses."""
from bridge_core.modes import tloz_basic


def test_guid_matches_lua_mode():
    assert tloz_basic.GUID == "e7cc9d84-959f-4d72-84bb-99212a30f1bb"


def test_format_matches_lua_mode():
    assert tloz_basic.FORMAT == "1.1"


def test_running_predicate_for_z1_states():
    assert tloz_basic.is_running({0x12: 0x4}) is True
    assert tloz_basic.is_running({0x12: 0xD}) is True
    assert tloz_basic.is_running({0x12: 0x0}) is False
    assert tloz_basic.is_running({0x12: 0xE}) is False


def test_sync_includes_inventory_addresses():
    expected = [0x0657, 0x0659, 0x065A, 0x065B, 0x065C, 0x065F, 0x0660, 0x0661,
                0x0662, 0x0663, 0x0664, 0x0665, 0x0666, 0x0674, 0x0675, 0x0676]
    for addr in expected:
        assert addr in tloz_basic.SYNC, f"missing inventory addr 0x{addr:04X}"


def test_sync_excludes_progress_addresses():
    """tloz_basic should NOT include compass/map/triforce — that's tloz_progress."""
    excluded = [0x0667, 0x0668, 0x0669, 0x066A, 0x0671, 0x0672]
    for addr in excluded:
        assert addr not in tloz_basic.SYNC, f"tloz_basic should not include progress addr 0x{addr:04X}"


def test_sync_excludes_map_ranges():
    """tloz_basic should NOT include overworld / dungeon map — that's tloz_all."""
    for addr in [0x067F, 0x06FF, 0x0780, 0x07FE]:
        assert addr not in tloz_basic.SYNC, f"tloz_basic should not include map addr 0x{addr:04X}"


def test_potion_excluded():
    """0x065E (Potion) is intentionally skipped — disposable, players buy their own."""
    assert 0x065E not in tloz_basic.SYNC


def test_read_ranges_cover_all_sync_keys():
    covered = set()
    for base, length in tloz_basic.READ_RANGES:
        for i in range(length):
            covered.add(base + i)
    assert tloz_basic.RUNNING_ADDR in covered
    for addr in tloz_basic.SYNC:
        assert addr in covered, f"SYNC addr 0x{addr:04X} not in any READ_RANGES"
