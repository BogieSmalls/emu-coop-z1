"""Python port of modes/tloz_all.lua.

Must match the Lua mode's guid byte-for-byte so the cross-implementation hello
handshake validates. Address coverage and recordChanged semantics must also
match exactly.

If you change ANYTHING in this file, regenerate the GUID in BOTH files.
"""
from __future__ import annotations

GUID = "377c5683-3cf5-4c56-a921-ab40257b2ec1"
FORMAT = "1.2"
NAME = "The Legend of Zelda (sync most things)"
MATCH = {"kind": "stringtest", "addr": 0xFFEB, "value": "ZELDA"}
RUNNING_ADDR = 0x12
RUNNING_RANGE = (0x4, 0xD)

# Contiguous (base, length) ranges to poll via Action 0x01 (ArrayRead).
# Using ArrayRead instead of scattered Action 0x00 reads keeps the cart's
# per-response handler work tiny (1 LDA per byte vs 1 LDA-via-pointer per
# byte plus lots of address dereference work), which matters during Z1
# state transitions where the game's main loop has tight timing.
# These ranges cover RUNNING_ADDR + the entire SYNC set, with some unused
# bytes pulled along; the diff logic only consults SYNC keys so extras are free.
READ_RANGES: list[tuple[int, int]] = [
    (0x0012, 1),     # RUNNING_ADDR
    (0x0657, 0x26),  # inventory + progress items, $0657-$067C (gaps OK)
    (0x067F, 0x80),  # overworld map: $067F-$06FE
    (0x06FF, 0x80),  # dungeon flags part 1: $06FF-$077E
    (0x077F, 0x80),  # dungeon flags part 2: $077F-$07FE
]


def is_running(memory: dict[int, int]) -> bool:
    """Returns True if the game is in a 'running' state.

    `memory` is a dict of {addr: value} containing at least RUNNING_ADDR.
    """
    state = memory.get(RUNNING_ADDR, 0)
    return RUNNING_RANGE[0] <= state <= RUNNING_RANGE[1]


def _plural(count: int, name: str) -> str:
    return f"{count} {name}" + ("s" if count != 1 else "")


# --- Heart container handler (function-as-kind) ---
# hearts: high nibble = container count - 1; low nibble = filled hearts - 1


def _heart_kind(value: int, previous_value: int, receiving: bool):
    if receiving:
        prev_container = (previous_value & 0xF0) >> 4
        new_container = (value & 0xF0) >> 4
        if new_container > prev_container:
            new_value = (
                (value & 0xF0)
                | ((previous_value & 0x0F) + (new_container - prev_container)) & 0x0F
            )
            return True, new_value
        else:
            currently_filled = previous_value & 0x0F
            new_value = (
                (value & 0xF0) | (min(currently_filled, new_container) & 0x0F)
            )
            return True, new_value
    else:
        return ((value & 0xF0) != (previous_value & 0xF0)), value


def _heart_message(value: int, previous_value: int) -> str | None:
    """Return a string suitable for the status sink (or None if no message)."""
    prev_container = (previous_value & 0xF0) >> 4
    new_container = (value & 0xF0) >> 4
    if new_container > prev_container:
        return "Partner gained " + _plural(new_container - prev_container, "Heart Container")
    elif new_container < prev_container:
        return "Partner lost " + _plural(prev_container - new_container, "Heart Container")
    return None


# --- Bomb upgrade handler ---


def _bomb_receive_trigger(value: int, previous_value: int) -> str:
    """Side-effect: write current bomb count to 0x0658. Status string returned."""
    if value > previous_value:
        return "Partner got a bomb upgrade of " + _plural(value - previous_value, "bomb")
    else:
        return "Partner chose to get rid of " + _plural(previous_value - value, "bomb")


# --- Sync table ---

SYNC: dict[int, dict] = {
    # multi-items
    0x0657: {"name_map": ["Wood Sword", "White Sword", "Magical Sword"], "kind": "high"},
    0x0659: {"name_map": ["Arrow", "Silver Arrow"], "kind": "high"},
    0x065B: {"name_map": ["Blue Candle", "Red Candle"], "kind": "high"},
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
    # progress: compasses + maps + triforce (inherited from tloz_progress.lua)
    0x0667: {
        "name_bitmap": [
            "Level 1 Compass", "Level 2 Compass", "Level 3 Compass", "Level 4 Compass",
            "Level 5 Compass", "Level 6 Compass", "Level 7 Compass", "Level 8 Compass",
        ],
        "kind": "bitOr",
    },
    0x0668: {
        "name_bitmap": [
            "Level 1 Map", "Level 2 Map", "Level 3 Map", "Level 4 Map",
            "Level 5 Map", "Level 6 Map", "Level 7 Map", "Level 8 Map",
        ],
        "kind": "bitOr",
    },
    0x0669: {"name": "Level 9 Compass", "kind": "high"},
    0x066A: {"name": "Level 9 Map", "kind": "high"},
    0x0671: {
        "name_bitmap": [
            "First Triforce Piece", "Second Triforce Piece", "Third Triforce Piece",
            "Fourth Triforce Piece", "Fifth Triforce Piece", "Sixth Triforce Piece",
            "Seventh Triforce Piece", "Eighth Triforce Piece",
        ],
        "kind": "bitOr",
    },
    0x0672: {"name": "Triforce of Power", "kind": "high"},
    # keys (delta)
    0x066E: {"kind": "delta", "deltaMin": 0},
    # heart containers (function-as-kind)
    0x066F: {"kind": _heart_kind, "message": _heart_message},
    # bomb upgrade (delta with side-effect on receive)
    0x067C: {
        "kind": "delta",
        "deltaMin": 1,
        "deltaMax": 255,
        "ignoreZeroBoundary": True,
        "receive_trigger": _bomb_receive_trigger,
    },
}

# Overworld map: 0x067F..0x06FE (each tile: 0x80 if requires-item-and-opened, 0x10 if obtained)
for _i in range(0x067F, 0x06FF):
    SYNC[_i] = {"kind": "bitOr", "mask": 0x80 | 0x10}

# Dungeon map: 0x06FF..0x07FE (top-room-flags + visited + item-collected + key-doors)
for _i in range(0x06FF, 0x07FF):
    SYNC[_i] = {"kind": "bitOr"}
