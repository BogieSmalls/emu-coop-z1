"""Python port of modes/tloz_progress.lua.

Z1 mode that syncs basic inventory items + progress flags (level compasses,
level maps, triforce pieces). Superset of tloz_basic, subset of tloz_all
(no overworld/dungeon map syncing).

Must match the Lua mode's guid byte-for-byte so the cross-implementation hello
handshake validates. If you change the SYNC table, regenerate the GUID in BOTH
files.
"""
from __future__ import annotations

from bridge_core.modes import tloz_basic

GUID = "658ed546-4984-4203-9e10-5866d2bc05c0"
FORMAT = "1.1"
NAME = "The Legend of Zelda (sync normal and progress items)"
MATCH = {"kind": "stringtest", "addr": 0xFFEB, "value": "ZELDA"}
RUNNING_ADDR = 0x12
RUNNING_RANGE = (0x4, 0xD)


def is_running(memory: dict[int, int]) -> bool:
    state = memory.get(RUNNING_ADDR, 0)
    return RUNNING_RANGE[0] <= state <= RUNNING_RANGE[1]


# Same range as tloz_basic — all the new addresses (0x0667-0x0672)
# fall within 0x0657-0x0676 already covered by the inventory band.
READ_RANGES: list[tuple[int, int]] = [
    (0x0012, 1),     # RUNNING_ADDR
    (0x0657, 0x20),  # inventory + progress, 0x0657-0x0676
]


# Start with all of tloz_basic's items, then add the progress flags.
SYNC: dict[int, dict] = dict(tloz_basic.SYNC)

SYNC[0x0667] = {
    "name_bitmap": [
        "Level 1 Compass", "Level 2 Compass", "Level 3 Compass", "Level 4 Compass",
        "Level 5 Compass", "Level 6 Compass", "Level 7 Compass", "Level 8 Compass",
    ],
    "kind": "bitOr",
}
SYNC[0x0668] = {
    "name_bitmap": [
        "Level 1 Map", "Level 2 Map", "Level 3 Map", "Level 4 Map",
        "Level 5 Map", "Level 6 Map", "Level 7 Map", "Level 8 Map",
    ],
    "kind": "bitOr",
}
SYNC[0x0669] = {"name": "Level 9 Compass", "kind": "high"}
SYNC[0x066A] = {"name": "Level 9 Map", "kind": "high"}
SYNC[0x0671] = {
    "name_bitmap": [
        "First Triforce Piece", "Second Triforce Piece", "Third Triforce Piece",
        "Fourth Triforce Piece", "Fifth Triforce Piece", "Sixth Triforce Piece",
        "Seventh Triforce Piece", "Eighth Triforce Piece",
    ],
    "kind": "bitOr",
}
SYNC[0x0672] = {"name": "Triforce of Power", "kind": "high"}
