"""One-shot CC capability audit (production-shaped workloads).

Usage: python audit_cc_capabilities.py --port COM5 [--baud 115200]

Tests the actual sustained workloads the bridge will need:
  1. Memory region accessibility: 16-byte probes at scattered addresses
  2. Tier 1 (running flag): 30s @ 10Hz x 1 byte
  3. Tier 2 (inventory chunk): 30s @ 5Hz x 8 bytes
  4. Tier 3 (inventory full): 30s @ 2Hz x 32 bytes
  5. Tier 4 (map chunk): 30s @ 0.5Hz x 128 bytes
  6. Mixed multi-tier: 60s simulating real bridge polling pattern

Auto-aborts a phase if 10 consecutive timeouts (game crashed in cart).
2-second pause + liveness probe between phases.
"""
import argparse
import time

import serial

ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B

ABORT_AFTER_CONSECUTIVE_TIMEOUTS = 10


def make_header(cmd: int) -> bytes:
    return bytes([P, P ^ 0xFF, cmd & 0xFF, (cmd ^ 0xFF) & 0xFF])


def u32le(v: int) -> bytes:
    return bytes([(v >> 0) & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])


def usb_mem_wr(sp: serial.Serial, addr: int, data: bytes) -> None:
    sp.write(make_header(CMD_MEM_WR))
    sp.write(u32le(addr))
    sp.write(u32le(len(data)))
    sp.write(b"\x00")
    sp.write(data)


def fr_len(mid: int, action: int, payload: bytes) -> bytes:
    body = bytes((mid & 0xFF, action & 0xFF)) + payload
    return bytes((1 + len(body),)) + body


def fr_read_array(mid: int, base: int, n: int) -> bytes:
    return fr_len(mid, 0x01, bytes((n & 0xFF, base & 0xFF, (base >> 8) & 0xFF)))


def fr_return(mid: int) -> bytes:
    return fr_len(mid, 0x05, b"\x00")


