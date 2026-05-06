"""Mode-parity tests: tloz_all.py must agree with modes/tloz_all.lua on guid + addresses."""
import pytest

from bridge_core.modes import tloz_all


def test_guid_matches_lua_mode():
    """Must match modes/tloz_all.lua's guid line-for-line."""
    assert tloz_all.GUID == "377c5683-3cf5-4c56-a921-ab40257b2ec1"


def test_format_matches_lua_mode():
    assert tloz_all.FORMAT == "1.2"


def test_running_predicate_for_z1_states():
    """Z1 state register is 0x12; 'running' = state in [0x4, 0xD]."""
    assert tloz_all.is_running({0x12: 0x4}) is True
    assert tloz_all.is_running({0x12: 0xD}) is True
    assert tloz_all.is_running({0x12: 0x0}) is False
    assert tloz_all.is_running({0x12: 0x3}) is False
    assert tloz_all.is_running({0x12: 0xE}) is False


def test_sync_includes_inventory_addresses():
    """Wood Sword (0x0657), Bow (0x065A), Recorder (0x065C) etc. must be in sync."""
    expected = [0x0657, 0x065A, 0x065C, 0x065F, 0x0660, 0x0661, 0x0663, 0x0664, 0x0665, 0x0666, 0x0674, 0x0675, 0x0676]
    for addr in expected:
        assert addr in tloz_all.SYNC, f"missing inventory addr 0x{addr:04X}"


def test_sync_includes_overworld_map_range():
    """Overworld map is 0x067F..0x06FE."""
    for addr in range(0x067F, 0x06FF):
        assert addr in tloz_all.SYNC, f"missing overworld map addr 0x{addr:04X}"


def test_sync_includes_dungeon_map_range():
    """Dungeon map is 0x06FF..0x07FE."""
    for addr in range(0x06FF, 0x07FF):
        assert addr in tloz_all.SYNC, f"missing dungeon map addr 0x{addr:04X}"


def test_heart_record_kind_is_callable():
    """Heart container handler is a function-as-kind."""
    assert callable(tloz_all.SYNC[0x066F]["kind"])


def test_bomb_record_has_delta_kind():
    record = tloz_all.SYNC[0x067C]
    assert record["kind"] == "delta"


def test_sync_includes_progress_inherited_addresses():
    """tloz_all.lua inherits from tloz_progress.lua, which adds compass/map/triforce.
    These are critical for Z1R co-op — skipping them would break triforce-piece sync."""
    expected = [0x0667, 0x0668, 0x0669, 0x066A, 0x0671, 0x0672]
    for addr in expected:
        assert addr in tloz_all.SYNC, f"missing progress addr 0x{addr:04X}"


def test_triforce_pieces_record_has_bitmap():
    """0x0671 is the triforce-pieces register; each bit = one piece."""
    record = tloz_all.SYNC[0x0671]
    assert record["kind"] == "bitOr"
    assert "name_bitmap" in record
    assert len(record["name_bitmap"]) == 8
