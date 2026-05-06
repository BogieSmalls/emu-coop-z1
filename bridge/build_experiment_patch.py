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


EXPERIMENTS = {
    "h1_no_b58d": experiment_h1_no_b58d,
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
