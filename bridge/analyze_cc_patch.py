"""Analyze the CC patch by comparing pre- and post-patched Z1 ROMs.

Reads the original ROM + the IPS, applies the patch in memory, then for each
modified region dumps original vs patched bytes and disassembles the patched
region as 6502 assembly.

Includes a minimal 6502 disassembler (no external deps).

Usage:
  python analyze_cc_patch.py <orig.nes> [<patch.ips>]
  (defaults to bridge_core/patches/zelda_z1rr_coop.ips for the IPS)
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from bridge_core.ips import apply, parse


# --- 6502 disassembler ---
# Each entry: (mnemonic, mode) where mode is one of:
#   "imp"  - implied (no operand)
#   "imm"  - immediate (#$nn)
#   "zp"   - zero page ($nn)
#   "zpx"  - zero page + X ($nn,X)
#   "zpy"  - zero page + Y ($nn,Y)
#   "abs"  - absolute ($nnnn)
#   "absx" - absolute + X ($nnnn,X)
#   "absy" - absolute + Y ($nnnn,Y)
#   "ind"  - indirect ($nnnn)
#   "indx" - (zp,X)
#   "indy" - (zp),Y
#   "rel"  - relative branch (signed byte)
#   "acc"  - accumulator (A)

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


def disasm_one(data: bytes, idx: int, pc: int) -> tuple[str, int]:
    """Disassemble one instruction; return (line, length)."""
    op = data[idx]
    if op not in OPCODES:
        return (f".byte ${op:02X}        ; (unknown)", 1)
    mnem, mode = OPCODES[op]
    n = MODE_LEN[mode]
    if idx + n > len(data):
        return (f".byte ${op:02X}        ; (truncated)", 1)
    bytes_str = " ".join(f"{b:02X}" for b in data[idx:idx + n])

    if mode == "imp" or mode == "acc":
        operand = "" if mode == "imp" else "A"
    elif mode == "imm":
        operand = f"#${data[idx + 1]:02X}"
    elif mode == "zp":
        operand = f"${data[idx + 1]:02X}"
    elif mode == "zpx":
        operand = f"${data[idx + 1]:02X},X"
    elif mode == "zpy":
        operand = f"${data[idx + 1]:02X},Y"
    elif mode == "rel":
        # signed offset, target = pc + 2 + offset
        off = data[idx + 1]
        if off >= 0x80:
            off -= 0x100
        target = (pc + 2 + off) & 0xFFFF
        operand = f"${target:04X}"
    elif mode == "indx":
        operand = f"(${data[idx + 1]:02X},X)"
    elif mode == "indy":
        operand = f"(${data[idx + 1]:02X}),Y"
    elif mode == "abs":
        addr = data[idx + 1] | (data[idx + 2] << 8)
        operand = f"${addr:04X}"
    elif mode == "absx":
        addr = data[idx + 1] | (data[idx + 2] << 8)
        operand = f"${addr:04X},X"
    elif mode == "absy":
        addr = data[idx + 1] | (data[idx + 2] << 8)
        operand = f"${addr:04X},Y"
    elif mode == "ind":
        addr = data[idx + 1] | (data[idx + 2] << 8)
        operand = f"(${addr:04X})"
    else:
        operand = ""
    line = f"{bytes_str:<10}  {mnem} {operand}".rstrip()
    return line, n


def disasm_block(data: bytes, file_offset: int, cpu_origin: int) -> list[str]:
    """Disassemble a block, prefixing each line with CPU address."""
    out = []
    idx = 0
    pc = cpu_origin
    while idx < len(data):
        line, n = disasm_one(data, idx, pc)
        out.append(f"{pc:04X}:  {line}")
        idx += n
        pc += n
    return out


def file_offset_to_cpu(file_offset: int, header_len: int = 16) -> tuple[int, int]:
    """Map a file offset to (bank_num, cpu_addr) for an MMC1-mapped Z1 ROM.

    Z1 has 8 PRG banks of 16KB each. MMC1 banks 0-6 are switchable into
    $8000-$BFFF; bank 7 is fixed at $C000-$FFFF.
    """
    o = file_offset - header_len
    bank = o // 0x4000
    bank_off = o % 0x4000
    if bank == 7:
        cpu = 0xC000 + bank_off  # fixed bank
    else:
        cpu = 0x8000 + bank_off  # switched bank, conventionally 0x8000-0xBFFF
    return bank, cpu


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("orig_rom")
    ap.add_argument("ips", nargs="?", default="bridge_core/patches/zelda_z1rr_coop.ips")
    ap.add_argument("--region", help="only disassemble this region (hex offset)")
    ap.add_argument("--no-disasm", action="store_true", help="just print bytes")
    args = ap.parse_args()

    orig = Path(args.orig_rom).read_bytes()
    patch = Path(args.ips).read_bytes()
    patched = apply(orig, patch)
    print(f"# Original ROM: {args.orig_rom} ({len(orig)} bytes)")
    print(f"# Patch:        {args.ips} ({len(patch)} bytes)")
    print(f"# Patched size: {len(patched)} bytes")
    print()

    # Read NMI/Reset/IRQ vectors from patched ROM (file offsets 0x2000A-0x2000F,
    # which correspond to CPU $FFFA-$FFFF in bank 7 plus the iNES 16-byte header)
    if len(patched) >= 0x20010:
        nmi = patched[0x2000A] | (patched[0x2000B] << 8)
        reset = patched[0x2000C] | (patched[0x2000D] << 8)
        irq = patched[0x2000E] | (patched[0x2000F] << 8)
        orig_nmi = orig[0x2000A] | (orig[0x2000B] << 8)
        orig_reset = orig[0x2000C] | (orig[0x2000D] << 8)
        orig_irq = orig[0x2000E] | (orig[0x2000F] << 8)
        print("# Interrupt vectors:")
        print(f"#   NMI:   ${nmi:04X}  (was ${orig_nmi:04X})")
        print(f"#   RESET: ${reset:04X}  (was ${orig_reset:04X})")
        print(f"#   IRQ:   ${irq:04X}  (was ${orig_irq:04X})")
        print()

    regions = list(parse(io.BytesIO(patch)))
    target = int(args.region, 16) if args.region else None

    for offset, payload in regions:
        if target is not None and offset != target:
            continue
        bank, cpu = file_offset_to_cpu(offset)
        print(f"\n## Region 0x{offset:06X} (bank {bank}, CPU ${cpu:04X}, {len(payload)} bytes)")
        orig_slice = orig[offset:offset + len(payload)]
        # Show original bytes for context
        all_zero_or_ff = all(b in (0, 0xFF) for b in orig_slice)
        if all_zero_or_ff:
            print(f"   (original was all 0x{orig_slice[0]:02X} - empty/free space)")
        else:
            ow = " ".join(f"{b:02X}" for b in orig_slice[:32])
            print(f"   orig: {ow}{'...' if len(orig_slice) > 32 else ''}")
        if not args.no_disasm:
            for line in disasm_block(payload, offset, cpu):
                print(f"   {line}")
        else:
            for i in range(0, len(payload), 16):
                bh = " ".join(f"{b:02X}" for b in payload[i:i + 16])
                print(f"   +{i:03X}: {bh}")


if __name__ == "__main__":
    main()
