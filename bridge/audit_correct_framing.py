"""Diagnostic with correct CC framing (matches Crowd Control's official client).

Two fixes vs. the old audit scripts:
  1. Each frame ends with a 1-byte checksum: sum(body_bytes) mod 256.
  2. We send ONE frame per request (no separate action 0x05 'Return' frame).

If our prior 97-transaction crash was caused by the cart reading one extra byte
per frame from the FIFO (because our L was off by one due to the missing
checksum), running with correct framing should let us blow past 97 reads.

Usage:
    python audit_correct_framing.py --port COM5 [--reads 200] [--interval 0.1]
"""
import argparse
import time

import serial

ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B


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


def cc_frame(mid: int, action: int, payload: bytes) -> bytes:
    """Build a CC frame matching the official client:
       [L, mid, action, ...payload, checksum]
       where L = body length including checksum, checksum = sum(body bytes without L) mod 256."""
    body = bytes((mid & 0xFF, action & 0xFF)) + payload
    checksum = sum(body) & 0xFF
    body_with_checksum = body + bytes((checksum,))
    L = len(body_with_checksum)
    return bytes((L,)) + body_with_checksum


def cc_read_individual(mid: int, addr: int, count: int = 1) -> bytes:
    """Action 0x00 = Read individual addresses (matches CC client's Read8)."""
    payload = bytes((count & 0xFF, addr & 0xFF, (addr >> 8) & 0xFF))
    return cc_frame(mid, 0x00, payload)


def cc_array_read(mid: int, base: int, n: int) -> bytes:
    """Action 0x01 = Array read."""
    payload = bytes((n & 0xFF, base & 0xFF, (base >> 8) & 0xFF))
    return cc_frame(mid, 0x01, payload)


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


def time_one_read(sp: serial.Serial, mid: int, addr: int, n: int, timeout_ms: int = 200) -> float | None:
    """Send one Action 0x01 frame, wait for response. No Return frame.

    Response format (per cart's handler at $BB90 for Action 0x01):
        prelude [2B D4 22 DD] + size(N+3) + 0x00 + 0x20 + mid + action + N data bytes
    """
    t0 = time.perf_counter()
    usb_mem_wr(sp, ADDR_FIFO, cc_array_read(mid, addr, n))
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reads", type=int, default=200)
    ap.add_argument("--interval", type=float, default=0.1,
                    help="seconds between reads (default 0.1 = 10 Hz)")
    ap.add_argument("--timeout-ms", type=int, default=200)
    args = ap.parse_args()

    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    print(f"# Correct-framing diagnostic (with checksum, no Return frame)")
    print(f"# Port: {args.port}, baud: {args.baud}")
    print(f"# Plan: {args.reads} reads at one every {args.interval}s = {args.reads * args.interval:.0f}s wallclock")
    print(f"# Bypassing the 97-transaction crash threshold is the goal.")
    print()
    print("read#  wallclock(s)  result    latency(ms)")
    print("-----  ------------  --------  -----------")

    t_start = time.time()
    successes = 0
    timeouts = 0
    consec_timeouts = 0
    for i in range(1, args.reads + 1):
        target_t = t_start + (i - 1) * args.interval
        wait = target_t - time.time()
        if wait > 0:
            time.sleep(wait)
        wallclock = time.time() - t_start
        mid = ((i - 1) % 254) + 1
        latency = time_one_read(sp, mid, 0x0000, 1, args.timeout_ms)
        if latency is None:
            print(f"{i:5d}  {wallclock:12.2f}  TIMEOUT   -")
            timeouts += 1
            consec_timeouts += 1
            if consec_timeouts >= 15:
                print(f"\n# ABORTED after 15 consecutive timeouts (cart silent).")
                print(f"# Last successful read: #{i - consec_timeouts}")
                break
        else:
            print(f"{i:5d}  {wallclock:12.2f}  OK        {latency:6.1f}")
            successes += 1
            consec_timeouts = 0

    total_t = time.time() - t_start
    print()
    print(f"# Summary: {successes} successes / {timeouts} timeouts in {total_t:.1f}s")
    if successes >= 150:
        print(f"# RESULT: Blew past the 97 threshold cleanly. Checksum framing is the fix.")
    elif 90 <= successes <= 110:
        print(f"# RESULT: Still hitting ~97 threshold. Checksum is not (or not the only) cause.")
    else:
        print(f"# RESULT: Different threshold than before. Investigate further.")


if __name__ == "__main__":
    main()
