"""Sync engine — Python port of driver.lua.

record_changed() is line-by-line equivalent to the Lua function. Other parts
(SyncEngine class with poll/cache/handleTable) come in a later task.
"""
from __future__ import annotations

from typing import Any, Callable


def record_changed(
    record: dict[str, Any],
    value: int,
    previous_value: int,
    receiving: bool,
) -> tuple[bool, int]:
    """Port of driver.lua's recordChanged().

    Returns (allow, value): whether to send/apply this change, and the resolved
    value to send/apply (which may differ from the input).
    """
    if record.get("kind") == "trigger":
        return False, value

    unaltered = value
    allow = True

    # Compute mask
    size = record.get("size", 1)
    if size == 2:
        mask = 0xFFFF
    elif size == 4:
        mask = 0xFFFFFFFF
    else:
        mask = 0xFF

    inverse_mask = 0
    masked_value = value

    if "mask" in record:
        mask = record["mask"]
        inverse_mask = (~mask) & 0xFFFFFFFF
        masked_value = (mask & value) | (inverse_mask & previous_value)

    kind = record.get("kind")

    if callable(kind):
        result = kind(value, previous_value, receiving)
        if isinstance(result, tuple):
            allow, value = result
        else:
            allow = bool(result)
        if value is None:
            value = unaltered
    elif kind == "high":
        allow = (mask & value) > (mask & previous_value)
        value = masked_value
    elif kind == "bitOr":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value | previous_value
    elif kind == "bitAnd":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value & previous_value
    elif kind == "delta":
        if not receiving:
            allow = masked_value != previous_value
            value = (mask & value) - (mask & previous_value)
        else:
            allow = value != 0
            masked_sum = previous_value + value
            if "deltaMin" in record and masked_sum < record["deltaMin"]:
                masked_sum = record["deltaMin"]
            if "deltaMax" in record and masked_sum > record["deltaMax"]:
                masked_sum = record["deltaMax"]
            value = (inverse_mask & previous_value) | (mask & masked_sum)
    else:
        allow = masked_value != previous_value
        value = masked_value

    if allow and "cond" in record:
        # cond is a callable: cond(value, size) -> bool
        cond_fn = record["cond"]
        if callable(cond_fn):
            allow = cond_fn(masked_value, size)

    return allow, value
