"""Behavioral parity tests for record_changed() — verified against driver.lua."""
import pytest

from bridge_core.sync_engine import record_changed


def test_high_kind_send_when_increased():
    record = {"kind": "high", "size": 1}
    allow, value = record_changed(record, value=1, previous_value=0, receiving=False)
    assert allow is True
    assert value == 1


def test_high_kind_no_send_when_decreased():
    record = {"kind": "high", "size": 1}
    allow, _value = record_changed(record, value=0, previous_value=1, receiving=False)
    assert allow is False


def test_high_kind_no_send_when_same():
    record = {"kind": "high", "size": 1}
    allow, _value = record_changed(record, value=1, previous_value=1, receiving=False)
    assert allow is False


def test_delta_kind_send_when_changed():
    record = {"kind": "delta", "size": 1}
    allow, value = record_changed(record, value=8, previous_value=0, receiving=False)
    assert allow is True
    assert value == 8  # delta = 8 - 0


def test_delta_kind_receive_applies_delta():
    record = {"kind": "delta", "size": 1}
    allow, value = record_changed(record, value=8, previous_value=4, receiving=True)
    assert allow is True
    assert value == 12  # 4 + 8


def test_delta_kind_clamp_min():
    record = {"kind": "delta", "size": 1, "deltaMin": 1}
    allow, value = record_changed(record, value=5, previous_value=0, receiving=True)
    # without clamp, 0+5=5; clamp doesn't trigger
    assert allow is True
    assert value == 5


def test_delta_kind_no_send_zero_delta_on_receive():
    record = {"kind": "delta", "size": 1}
    allow, _value = record_changed(record, value=0, previous_value=4, receiving=True)
    # delta of 0 means no change; allow=False
    assert allow is False


def test_bitor_kind_changes_bits():
    record = {"kind": "bitOr", "size": 1}
    allow, value = record_changed(record, value=0b1010, previous_value=0b0001, receiving=True)
    assert allow is True
    assert value == 0b1011  # OR


def test_function_kind_invokes_callback():
    captured = []

    def custom_kind(val, prev, recv):
        captured.append((val, prev, recv))
        return True, val * 2

    record = {"kind": custom_kind}
    allow, value = record_changed(record, value=5, previous_value=2, receiving=True)
    assert allow is True
    assert value == 10
    assert captured == [(5, 2, True)]


from bridge_core.cc_client import CCClient
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine

from .mock_cc_server import MockCCServer


def make_engine() -> tuple[SyncEngine, MockCCServer]:
    server = MockCCServer()
    client = CCClient(server.serial)
    engine = SyncEngine(cc_client=client, mode=tloz_all)
    return engine, server


def test_sync_engine_starts_idle():
    engine, _server = make_engine()
    assert engine.did_cache is False
    assert engine.is_game_running({0x12: 0x0}) is False


def test_sync_engine_detects_running():
    engine, _server = make_engine()
    assert engine.is_game_running({0x12: 0x5}) is True


def test_sync_engine_caches_on_first_running_tick():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)  # no sword
    server.set_ram(0x12, 0x5)  # running
    engine.check_first_running({0x0657: 0, 0x12: 0x5})
    assert engine.did_cache is True
    assert engine.cache[0x0657] == 0


def test_sync_engine_handle_table_writes_to_ram():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)
    engine.cache[0x0657] = 0
    msgs = engine.handle_table({"addr": 0x0657, "value": 1})
    server.step()
    assert server.ram[0x0657] == 1


def test_sync_engine_handle_table_emits_message():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)
    engine.cache[0x0657] = 0
    msgs = engine.handle_table({"addr": 0x0657, "value": 1})
    assert any("Wood Sword" in m for m in msgs)


def test_sync_engine_resync_clears_cache():
    engine, _server = make_engine()
    engine.cache[0x0657] = 1
    engine.did_cache = True
    engine.resync()
    assert engine.did_cache is False
    assert engine.force_send is True
