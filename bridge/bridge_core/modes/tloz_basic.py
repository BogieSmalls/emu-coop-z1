"""Python port of modes/tloz_basic.lua.

Z1 mode that syncs only the basic inventory items (sword, bow, candle, etc.)
and not progress flags (compasses, maps, triforce). Subset of tloz_all.

Must match the Lua mode's guid byte-for-byte so the cross-implementation hello
handshake validates. If you change the SYNC table, regenerate the GUID in BOTH
files.
"""
from __future__ import annotations

GUID = "e7cc9d84-959f-4d72-84bb-99212a30f1bb"
FORMAT = "1.1"
NAME = "The Legend of Zelda (sync items only)"
MATCH = {"kind": "stringtest", "addr": 0xFFEB, "value": "ZELDA"}
RUNNING_ADDR = 0x12
RUNNING_RANGE = (0x4, 0xD)


def is_running(memory: dict[int, int]) -> bool:
    state = memory.get(RUNNING_ADDR, 0)
    return RUNNING_RANGE[0] <= state <= RUNNING_RANGE[1]


# Contiguous (base, length) ranges to poll via Action 0x01 (ArrayRead).
# Just the inventory band; no maps in this mode.
READ_RANGES: list[tuple[int, int]] = [
    (0x0012, 1),     # RUNNING_ADDR
    (0x0657, 0x20),  # inventory items, 0x0657-0x0676
]


SYNC: dict[int, dict] = {
    # multi-items
    0x0657: {"name_map": ["Wood Sword", "White Sword", "Magical Sword"], "kind": "high"},
    0x0659: {"name_map": ["Arrow", "Silver Arrow"], "kind": "high"},
    0x065B: {"name_map": ["Blue Candle", "Red Candle"], "kind": "high"},
    # 0x065E (Potion) is intentionally skipped — disposable, players buy their own.
    0x0662: {"name_map": ["Blue Ring", "Red Ring"], "kind": "high"},
    # singular items
    0x065A: {"name": "Bow", "kind": "high"},
    0x065C: {"name": "Recorder", "kind": "high"},
    0x065F: {"name": "Magical Rod", "kind": "high"},
    0x0660: {"name": "Raft", "kind": "high"},
    0x0661: {"name": "Magic Book", "kind": "high"},
    0x0663: {"name": "Step Ladder", "kind": "high"},
    0x0664: {"name": "Magical Key", "kind": "high"},
    0x0665: {"name": "Power Bracelet", "kind": "high"},
    0x0666: {"name": "Letter", "kind": "high"},
    0x0674: {"name": "Boomerang", "kind": "high"},
    0x0675: {"name": "Magical Boomerang", "kind": "high"},
    0x0676: {"name": "Magical Shield", "kind": "high"},
}
