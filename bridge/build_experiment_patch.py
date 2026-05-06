"""Build experimental modifications to the CC patch and emit a new IPS + ROM.

Usage:
  python build_experiment_patch.py <orig.nes> --experiment h1_no_b58d \\
      [--out-ips path.ips] [--out-rom path.nes]

Available experiments:
  h1_no_b58d   Hypothesis 1: NOP out the always-called JSR $B58D at $B39F
               in the main-loop hook. If the game survives sustained polling
               with this change, the always-called helper is the culprit.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bridge_core.ips import apply
from bridge_core.ips_build import make_ips


def _bank6_file_offset(cpu_addr: int, header_len: int = 16) -> int:
    """Map a CPU address in bank 6 ($8000-$BFFF when bank 6 is swapped in)
    to its file offset in the standard 8-bank Z1 ROM."""
    if not (0x8000 <= cpu_addr <= 0xBFFF):
        raise ValueError(f"${cpu_addr:04X} is not in the bank-6 swap window")
    bank_off = cpu_addr - 0x8000
    return header_len + 6 * 0x4000 + bank_off


def _bank7_file_offset(cpu_addr: int, header_len: int = 16) -> int:
    """Map a CPU address in bank 7 (fixed at $C000-$FFFF)."""
    if not (0xC000 <= cpu_addr <= 0xFFFF):
        raise ValueError(f"${cpu_addr:04X} is not in the bank-7 fixed window")
    return header_len + 7 * 0x4000 + (cpu_addr - 0xC000)


# --- Experiment definitions ---

def experiment_h1_no_b58d(rom: bytearray) -> list[tuple[int, bytes, bytes]]:
    """Replace `JSR $B58D` (3 bytes at $B39F, file 0x1B3AF) with three NOPs.

    Returns: list of (file_offset, expected_old_bytes, new_bytes) tuples
             for verification + display.
    """
    target_addr = 0xB39F
    file_off = _bank6_file_offset(target_addr)
    expected = b"\x20\x8D\xB5"  # JSR $B58D
    actual = bytes(rom[file_off:file_off + 3])
    if actual != expected:
        raise RuntimeError(
            f"Sanity check failed at $B39F (file 0x{file_off:X}): "
            f"expected {expected.hex()}, got {actual.hex()}. "
            "Patched ROM doesn't look like our zelda_cc baseline."
        )
    new = b"\xEA\xEA\xEA"  # NOP NOP NOP
    rom[file_off:file_off + 3] = new
    return [(file_off, expected, new)]


def experiment_h2_save_regs(rom: bytearray) -> list[tuple[int, bytes, bytes]]:
    """Hypothesis 2: NMI hook clobbers A/X/Y before Z1's original NMI handler
    at $E484 can save them, corrupting main-code state on every NMI.

    Fix:
    - Prepend `PHA / TXA / PHA / TYA / PHA` to the NMI hook at $FFC0 (extends
      the 8-byte hook to 13 bytes, into free space at $FFC8-$FFCC).
    - Add a register-restore wrapper at $FFCD (8 bytes, free space): pops Y/X/A,
      then jumps to original $E484.
    - Redirect bank-6 JMP $E484 (at $B2B3) to JMP $FFCD instead.
    """
    changes = []

    # Step 1: extended NMI hook at $FFC0 (file 0x1FFD0)
    file_off = 0x1FFD0
    expected = b"\xA9\x0E\x20\xAC\xFF\x4C\x90\xB2"  # original 8-byte hook
    actual = bytes(rom[file_off:file_off + 8])
    if actual != expected:
        raise RuntimeError(
            f"Sanity check failed at $FFC0 (file 0x{file_off:X}): "
            f"expected {expected.hex()}, got {actual.hex()}"
        )
    new = bytes([
        0x48,                     # PHA       (save A)
        0x8A, 0x48,               # TXA / PHA (save X)
        0x98, 0x48,               # TYA / PHA (save Y)
        0xA9, 0x0E,               # LDA #$0E
        0x20, 0xAC, 0xFF,         # JSR $FFAC
        0x4C, 0x90, 0xB2,         # JMP $B290
    ])  # 13 bytes
    # Verify the extra 5 bytes we'll occupy are free (FF)
    extra = bytes(rom[file_off + 8:file_off + 13])
    if extra != b"\xFF" * 5:
        raise RuntimeError(
            f"Free-space check failed at $FFC8 (file 0x{file_off + 8:X}): "
            f"expected FF*5, got {extra.hex()}"
        )
    rom[file_off:file_off + 13] = new
    changes.append((file_off, expected + extra, new))

    # Step 2: register-restore wrapper at $FFCD (file 0x1FFDD)
    file_off = 0x1FFDD
    expected = b"\xFF" * 8
    actual = bytes(rom[file_off:file_off + 8])
    if actual != expected:
        raise RuntimeError(
            f"Free-space check failed at $FFCD (file 0x{file_off:X}): "
            f"expected FF*8, got {actual.hex()}"
        )
    new = bytes([
        0x68,                     # PLA
        0xA8,                     # TAY  (restore Y)
        0x68,                     # PLA
        0xAA,                     # TAX  (restore X)
        0x68,                     # PLA  (restore A)
        0x4C, 0x84, 0xE4,         # JMP $E484
    ])  # 8 bytes
    rom[file_off:file_off + 8] = new
    changes.append((file_off, expected, new))

    # Step 3: redirect JMP $E484 in bank-6 NMI-drain to JMP $FFCD
    # $B2B3 in bank 6 = file 0x1B2C3
    file_off = 0x1B2C3
    expected = b"\x4C\x84\xE4"  # JMP $E484
    actual = bytes(rom[file_off:file_off + 3])
    if actual != expected:
        raise RuntimeError(
            f"Sanity check failed at $B2B3 (file 0x{file_off:X}): "
            f"expected {expected.hex()}, got {actual.hex()}"
        )
    new = b"\x4C\xCD\xFF"  # JMP $FFCD
    rom[file_off:file_off + 3] = new
    changes.append((file_off, expected, new))

    return changes


EXPERIMENTS = {
    "h1_no_b58d": experiment_h1_no_b58d,
    "h2_save_regs": experiment_h2_save_regs,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("orig_rom")
    ap.add_argument("--experiment", required=True, choices=sorted(EXPERIMENTS))
    ap.add_argument("--base-ips", default="bridge_core/patches/zelda_cc.ips",
                    help="baseline CC patch to start from")
    ap.add_argument("--out-ips", help="output IPS path (default: <experiment>.ips)")
    ap.add_argument("--out-rom", help="output patched .nes path (default: <experiment>.nes)")
    args = ap.parse_args()

    orig = Path(args.orig_rom).read_bytes()
    base_patch = Path(args.base_ips).read_bytes()
    rom = bytearray(apply(orig, base_patch))
    print(f"# Loaded orig ROM ({len(orig)} bytes) + baseline IPS ({len(base_patch)} bytes)")
    print(f"# Patched baseline ROM size: {len(rom)} bytes")
    print()

    print(f"# Applying experiment: {args.experiment}")
    fn = EXPERIMENTS[args.experiment]
    changes = fn(rom)
    for file_off, before, after in changes:
        cpu = 0x8000 + (file_off - 16 - 6 * 0x4000) if (16 + 6 * 0x4000) <= file_off < (16 + 7 * 0x4000) else None
        cpu_str = f" (CPU ${cpu:04X})" if cpu is not None else ""
        print(f"#   file 0x{file_off:06X}{cpu_str}: {before.hex(' ')} -> {after.hex(' ')}")
    print()

    new_ips_bytes = make_ips(orig, bytes(rom))
    default_dir = Path("dist") / args.experiment
    default_dir.mkdir(parents=True, exist_ok=True)
    out_ips = Path(args.out_ips or default_dir / "zelda_cc.ips")
    out_rom = Path(args.out_rom or default_dir / "zelda_cc.nes")
    out_ips.write_bytes(new_ips_bytes)
    out_rom.write_bytes(bytes(rom))

    print(f"# Wrote {out_ips} ({len(new_ips_bytes)} bytes)")
    print(f"# Wrote {out_rom} ({len(rom)} bytes)")
    print()
    print("# Verification: round-trip apply(orig, new_ips) == new_rom?")
    roundtrip = apply(orig, new_ips_bytes)
    print(f"#   {'OK' if roundtrip == bytes(rom) else 'MISMATCH'}")


if __name__ == "__main__":
    main()