def strip_status_pairs(b: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(b):
        if i + 1 < len(b) and b[i] in (0x00, 0x04) and b[i + 1] == 0xA5:
            i += 2
            continue
        out.append(b[i])
        i += 1
    return bytes(out)


def time_one_read(sp: serial.Serial, mid: int, base: int, n: int, timeout_ms: int = 200) -> float | None:
    """Returns elapsed milliseconds for one read-array, or None if timed out."""
    t0 = time.perf_counter()
    usb_mem_wr(sp, ADDR_FIFO, fr_read_array(mid, base, n))
    time.sleep(0.005)
    usb_mem_wr(sp, ADDR_FIFO, fr_return(mid))
    deadline = time.perf_counter() + timeout_ms / 1000.0
    raw = bytearray()
    while time.perf_counter() < deadline:
        bytes_in = sp.in_waiting
        if bytes_in:
            raw += sp.read(bytes_in)
        filt = strip_status_pairs(bytes(raw))
        for i in range(len(filt) - 3):
            if filt[i] == 0x20 and filt[i + 1] == (mid & 0xFF) and filt[i + 2] in (0x01, 0x00):
                if i + 3 + n <= len(filt):
                    return (time.perf_counter() - t0) * 1000.0
        time.sleep(0.001)
    return None


def is_cart_alive(sp: serial.Serial) -> bool:
    """3 consecutive successful 1-byte reads = game is processing CC frames."""
    for _ in range(3):
        t = time_one_read(sp, 1, 0x0000, 1, timeout_ms=300)
        if t is None:
            return False
        time.sleep(0.05)
    return True


def test_memory_regions(sp: serial.Serial) -> None:
    print("\n## Memory region accessibility (16-byte reads, isolated)")
    print("\n| Region | Range | Reads OK? | Latency |")
    print("|---|---|---|---|")
    for name, base, size in [
        ("RAM low", 0x0000, 16),
        ("RAM mid", 0x0400, 16),
        ("RAM high", 0x0700, 16),
        ("RAM end", 0x07F0, 16),
        ("Cart SRAM start", 0x6000, 16),
        ("Cart SRAM mid", 0x7000, 16),
        ("Cart ROM low", 0x8000, 16),
    ]:
        t = time_one_read(sp, 1, base, size, timeout_ms=300)
        ok = "OK" if t is not None else "FAIL"
        detail = f"{t:.1f}ms" if t is not None else "timeout"
        print(f"| {name} | 0x{base:04X}+{size}b | {ok} | {detail} |")
        time.sleep(0.05)


def sustained_test(sp: serial.Serial, label: str, base: int, size: int, hz: float, duration_s: int) -> tuple[int, int, bool]:
    """Run a sustained polling pattern. Returns (success, timeouts, aborted)."""
    period = 1.0 / hz
    deadline = time.time() + duration_s
    success = 0
    timeouts = 0
    consec = 0
    aborted = False
    mid = 1
    timeout_per_read = max(50, int(period * 1000 * 0.7))
    while time.time() < deadline:
        loop_start = time.time()
        t = time_one_read(sp, mid, base, size, timeout_ms=timeout_per_read)
        if t is None:
            timeouts += 1
            consec += 1
            if consec >= ABORT_AFTER_CONSECUTIVE_TIMEOUTS:
                aborted = True
                break
        else:
            success += 1
            consec = 0
        mid = (mid + 1) & 0xFF
        if mid == 0:
            mid = 1
        elapsed = time.time() - loop_start
        sleep = period - elapsed
        if sleep > 0:
            time.sleep(sleep)
    return success, timeouts, aborted


def run_phase(sp: serial.Serial, name: str, base: int, size: int, hz: float, duration_s: int) -> bool:
    """Run one sustained phase, print result. Returns False on abort."""
    if not is_cart_alive(sp):
        print(f"\n*Skipping {name}: cart silent before phase started.*")
        return False
    success, timeouts, aborted = sustained_test(sp, name, base, size, hz, duration_s)
    actual_hz = success / duration_s if duration_s > 0 else 0.0
    tag = " (aborted - cart silent)" if aborted else ""
    print(f"| {name} | {hz} Hz | {size} | {duration_s}s | {success} | {timeouts} | {actual_hz:.1f} Hz{tag} |")
    return not aborted


def test_tiers(sp: serial.Serial) -> bool:
    print("\n## Production-shaped sustained workloads")
    print("\n| Tier | Target Hz | Bytes/poll | Duration | Successes | Timeouts | Actual Hz |")
    print("|---|---|---|---|---|---|---|")
    if not run_phase(sp, "Tier 1 (running flag)",   0x0000, 1,   10.0, 30):
        return False
    time.sleep(2)
    if not run_phase(sp, "Tier 2 (small chunk)",    0x0657, 8,   5.0, 30):
        return False
    time.sleep(2)
    if not run_phase(sp, "Tier 3 (inventory)",      0x0657, 32,  2.0, 30):
        return False
    time.sleep(2)
    if not run_phase(sp, "Tier 4 (map chunk)",      0x067F, 128, 0.5, 30):
        return False
    return True


def test_mixed_multitier(sp: serial.Serial) -> None:
    """Simulate a realistic bridge polling pattern: rapid small reads + occasional large."""
    print("\n## Mixed multi-tier (60s realistic bridge pattern)")
    if not is_cart_alive(sp):
        print("\n*Skipping mixed phase: cart silent.*")
        return
    deadline = time.time() + 60
    last_inv = 0.0
    last_map = 0.0
    success = 0
    timeouts = 0
    consec = 0
    aborted = False
    mid = 1
    while time.time() < deadline:
        loop_start = time.time()
        # Always: running flag (1 byte)
        t = time_one_read(sp, mid, 0x0000, 1, timeout_ms=80)
        mid = (mid + 1) & 0xFF or 1
        if t is None:
            timeouts += 1; consec += 1
        else:
            success += 1; consec = 0
        # Every 500ms: inventory chunk (32 bytes)
        if loop_start - last_inv >= 0.5:
            t = time_one_read(sp, mid, 0x0657, 32, timeout_ms=120)
            mid = (mid + 1) & 0xFF or 1
            if t is None:
                timeouts += 1; consec += 1
            else:
                success += 1; consec = 0
            last_inv = loop_start
        # Every 2s: map chunk (128 bytes)
        if loop_start - last_map >= 2.0:
            t = time_one_read(sp, mid, 0x067F, 128, timeout_ms=400)
            mid = (mid + 1) & 0xFF or 1
            if t is None:
                timeouts += 1; consec += 1
            else:
                success += 1; consec = 0
            last_map = loop_start
        if consec >= ABORT_AFTER_CONSECUTIVE_TIMEOUTS:
            aborted = True
            break
        elapsed = time.time() - loop_start
        sleep = 0.1 - elapsed
        if sleep > 0:
            time.sleep(sleep)
    total = success + timeouts
    fail_pct = (100 * timeouts / total) if total else 0.0
    tag = " (aborted - cart silent)" if aborted else ""
    print(f"\nResults: {success} successes / {timeouts} timeouts (failure {fail_pct:.1f}%){tag}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    print(f"# EDN8 CC capability audit (production-shaped)")
    print(f"\nPort: {args.port}, baud: {args.baud}")
    print(f"Run at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n## Setup")
    print("- Cart: <fill in: model + firmware version>")
    print("- ROM: <fill in: vanilla Z1 or Z1R seed + CC patch>")
    print("- Game state: <fill in: title screen / overworld / paused>")

    test_memory_regions(sp)
    time.sleep(2)
    if test_tiers(sp):
        time.sleep(2)
        test_mixed_multitier(sp)

    print("\n## Conclusions")
    print("- (Fill in observations: which tiers survived, recommended bridge polling architecture.)")


if __name__ == "__main__":
    main()
