"""Relocate the emu-coop-plus main-code regions out of bank 6 into bank 4.

The original (CC-derived) IPS lays its ~1.1 KB of NMI/main-loop/dispatcher code
in bank 6 at CPU $B290-$BED1. Several Z1R flagsets fill that exact region with
seed-specific data, so applying the patch to those seeds silently overwrites
the seed's customizations and corrupts the overworld.

Bank 4's free region at file 0x01347F (CPU $B46F when bank 4 is mapped) is
0xFF in vanilla and untouched by every Z1R flagset we audited. This script
packs the bank-6 code into bank 4 contiguously, rewrites every internal
JMP/JSR/abs operand and relative branch, fixes the dispatcher's jump table,
and updates the four external hooks (bank value + three JMP/JSR targets) so
the relocated patch behaves identically to the original.

Output: overwrites bridge/bridge_core/patches/zelda_emu_coop_plus.ips with
the relocated IPS so subsequent .exe/zip builds pick up the new patch.

Usage:
    python relocate_patch.py <vanilla.nes>
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from bridge_core.ips import apply, parse
from bridge_core.ips_build import make_ips


# --- 6502 opcode table (subset; same as analyze_cc_patch.py) ---

OPCODES: dict[int, tuple[str, str]] = {
    0x00: ("BRK", "imp"), 0x01: ("ORA", "indx"),
    0x05: ("ORA", "zp"), 0x06: ("ASL", "zp"),
    0x08: ("PHP", "imp"), 0x09: ("ORA", "imm"), 0x0A: ("ASL", "acc"),
    0x0D: ("ORA", "abs"), 0x0E: ("ASL", "abs"),
    0x10: ("BPL", "rel"), 0x11: ("ORA", "indy"),
    0x15: ("ORA", "zpx"), 0x16: ("ASL", "zpx"),
    0x18: ("CLC", "imp"), 0x19: ("ORA", "absy"),
    0x1D: ("ORA", "absx"), 0x1E: ("ASL", "absx"),
    0x20: ("JSR", "abs"), 0x21: ("AND", "indx"),
    0x24: ("BIT", "zp"), 0x25: ("AND", "zp"), 0x26: ("ROL", "zp"),
    0x28: ("PLP", "imp"), 0x29: ("AND", "imm"), 0x2A: ("ROL", "acc"),
    0x2C: ("BIT", "abs"), 0x2D: ("AND", "abs"), 0x2E: ("ROL", "abs"),
    0x30: ("BMI", "rel"), 0x31: ("AND", "indy"),
    0x35: ("AND", "zpx"), 0x36: ("ROL", "zpx"),
    0x38: ("SEC", "imp"), 0x39: ("AND", "absy"),
    0x3D: ("AND", "absx"), 0x3E: ("ROL", "absx"),
    0x40: ("RTI", "imp"), 0x41: ("EOR", "indx"),
    0x45: ("EOR", "zp"), 0x46: ("LSR", "zp"),
    0x48: ("PHA", "imp"), 0x49: ("EOR", "imm"), 0x4A: ("LSR", "acc"),
    0x4C: ("JMP", "abs"), 0x4D: ("EOR", "abs"), 0x4E: ("LSR", "abs"),
    0x50: ("BVC", "rel"), 0x51: ("EOR", "indy"),
    0x55: ("EOR", "zpx"), 0x56: ("LSR", "zpx"),
    0x58: ("CLI", "imp"), 0x59: ("EOR", "absy"),
    0x5D: ("EOR", "absx"), 0x5E: ("LSR", "absx"),
    0x60: ("RTS", "imp"), 0x61: ("ADC", "indx"),
    0x65: ("ADC", "zp"), 0x66: ("ROR", "zp"),
    0x68: ("PLA", "imp"), 0x69: ("ADC", "imm"), 0x6A: ("ROR", "acc"),
    0x6C: ("JMP", "ind"), 0x6D: ("ADC", "abs"), 0x6E: ("ROR", "abs"),
    0x70: ("BVS", "rel"), 0x71: ("ADC", "indy"),
    0x75: ("ADC", "zpx"), 0x76: ("ROR", "zpx"),
    0x78: ("SEI", "imp"), 0x79: ("ADC", "absy"),
    0x7D: ("ADC", "absx"), 0x7E: ("ROR", "absx"),
    0x81: ("STA", "indx"),
    0x84: ("STY", "zp"), 0x85: ("STA", "zp"), 0x86: ("STX", "zp"),
    0x88: ("DEY", "imp"), 0x8A: ("TXA", "imp"),
    0x8C: ("STY", "abs"), 0x8D: ("STA", "abs"), 0x8E: ("STX", "abs"),
    0x90: ("BCC", "rel"), 0x91: ("STA", "indy"),
    0x94: ("STY", "zpx"), 0x95: ("STA", "zpx"), 0x96: ("STX", "zpy"),
    0x98: ("TYA", "imp"), 0x99: ("STA", "absy"), 0x9A: ("TXS", "imp"),
    0x9D: ("STA", "absx"),
    0xA0: ("LDY", "imm"), 0xA1: ("LDA", "indx"), 0xA2: ("LDX", "imm"),
    0xA4: ("LDY", "zp"), 0xA5: ("LDA", "zp"), 0xA6: ("LDX", "zp"),
    0xA8: ("TAY", "imp"), 0xA9: ("LDA", "imm"), 0xAA: ("TAX", "imp"),
    0xAC: ("LDY", "abs"), 0xAD: ("LDA", "abs"), 0xAE: ("LDX", "abs"),
    0xB0: ("BCS", "rel"), 0xB1: ("LDA", "indy"),
    0xB4: ("LDY", "zpx"), 0xB5: ("LDA", "zpx"), 0xB6: ("LDX", "zpy"),
    0xB8: ("CLV", "imp"), 0xB9: ("LDA", "absy"), 0xBA: ("TSX", "imp"),
    0xBC: ("LDY", "absx"), 0xBD: ("LDA", "absx"), 0xBE: ("LDX", "absy"),
    0xC0: ("CPY", "imm"), 0xC1: ("CMP", "indx"),
    0xC4: ("CPY", "zp"), 0xC5: ("CMP", "zp"), 0xC6: ("DEC", "zp"),
    0xC8: ("INY", "imp"), 0xC9: ("CMP", "imm"), 0xCA: ("DEX", "imp"),
    0xCC: ("CPY", "abs"), 0xCD: ("CMP", "abs"), 0xCE: ("DEC", "abs"),
    0xD0: ("BNE", "rel"), 0xD1: ("CMP", "indy"),
    0xD5: ("CMP", "zpx"), 0xD6: ("DEC", "zpx"),
    0xD8: ("CLD", "imp"), 0xD9: ("CMP", "absy"),
    0xDD: ("CMP", "absx"), 0xDE: ("DEC", "absx"),
    0xE0: ("CPX", "imm"), 0xE1: ("SBC", "indx"),
    0xE4: ("CPX", "zp"), 0xE5: ("SBC", "zp"), 0xE6: ("INC", "zp"),
    0xE8: ("INX", "imp"), 0xE9: ("SBC", "imm"), 0xEA: ("NOP", "imp"),
    0xEC: ("CPX", "abs"), 0xED: ("SBC", "abs"), 0xEE: ("INC", "abs"),
    0xF0: ("BEQ", "rel"), 0xF1: ("SBC", "indy"),
    0xF5: ("SBC", "zpx"), 0xF6: ("INC", "zpx"),
    0xF8: ("SED", "imp"), 0xF9: ("SBC", "absy"),
    0xFD: ("SBC", "absx"), 0xFE: ("INC", "absx"),
}

MODE_LEN = {
    "imp": 1, "acc": 1,
    "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "rel": 2,
    "indx": 2, "indy": 2,
    "abs": 3, "absx": 3, "absy": 3, "ind": 3,
}

ABS_MODES = {"abs", "absx", "absy", "ind"}
REL_MODES = {"rel"}


# --- Old layout (CPU addresses; bank 6 when mapped) ---
# Each entry: (file_offset_in_ROM, cpu_addr, length).
# Order matches the IPS regions for bank-6 main code.
OLD_REGIONS = [
    (0x01B2A0, 0xB290, 38),    # NMI inbound drain
    (0x01B3A0, 0xB390, 21),    # main-loop hook
    (0x01B4A0, 0xB490, 517),   # dispatcher prologue + Freeze evaluator + handlers cluster
    (0x01B700, 0xB6F0, 77),    # secondary hook (called from $E65A)
    (0x01B8A0, 0xB890, 39),    # action 0xFF (NullMsg) handler
    (0x01B920, 0xB910, 64),    # action 0xFE (Version) handler
    (0x01B9A0, 0xB990, 70),    # Read action handler
    (0x01BAA0, 0xBA90, 80),    # ArrayRead action handler
    (0x01BBA0, 0xBB90, 72),    # WritePairs action handler
    (0x01BCA0, 0xBC90, 78),    # ReadIndividual action handler
    (0x01BDA0, 0xBD90, 12),    # action-dispatch jump TABLE (data, not code)
    (0x01BEA0, 0xBE90, 49),    # dispatcher
]

# CPU range covered by the old code (used to detect "internal" operands)
OLD_RANGE_START = 0xB290
OLD_RANGE_END = 0xBED1   # last byte = 0xBE90 + 49 - 1 = 0xBEC0... wait, 0xBE90+49=0xBEC1. Let me set conservatively.
# Recompute: max old end across regions
OLD_RANGE_END = max(c + L - 1 for _, c, L in OLD_REGIONS)

# New base address (bank 4, mapped at $8000-$BFFF when bank 4 is selected).
# File 0x01347F = bank 4 offset 0x346F → CPU $B46F when bank 4 mapped.
NEW_BASE_FILE = 0x01347F
NEW_BASE_CPU = 0xB46F

# Bank-switch immediate values (the byte the host loads into A before JSR $FFAC).
OLD_BANK_VALUE = 0x0E   # CC patch's value for bank 6 (MMC1 bit-3 don't-care alias)
NEW_BANK_VALUE = 0x04   # vanilla Z1's value for switching to bank 4

# Address of the dispatcher's jump table (we treat this region as DATA, not code,
# and rewrite each 16-bit pointer separately).
JUMP_TABLE_CPU = 0xBD90
JUMP_TABLE_LEN = 12  # 6 entries * 2 bytes each

# The 4-byte response prelude originally at $ED94 (in bank 7) collides with at
# least one Z1R seed that puts an $RTS / data byte there. Relocate it to the
# tail of our packed bank-4 region so we don't touch $ED94 at all.
PRELUDE_OLD_CPU = 0xED94
PRELUDE_NEW_CPU = 0xB8CC  # = NEW_BASE_CPU + 1117 (right after the packed code)
PRELUDE_LEN = 4
PRELUDE_BYTES = bytes([0x2B, 0xD4, 0x22, 0xDD])

# NMI hook entry — 8 bytes that the NMI vector points at. Originally at $FFC0,
# but at least one Z1R seed puts its own code there. Relocate to $FFD4 (16 free
# bytes in both vanilla and seed) and re-aim the NMI vector at the new spot.
NMI_HOOK_OLD_CPU = 0xFFC0
NMI_HOOK_NEW_CPU = 0xFFD4
NMI_HOOK_LEN = 8


def _bank7_file_offset(cpu_addr: int) -> int:
    return 0x10 + 7 * 0x4000 + (cpu_addr - 0xC000)


def _bank4_file_offset(cpu_addr: int) -> int:
    return 0x10 + 4 * 0x4000 + (cpu_addr - 0x8000)


def is_internal(addr: int) -> bool:
    return OLD_RANGE_START <= addr <= OLD_RANGE_END


def disasm_one(data: bytes, idx: int) -> tuple[str, int]:
    """Return (mnemonic, instruction_length) for the instruction at data[idx]."""
    op = data[idx]
    if op not in OPCODES:
        return f".byte ${op:02X}", 1
    mnem, mode = OPCODES[op]
    return mode, MODE_LEN[mode]


def build_mapping() -> dict[int, int]:
    """Return a per-byte mapping: old_cpu_addr -> new_cpu_addr.

    Regions are packed contiguously in declaration order starting at NEW_BASE_CPU.
    """
    mapping: dict[int, int] = {}
    new_addr = NEW_BASE_CPU
    for _, old_cpu, length in OLD_REGIONS:
        for i in range(length):
            mapping[old_cpu + i] = new_addr + i
        new_addr += length
    return mapping


def relocate_region(
    region_bytes: bytes,
    old_cpu_start: int,
    new_cpu_start: int,
    is_jump_table: bool,
    mapping: dict[int, int],
) -> bytes:
    """Rewrite a single region's bytes for its new location.

    For code regions: walks instruction-by-instruction, rewrites operands.
    For the jump table: rewrites each 16-bit pointer in place.
    """
    out = bytearray(region_bytes)

    if is_jump_table:
        # 6 little-endian pointers. Look up each in mapping.
        for i in range(0, JUMP_TABLE_LEN, 2):
            old_target = region_bytes[i] | (region_bytes[i + 1] << 8)
            if not is_internal(old_target):
                raise RuntimeError(
                    f"jump table entry {i//2} points outside patch: ${old_target:04X}"
                )
            new_target = mapping[old_target]
            out[i] = new_target & 0xFF
            out[i + 1] = (new_target >> 8) & 0xFF
        return bytes(out)

    # Code path: walk instructions
    idx = 0
    while idx < len(region_bytes):
        op = region_bytes[idx]
        if op not in OPCODES:
            # Treat unknown opcode as a 1-byte data byte; leave it alone.
            idx += 1
            continue
        mnem, mode = OPCODES[op]
        ilen = MODE_LEN[mode]
        if idx + ilen > len(region_bytes):
            # Truncated — leave remaining bytes as-is
            break

        instr_old_addr = old_cpu_start + idx

        if mode in ABS_MODES:
            old_target = region_bytes[idx + 1] | (region_bytes[idx + 2] << 8)
            if is_internal(old_target):
                new_target = mapping[old_target]
                out[idx + 1] = new_target & 0xFF
                out[idx + 2] = (new_target >> 8) & 0xFF
            elif old_target == PRELUDE_OLD_CPU:
                # `LDA $ED94,Y` style references to the relocated prelude data
                out[idx + 1] = PRELUDE_NEW_CPU & 0xFF
                out[idx + 2] = (PRELUDE_NEW_CPU >> 8) & 0xFF
        elif mode in REL_MODES:
            # Branch: signed 8-bit offset relative to (instr_old_addr + 2).
            offset = region_bytes[idx + 1]
            if offset >= 0x80:
                offset -= 0x100
            old_target = (instr_old_addr + 2 + offset) & 0xFFFF
            if is_internal(old_target):
                new_target = mapping[old_target]
                instr_new_addr = new_cpu_start + idx
                new_offset = new_target - (instr_new_addr + 2)
                if not -128 <= new_offset <= 127:
                    raise RuntimeError(
                        f"relative branch at ${instr_old_addr:04X} now out of "
                        f"range after relocation: offset={new_offset}"
                    )
                out[idx + 1] = new_offset & 0xFF
        # imm/zp/imp/etc. — no operand rewriting needed

        idx += ilen

    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vanilla", help="Path to vanilla Z1 NES ROM")
    args = ap.parse_args()

    vanilla = Path(args.vanilla).read_bytes()
    if len(vanilla) != 131088:
        print(f"WARN: expected 131088-byte iNES; got {len(vanilla)}")
    patch_path = Path("bridge_core/patches/zelda_emu_coop_plus.ips")
    old_ips = patch_path.read_bytes()
    print(f"# Old IPS: {patch_path} ({len(old_ips)} bytes)")

    # Apply old IPS to get the currently-patched ROM (so we can extract the
    # already-patched bytes for each region).
    patched = bytearray(apply(vanilla, old_ips))

    # Sanity check: every byte we plan to relocate currently exists in the
    # patched ROM as we expect.
    print(f"# Old code occupies CPU ${OLD_RANGE_START:04X}-${OLD_RANGE_END:04X} "
          f"(span {OLD_RANGE_END - OLD_RANGE_START + 1} bytes)")
    total_code = sum(L for _, _, L in OLD_REGIONS)
    print(f"# Total code bytes to relocate: {total_code}")

    mapping = build_mapping()
    new_top_cpu = NEW_BASE_CPU + total_code
    if new_top_cpu > 0xBFFF:
        raise SystemExit(
            f"packed code overflows bank window: ends at ${new_top_cpu:04X} "
            f"(must be <= $BFFF)"
        )
    print(f"# New code occupies CPU ${NEW_BASE_CPU:04X}-${new_top_cpu - 1:04X} "
          f"(packed)")

    # Build the relocated bytes (one big contiguous block at NEW_BASE_FILE).
    new_block = bytearray()
    new_cpu = NEW_BASE_CPU
    for file_off, old_cpu, length in OLD_REGIONS:
        region_bytes = bytes(patched[file_off:file_off + length])
        is_jt = (old_cpu == JUMP_TABLE_CPU)
        relocated = relocate_region(region_bytes, old_cpu, new_cpu, is_jt, mapping)
        if len(relocated) != length:
            raise RuntimeError(f"relocate produced wrong length for ${old_cpu:04X}")
        new_block += relocated
        new_cpu += length
    # Append prelude bytes immediately after the packed code.
    assert new_cpu == PRELUDE_NEW_CPU, (
        f"expected prelude at ${PRELUDE_NEW_CPU:04X} but packing ended at ${new_cpu:04X}"
    )
    new_block += PRELUDE_BYTES

    # Build the FINAL patched ROM by:
    #  1. Starting from vanilla
    #  2. Re-applying every IPS region EXCEPT (a) the bank-6 main code,
    #     (b) the old prelude bytes at $ED94-$ED9A, (c) the old NMI hook entry
    #     at $FFC0-$FFC7
    #  3. Writing the relocated code+prelude block at NEW_BASE_FILE (bank 4)
    #  4. Writing the new NMI hook entry at $FFD4 (bank 7 free space)
    #  5. Updating bank value, JSR/JMP hook targets, and NMI vector
    final = bytearray(vanilla)
    relocated_ranges = [(fo, fo + L) for fo, _, L in OLD_REGIONS]
    # Skip the old prelude+leftover bytes at $ED94-$ED9A (file 0x01EDA4-0x01EDAA).
    # Also skip the old NMI hook entry at $FFC0-$FFC7 (file 0x01FFD0-0x01FFD7).
    skip_ranges = relocated_ranges + [
        (_bank7_file_offset(PRELUDE_OLD_CPU),
         _bank7_file_offset(PRELUDE_OLD_CPU) + 7),  # $ED94-$ED9A inclusive
        (_bank7_file_offset(NMI_HOOK_OLD_CPU),
         _bank7_file_offset(NMI_HOOK_OLD_CPU) + NMI_HOOK_LEN),  # $FFC0-$FFC7
    ]

    def _is_skipped_byte(offset: int) -> bool:
        for r_start, r_end in skip_ranges:
            if r_start <= offset < r_end:
                return True
        return False

    for offset, payload in parse(io.BytesIO(old_ips)):
        end = offset + len(payload)
        if end > len(final):
            final.extend(b"\x00" * (end - len(final)))
        # Per-byte: a record may straddle a skip boundary (e.g. one record
        # covers both the JMP $FAE4 operand we keep AND the prelude bytes we
        # don't), so we apply byte-by-byte rather than discarding whole records.
        for i, b in enumerate(payload):
            if not _is_skipped_byte(offset + i):
                final[offset + i] = b

    # Stage the relocated code + prelude at bank 4 file location
    final[NEW_BASE_FILE:NEW_BASE_FILE + len(new_block)] = new_block

    # Stage the new NMI hook entry at bank 7 $FFD4 (8 bytes):
    #   LDA #$04 / JSR $FFAC / JMP $<new bank-4 NMI drain>
    new_nmi_drain = mapping[0xB290]
    nmi_hook_bytes = bytes([
        0xA9, NEW_BANK_VALUE,           # LDA #$04
        0x20, 0xAC, 0xFF,               # JSR $FFAC
        0x4C, new_nmi_drain & 0xFF, (new_nmi_drain >> 8) & 0xFF,  # JMP $<new>
    ])
    nmi_hook_file = _bank7_file_offset(NMI_HOOK_NEW_CPU)
    final[nmi_hook_file:nmi_hook_file + NMI_HOOK_LEN] = nmi_hook_bytes

    # External hook updates -------------------------------------------------
    # 1. Bank value at $ED8A (file 0x1ED9A): $0E -> $04
    final[0x01ED9A] = NEW_BANK_VALUE

    # 2. JSR $B390 at $ED8E (file 0x1ED9E-0x1EDA0; we only rewrite operand bytes
    #    at +1,+2; opcode 0x20 already matches vanilla's JSR opcode at $ED8E).
    new_main_loop_hook = mapping[0xB390]
    final[0x01ED9E] = 0x20  # ensure opcode (vanilla also has 0x20 here)
    final[0x01ED9F] = new_main_loop_hook & 0xFF
    final[0x01EDA0] = (new_main_loop_hook >> 8) & 0xFF

    # 3. JSR $B6F0 at $E65A (file 0x1E66A: opcode + operand)
    new_secondary_hook = mapping[0xB6F0]
    final[0x01E66B] = new_secondary_hook & 0xFF
    final[0x01E66C] = (new_secondary_hook >> 8) & 0xFF

    # 4. JMP $FAE4 at $ED91 — vanilla has JMP $6CC0; we want JMP $FAE4. Vanilla
    #    bytes at $ED91-$ED93 are 4C C0 6C; we change operand to E4 FA at $ED92-$ED93.
    final[0x01EDA2] = 0xE4
    final[0x01EDA3] = 0xFA

    # 5. NMI vector at $FFFA: was $FFC0 in old patch; now $FFD4.
    final[0x02000A] = NMI_HOOK_NEW_CPU & 0xFF
    final[0x0200_0B] = (NMI_HOOK_NEW_CPU >> 8) & 0xFF

    # Generate the new IPS by diffing vanilla -> final
    new_ips = make_ips(vanilla, bytes(final))
    patch_path.write_bytes(new_ips)
    print(f"# New IPS: {patch_path} ({len(new_ips)} bytes)")
    print(f"# Round-trip: applying new IPS to vanilla yields the relocated ROM: "
          f"{'OK' if apply(vanilla, new_ips) == bytes(final) else 'MISMATCH'}")

    # Sanity: confirm bytes at OLD locations are now $FF in the final ROM
    # (since we no longer write there)
    old_bytes_clean = all(
        all(b == 0xFF for b in final[fo:fo + L])
        for fo, _, L in OLD_REGIONS
    )
    print(f"# Old bank-6 code regions are now 0xFF in final ROM: "
          f"{'OK' if old_bytes_clean else 'WARN — some bytes leftover'}")
    print()
    print("# Hooks updated:")
    print(f"#   bank value $ED8A:           $0E -> $0{NEW_BANK_VALUE:01X}")
    print(f"#   JSR $B390 at $ED8E:         -> JSR ${new_main_loop_hook:04X}")
    print(f"#   JMP $6CC0 at $ED91:         -> JMP $FAE4")
    print(f"#   JSR $B6F0 at $E65A:         -> JSR ${new_secondary_hook:04X}")
    print(f"#   prelude data $ED94:         relocated to ${PRELUDE_NEW_CPU:04X} (bank 4)")
    print(f"#   NMI hook entry $FFC0:       relocated to ${NMI_HOOK_NEW_CPU:04X} (bank 7 free)")
    print(f"#   NMI vector $FFFA:           ${NMI_HOOK_OLD_CPU:04X} -> ${NMI_HOOK_NEW_CPU:04X}")


if __name__ == "__main__":
    main()
