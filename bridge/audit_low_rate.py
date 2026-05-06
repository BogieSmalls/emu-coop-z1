"""Low-rate diagnostic: test whether the CC patch crash is count-based or time-based.

Sends N reads at a fixed inter-read interval. Aborts on 5 consecutive timeouts.
Prints a per-read line so we can see exactly when failure starts.

Usage:
    python audit_low_rate.py --port COM5 [--reads 30] [--interval 2.0] [--bytes 1]

Comparison:
    - High-rate audit (10 Hz x 1 byte): always crashes at exactly read #97
    - This script at --reads 30 --interval 2.0:  60 sec wallclock, 30 messages
        - If completes successfully -> rate/time matters (game can rest between reads)
        - If crashes at read N < 30 -> count-based bug, threshold below 30
        - If crashes at the same wallclock time (~10s) -> time-based, regardless of count
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


def time_one_read(sp: serial.Serial, mid: int, base: int, n: int, timeout_ms: int) -> float | None:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reads", type=int, default=30)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="seconds between reads (default 2.0 = 0.5 Hz)")
    ap.add_argument("--bytes", type=int, default=1, help="bytes per read")
    ap.add_argument("--timeout-ms", type=int, default=200)
    args = ap.parse_args()

    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    print(f"# Low-rate diagnostic")
    print(f"# Port: {args.port}, baud: {args.baud}")
    print(f"# Plan: {args.reads} reads, {args.interval}s apart, {args.bytes} byte each")
    print(f"# Total wallclock target: {args.reads * args.interval:.0f}s")
    print(f"# Timeout per read: {args.timeout_ms}ms")
    print()
    print("read#  wallclock(s)  result    latency(ms)")
    print("-----  ------------  --------  -----------")

    t_start = time.time()
    consec_timeouts = 0
    successes = 0
    timeouts = 0
    for i in range(1, args.reads + 1):
        target_t = t_start + (i - 1) * args.interval
        wait = target_t - time.time()
        if wait > 0:
            time.sleep(wait)
        wallclock = time.time() - t_start
        mid = ((i - 1) % 255) + 1
        latency = time_one_read(sp, mid, 0x0000, args.bytes, args.timeout_ms)
        if latency is None:
            print(f"{i:5d}  {wallclock:12.2f}  TIMEOUT   -")
            timeouts += 1
            consec_timeouts += 1
            if consec_timeouts >= 5:
                print(f"\n# ABORTED after 5 consecutive timeouts (cart silent).")
                print(f"# Last successful read: #{i - consec_timeouts} at t={t_start + (i - consec_timeouts - 1) * args.interval - t_start:.2f}s")
                break
        else:
            print(f"{i:5d}  {wallclock:12.2f}  OK        {latency:6.1f}")
            successes += 1
            consec_timeouts = 0

    total_t = time.time() - t_start
    aborted = consec_timeouts >= 5
    print()
    print(f"# Summary: {successes} successes / {timeouts} timeouts in {total_t:.1f}s")
    if aborted:
        # 5+ consecutive timeouts = cart genuinely silent (game probably crashed)
        last_ok = args.reads - timeouts  # crude: last ok read index
        print(f"# RESULT: Cart went silent (>=5 consecutive timeouts).")
        if 90 <= successes <= 105:
            print(f"#         Threshold matches the 'always-crashes-at-97' rate-dependent pattern.")
        else:
            print(f"#         Threshold {successes} differs from 97-read pattern; new behavior.")
    elif timeouts == 0:
        print(f"# RESULT: All {args.reads} reads completed successfully.")
        print(f"#         Game tolerates polling at this rate without any hiccups.")
    else:
        # Some timeouts but no consecutive run -> environmental hiccups, not a crash
        print(f"# RESULT: Test completed; {timeouts} transient timeout(s).")
        print(f"#         No consecutive-timeout streak >= 5, so no crash detected.")
        print(f"#         Transient timeouts are likely environmental (e.g., screen transitions).")


if __name__ == "__main__":
    main()
