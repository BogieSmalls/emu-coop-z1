"""Discriminator: do USB writes count toward the ~97-transaction crash limit, or only reads?

Sends a long burst of writes (action 0x02 = WritePairs, writing 0x00 to a cart-SRAM
scratch address), interleaved with periodic 1-byte liveness reads.

If writes don't count: all 5 liveness reads should succeed regardless of how many
writes we do (since we only ever issue 5 reads, well under the ~97 limit).

If writes do count: the cart goes silent once total transactions cross ~97 — i.e.,
liveness read #3 or #4 fails because too many writes were issued before it.

Usage:
    python audit_writes.py --port COM5 [--writes-per-batch 30] [--batches 5]

Default: 30 writes per batch, 5 batches = 150 writes + 6 reads = 156 total transactions.
"""
import argparse
import time

import serial

ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B

# Cart-SRAM scratch byte we'll repeatedly write 0x00 to (well outside any
# patch- or game-used region we know of)
WRITE_TARGET_ADDR = 0x7FE0
WRITE_VALUE = 0x00


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


def fr_write_pairs(mid: int, pairs: list[tuple[int, int]]) -> bytes:
    payload = bytes((len(pairs),))
    for addr, val in pairs:
        payload += bytes((addr & 0xFF, (addr >> 8) & 0xFF, val & 0xFF))
    return fr_len(mid, 0x02, payload)


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


def send_write(sp: serial.Serial, mid: int, addr: int, val: int) -> None:
    """Send a 1-pair WritePairs frame; don't wait for response."""
    usb_mem_wr(sp, ADDR_FIFO, fr_write_pairs(mid, [(addr, val)]))
    time.sleep(0.005)
    usb_mem_wr(sp, ADDR_FIFO, fr_return(mid))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--writes-per-batch", type=int, default=30)
    ap.add_argument("--batches", type=int, default=5)
    ap.add_argument("--write-interval", type=float, default=0.1,
                    help="seconds between writes within a batch (default 0.1 = 10 Hz)")
    args = ap.parse_args()

    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    print(f"# Write-vs-read discriminator")
    print(f"# Port: {args.port}, baud: {args.baud}")
    print(f"# Plan: {args.batches} batches of {args.writes_per_batch} writes each")
    print(f"#       Liveness read between each batch")
    print(f"#       Total: {args.batches * args.writes_per_batch} writes + {args.batches + 1} reads")
    print(f"#       Write target: ${WRITE_TARGET_ADDR:04X} (cart SRAM scratch)")
    print()

    mid = 1
    total_transactions = 0
    t_start = time.time()

    def next_mid() -> int:
        nonlocal mid
        m = mid
        mid = (mid % 254) + 1
        return m

    print("phase           total-trans  result    note")
    print("---------------  ----------  --------  -----")
    # Initial liveness
    latency = time_one_read(sp, next_mid(), 0x0000, 1, timeout_ms=200)
    total_transactions += 1
    result = "OK" if latency is not None else "TIMEOUT"
    print(f"liveness #0       {total_transactions:5d}        {result:8s}  {f'{latency:.1f}ms' if latency else 'baseline check'}")
    if latency is None:
        print("\n# Cart was already silent at start - aborting.")
        return

    for batch in range(1, args.batches + 1):
        # Send batch of writes
        for j in range(args.writes_per_batch):
            send_write(sp, next_mid(), WRITE_TARGET_ADDR, WRITE_VALUE)
            total_transactions += 1
            time.sleep(args.write_interval)
        print(f"after batch {batch}    {total_transactions:5d}        -         {args.writes_per_batch} writes done")

        # Liveness probe
        latency = time_one_read(sp, next_mid(), 0x0000, 1, timeout_ms=400)
        total_transactions += 1
        result = "OK" if latency is not None else "TIMEOUT"
        print(f"liveness #{batch}       {total_transactions:5d}        {result:8s}  {f'{latency:.1f}ms' if latency else 'CART SILENT'}")
        if latency is None:
            elapsed = time.time() - t_start
            print(f"\n# Cart went silent after {total_transactions} total transactions ({elapsed:.1f}s wallclock).")
            if total_transactions <= 110:
                print(f"# CONCLUSION: All transactions count toward the ~97 limit (writes are NOT free).")
            else:
                print(f"# CONCLUSION: Cart died at {total_transactions} transactions - past the 97 read-only threshold.")
                print(f"#             Writes may be cheaper than reads but still count.")
            return

    elapsed = time.time() - t_start
    print()
    print(f"# Final: {total_transactions} total transactions in {elapsed:.1f}s, all liveness reads succeeded.")
    if args.batches * args.writes_per_batch >= 100:
        print(f"# CONCLUSION: Writes do NOT count toward the read limit - we sent {args.batches * args.writes_per_batch}+ writes")
        print(f"#             and the cart stayed alive. Bridge can issue writes freely.")
    else:
        print(f"# Inconclusive (need to push harder). Try --batches 7 or higher.")


if __name__ == "__main__":
    main()
