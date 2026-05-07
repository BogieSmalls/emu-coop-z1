from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine

from .mister_mirror_factory import make_nes_ra_mirror


def test_readonly_mister_tloz_all_emits_sword_pickup():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0657] = 0x00
    mirror = make_nes_ra_mirror(cpu_ram=cpu_ram)
    endpoint = ReadOnlyMisterMemoryEndpoint(mirror)
    engine = SyncEngine(endpoint=endpoint, mode=tloz_all)
    first_snapshot = endpoint.read_ranges(tloz_all.READ_RANGES)
    assert first_snapshot is not None
    engine.check_first_running(first_snapshot)

    mirror[0x40 + 0x0657] = 0x01
    next_snapshot = endpoint.read_ranges(tloz_all.READ_RANGES)
    assert next_snapshot is not None
    changes = engine.diff(next_snapshot)

    assert (0x0657, 0x01, "You got Wood Sword") in changes


def test_readonly_mister_tloz_all_emits_map_flag_change():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    room_addr = 0x067F
    mirror = make_nes_ra_mirror(cpu_ram=cpu_ram)
    endpoint = ReadOnlyMisterMemoryEndpoint(mirror)
    engine = SyncEngine(endpoint=endpoint, mode=tloz_all)
    first_snapshot = endpoint.read_ranges(tloz_all.READ_RANGES)
    assert first_snapshot is not None
    engine.check_first_running(first_snapshot)

    mirror[0x40 + room_addr] = 0x10
    next_snapshot = endpoint.read_ranges(tloz_all.READ_RANGES)
    assert next_snapshot is not None
    changes = engine.diff(next_snapshot)

    assert (room_addr, 0x10, None) in changes
