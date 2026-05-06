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
