# EDN8 Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-first (macOS nice-to-have) Python bridge app that lets a real NES + Everdrive Pro N8 + CC-patched ROM participate in emu-coop sessions as a peer, via the same OCI relay FCEUX peers use.

**Architecture:** Three-component split inside one bundled app — `bridge_core` (pure-Python library: IPS patcher, CC USB client, sync engine, pipe client), `bridge_cli` (argparse wrapper for power users), `bridge_gui` (CustomTkinter app for end users). All three share the same backend; the GUI is just a presentation layer over the CLI's behavior.

**Tech Stack:** Python 3.10+, pyserial (USB), customtkinter (GUI), pytest (tests), PyInstaller (single-binary build). Wire format reused unchanged from the existing emu-coop length-prefix JSON protocol.

**Spec:** `docs/superpowers/specs/2026-05-06-edn8-bridge-design.md`

**Pre-flight check before each commit:** `git status` and `git diff --cached` to confirm what's being committed.

**Testing convention:** TDD. Red phase before green. Tests live in `bridge/tests/`. Run with `cd bridge && python -m pytest tests/ -v --timeout=15`.

**LuaJIT path** (for any Lua-side parity tests): `C:\Users\bogie\AppData\Local\Programs\LuaJIT\bin\luajit.exe`

---

## Phase 1: Hardware audit

This phase is data-collection, not engineering. The output is `bridge/docs/cc-patch-capabilities.md` documenting what the CC firmware can actually do and at what rates. Subsequent phases reference this.

### Task 1: Hardware audit script + run against real cart

**Files:**
- Create: `bridge/audit_cc_capabilities.py` (one-shot script)
- Create: `bridge/docs/cc-patch-capabilities.md` (results doc)

This is a USER-DRIVEN task. The implementer writes the script; the user runs it against their real EDN8 + NES + CC-patched ROM and pastes the output back; the implementer captures results in the doc.

- [ ] **Step 1: Create the audit script**

Create `bridge/audit_cc_capabilities.py`:

```python
"""One-shot CC capability audit. Run against a real EDN8 + CC-patched Z1 ROM.

Usage: python audit_cc_capabilities.py --port COM3 [--baud 115200]

Tests:
  1. Single-address read latency (mean, p95, p99 over 100 reads)
  2. Bulk read latency at 10/100/400 byte read-array sizes
  3. Sustained polling rate at 1Hz, 10Hz, 30Hz, 60Hz over 60s windows
  4. Memory region accessibility: 0x0000-0x07FF (RAM), 0x6000-0x7FFF (cart SRAM)
  5. Stability over 5 minutes of continuous 10Hz polling

Prints results as a markdown table for easy paste into docs/cc-patch-capabilities.md.
"""
import argparse
import statistics
import sys
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


def read_window(sp: serial.Serial, ms: int) -> bytes:
    t0 = time.time()
    buf = bytearray()
    while (time.time() - t0) * 1000 < ms:
        n = sp.in_waiting
        if n:
            buf += sp.read(n)
        else:
            time.sleep(0.0015)
    return bytes(buf)


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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(len(s) * pct / 100)
    return s[min(k, len(s) - 1)]


def test_latency(sp: serial.Serial, base: int, sizes: list[int], samples: int = 100) -> None:
    print("\n## Read-array latency")
    print(f"\n| Bytes | Mean (ms) | p95 (ms) | p99 (ms) | Timeouts |")
    print(f"|---|---|---|---|---|")
    mid = 1
    for size in sizes:
        timings: list[float] = []
        timeouts = 0
        for _ in range(samples):
            t = time_one_read(sp, mid, base, size)
            if t is None:
                timeouts += 1
            else:
                timings.append(t)
            mid = (mid + 1) & 0xFF
            if mid == 0:
                mid = 1
        if timings:
            mean = statistics.mean(timings)
            p95 = percentile(timings, 95)
            p99 = percentile(timings, 99)
            print(f"| {size} | {mean:.1f} | {p95:.1f} | {p99:.1f} | {timeouts}/{samples} |")
        else:
            print(f"| {size} | (all timed out) | - | - | {timeouts}/{samples} |")


def test_sustained_rate(sp: serial.Serial, base: int, size: int, target_hz: float, duration_s: int) -> None:
    """Try to sustain target_hz polling for duration_s. Reports actual rate + errors."""
    period = 1.0 / target_hz
    deadline = time.time() + duration_s
    success = 0
    timeouts = 0
    mid = 1
    actual_starts = []
    while time.time() < deadline:
        loop_start = time.time()
        actual_starts.append(loop_start)
        t = time_one_read(sp, mid, base, size, timeout_ms=int(period * 1000 * 0.8))
        if t is None:
            timeouts += 1
        else:
            success += 1
        mid = (mid + 1) & 0xFF
        if mid == 0:
            mid = 1
        elapsed = time.time() - loop_start
        sleep = period - elapsed
        if sleep > 0:
            time.sleep(sleep)
    actual_hz = success / duration_s if duration_s > 0 else 0.0
    print(f"| {target_hz} Hz | {size} | {duration_s}s | {success} | {timeouts} | {actual_hz:.1f} Hz |")


def test_sustained(sp: serial.Serial, base: int) -> None:
    print("\n## Sustained polling rate (60s windows)")
    print("\n| Target | Bytes/poll | Duration | Successes | Timeouts | Actual rate |")
    print("|---|---|---|---|---|---|")
    for hz in [1, 10, 30, 60]:
        test_sustained_rate(sp, base, 400, hz, 60)


def test_memory_regions(sp: serial.Serial) -> None:
    print("\n## Memory region accessibility")
    print("\n| Region | Range | Reads OK? | Notes |")
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
        t = time_one_read(sp, 1, base, size, timeout_ms=200)
        print(f"| {name} | 0x{base:04X}+{size}b | {'✓' if t is not None else '✗'} | {f'{t:.1f}ms' if t is not None else 'timeout'} |")


def test_stability(sp: serial.Serial, base: int) -> None:
    print("\n## Stability (5 min @ 10Hz, 400 bytes)")
    deadline = time.time() + 300
    success = 0
    timeouts = 0
    mid = 1
    while time.time() < deadline:
        loop_start = time.time()
        t = time_one_read(sp, mid, base, 400, timeout_ms=80)
        if t is None:
            timeouts += 1
        else:
            success += 1
        mid = (mid + 1) & 0xFF
        if mid == 0:
            mid = 1
        elapsed = time.time() - loop_start
        sleep = 0.1 - elapsed
        if sleep > 0:
            time.sleep(sleep)
    print(f"\nResults: {success} successes / {timeouts} timeouts over 5 minutes")
    print(f"Failure rate: {100 * timeouts / (success + timeouts):.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    print(f"# EDN8 CC capability audit")
    print(f"\nPort: {args.port}, baud: {args.baud}")
    print(f"Run at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n## Setup")
    print("- Cart: <fill in: model + firmware version>")
    print("- ROM: <fill in: vanilla Z1 or Z1R seed + CC patch>")
    print("- Game state: <fill in: title screen / overworld / paused>")

    test_memory_regions(sp)
    test_latency(sp, base=0x0000, sizes=[10, 100, 400])
    test_sustained(sp, base=0x0000)
    test_stability(sp, base=0x0000)

    print("\n## Conclusions")
    print("- (Fill in observations: which polling rate is sustainable, any anomalies, etc.)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: USER ACTION — run the audit**

This step is for the user. They run:

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python audit_cc_capabilities.py --port COM3 > audit-output.md
```

(Replace COM3 with whichever port the EDN8 enumerates as.)

The user then pastes the contents of `audit-output.md` back to the implementer.

- [ ] **Step 3: Capture results in `docs/cc-patch-capabilities.md`**

Once the user provides audit output, create `bridge/docs/cc-patch-capabilities.md` with:

```markdown
# CC patch capabilities (audit results)

Captured against a real EDN8 + CC-patched Z1 ROM on <DATE>.

[paste audit script output here]

## Recommendations for bridge polling architecture

Based on the above:

- Default polling rate: <X> Hz
- Default sync set: <Y> bytes
- Maximum address-set size at 10 Hz: <Z> bytes
- Stability concerns: <list>
```

Fill in the recommendations from the data.

- [ ] **Step 4: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/audit_cc_capabilities.py bridge/docs/cc-patch-capabilities.md
git commit -m "feat(bridge): add CC capability audit script + results"
```

---

## Phase 2: Foundation libraries

### Task 2: Initialize bridge project skeleton

**Files:**
- Create: `bridge/pyproject.toml`
- Create: `bridge/.gitignore`
- Create: `bridge/bridge_core/__init__.py`
- Create: `bridge/bridge_cli/__init__.py`
- Create: `bridge/bridge_gui/__init__.py`
- Create: `bridge/tests/__init__.py`
- Create: `bridge/bridge_core/modes/__init__.py`
- Create: `bridge/bridge_core/patches/.gitkeep`

- [ ] **Step 1: Create pyproject.toml**

Create `bridge/pyproject.toml`:

```toml
[project]
name = "emu-coop-bridge"
version = "0.1.0"
description = "Bridge that lets a real NES (via Everdrive Pro N8) participate in emu-coop sessions"
requires-python = ">=3.10"
dependencies = [
  "pyserial>=3.5",
  "customtkinter>=5.2",
]

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio>=0.23", "pytest-timeout>=2"]
dist = ["pyinstaller>=6"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["bridge_core", "bridge_core.modes", "bridge_cli", "bridge_gui"]

[tool.setuptools.package-data]
"bridge_core" = ["patches/*.ips"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create .gitignore**

Create `bridge/.gitignore`:

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.venv/
build/
dist/
uv.lock
audit-output.md
```

- [ ] **Step 3: Create empty package files**

Create `bridge/bridge_core/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `bridge/bridge_cli/__init__.py` (empty file).

Create `bridge/bridge_gui/__init__.py` (empty file).

Create `bridge/tests/__init__.py` (empty file).

Create `bridge/bridge_core/modes/__init__.py` (empty file).

Create `bridge/bridge_core/patches/.gitkeep` (empty file — placeholder so git tracks the directory before we vendor the IPS patch).

- [ ] **Step 4: Verify**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pip install -e ".[test]"
python -c "import bridge_core; print(bridge_core.__version__)"
```

Expected: `0.1.0`

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/pyproject.toml bridge/.gitignore bridge/bridge_core bridge/bridge_cli bridge/bridge_gui bridge/tests
git commit -m "feat(bridge): initialize project skeleton"
```

---

### Task 3: IPS parser/applier

**Files:**
- Create: `bridge/bridge_core/ips.py`
- Create: `bridge/tests/test_ips.py`
- Copy: `bridge/bridge_core/patches/zelda_cc.ips` (from `D:\Downloads\Games\ROMs\Z1R\EmuCoopBridge\Legend of Zelda, The (USA)_CC.ips`)

- [ ] **Step 1: Vendor the IPS patch**

```powershell
copy "D:\Downloads\Games\ROMs\Z1R\EmuCoopBridge\Legend of Zelda, The (USA)_CC.ips" `
     "D:\Projects\Streaming\z1rr-coop\bridge\bridge_core\patches\zelda_cc.ips"
```

- [ ] **Step 2: Write the failing tests**

Create `bridge/tests/test_ips.py`:

```python
import io
import struct
from pathlib import Path

import pytest

from bridge_core import ips


def make_ips(records: list[tuple[int, bytes]]) -> bytes:
    """Build a minimal IPS file from (offset, data) records."""
    buf = b"PATCH"
    for offset, data in records:
        buf += offset.to_bytes(3, "big")
        buf += len(data).to_bytes(2, "big")
        buf += data
    buf += b"EOF"
    return buf


def test_parse_simple_patch():
    raw = make_ips([(0x0010, b"\xab\xcd"), (0x0100, b"\xff")])
    records = list(ips.parse(io.BytesIO(raw)))
    assert records == [(0x0010, b"\xab\xcd"), (0x0100, b"\xff")]


def test_apply_simple_patch():
    src = bytearray(b"\x00" * 256)
    raw = make_ips([(0x0010, b"\xab\xcd"), (0x0100, b"\xff")])
    out = ips.apply(bytes(src), raw)
    assert out[0x0010:0x0012] == b"\xab\xcd"
    assert out[0x0100] == 0xFF
    assert out[0x0000] == 0x00  # unchanged


def test_apply_extends_rom_if_needed():
    src = bytearray(b"\x00" * 256)
    raw = make_ips([(0x0300, b"\x42")])  # past end of src
    out = ips.apply(bytes(src), raw)
    assert len(out) >= 0x0301
    assert out[0x0300] == 0x42


def test_invalid_header_raises():
    with pytest.raises(ips.IPSError):
        ips.apply(b"\x00" * 16, b"NOPATCH...")


def test_zelda_cc_patch_loads():
    """The vendored Z1 CC patch should be parseable."""
    patch_path = Path(__file__).parent.parent / "bridge_core" / "patches" / "zelda_cc.ips"
    raw = patch_path.read_bytes()
    records = list(ips.parse(io.BytesIO(raw)))
    assert len(records) > 0


def test_is_patched_detects_applied():
    """If an IPS has been applied, is_patched should return True."""
    src = bytearray(b"\x00" * 1024)
    raw = make_ips([(0x0100, b"\xab\xcd")])
    patched = ips.apply(bytes(src), raw)
    assert ips.is_patched(patched, raw) is True
    assert ips.is_patched(bytes(src), raw) is False
```

- [ ] **Step 3: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_ips.py -v
```

Expected: import errors / all FAIL.

- [ ] **Step 4: Implement `bridge_core/ips.py`**

Create `bridge_core/ips.py`:

```python
"""IPS patch format parser and applier.

IPS is a simple binary patch format:
- 5-byte header: b"PATCH"
- Records: 3-byte big-endian offset, 2-byte big-endian length, length bytes data
  (length=0 means RLE: 2-byte count + 1-byte fill byte)
- Trailer: b"EOF"
"""
from __future__ import annotations

import io
from typing import BinaryIO, Iterator


class IPSError(Exception):
    pass


def parse(stream: BinaryIO) -> Iterator[tuple[int, bytes]]:
    """Yield (offset, data) records from an IPS stream."""
    header = stream.read(5)
    if header != b"PATCH":
        raise IPSError(f"invalid IPS header: {header!r}")
    while True:
        offset_bytes = stream.read(3)
        if offset_bytes == b"EOF":
            return
        if len(offset_bytes) != 3:
            raise IPSError("unexpected end of patch (offset)")
        offset = int.from_bytes(offset_bytes, "big")
        length_bytes = stream.read(2)
        if len(length_bytes) != 2:
            raise IPSError("unexpected end of patch (length)")
        length = int.from_bytes(length_bytes, "big")
        if length == 0:
            # RLE: 2-byte count + 1-byte fill
            rle_count_bytes = stream.read(2)
            rle_fill_bytes = stream.read(1)
            if len(rle_count_bytes) != 2 or len(rle_fill_bytes) != 1:
                raise IPSError("unexpected end of patch (RLE)")
            count = int.from_bytes(rle_count_bytes, "big")
            data = rle_fill_bytes * count
        else:
            data = stream.read(length)
            if len(data) != length:
                raise IPSError("unexpected end of patch (data)")
        yield offset, data


def apply(rom_bytes: bytes, patch_bytes: bytes) -> bytes:
    """Apply IPS patch to ROM bytes; return new bytes."""
    out = bytearray(rom_bytes)
    for offset, data in parse(io.BytesIO(patch_bytes)):
        end = offset + len(data)
        if end > len(out):
            out.extend(b"\x00" * (end - len(out)))
        out[offset:end] = data
    return bytes(out)


def is_patched(rom_bytes: bytes, patch_bytes: bytes) -> bool:
    """Return True if rom_bytes already contains the bytes from patch_bytes."""
    for offset, data in parse(io.BytesIO(patch_bytes)):
        if offset + len(data) > len(rom_bytes):
            return False
        if rom_bytes[offset:offset + len(data)] != data:
            return False
    return True
```

- [ ] **Step 5: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_ips.py -v
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/ips.py bridge/bridge_core/patches/zelda_cc.ips bridge/tests/test_ips.py
git commit -m "feat(bridge): add IPS patch parser/applier with vendored Z1 CC patch"
```

---

### Task 4: Mock serial fixture

**Files:**
- Create: `bridge/tests/mock_serial.py`

- [ ] **Step 1: Implement the mock**

Create `bridge/tests/mock_serial.py`:

```python
"""Pyserial-compatible in-memory mock for unit tests."""
from __future__ import annotations

from collections import deque


class MockSerial:
    """Implements the pyserial subset bridge_core uses: write, read, in_waiting, close."""

    def __init__(self) -> None:
        self._tx_buf = bytearray()  # bytes the test code "wrote" (i.e., what bridge sends)
        self._rx_buf: deque[int] = deque()  # bytes the test should "read back" from the cart
        self.is_open = True
        self.timeout = 0
        self.write_timeout = 0
        self.baudrate = 115200

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise IOError("port closed")
        self._tx_buf += data
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if not self.is_open:
            raise IOError("port closed")
        out = bytearray()
        for _ in range(min(n, len(self._rx_buf))):
            out.append(self._rx_buf.popleft())
        return bytes(out)

    @property
    def in_waiting(self) -> int:
        return len(self._rx_buf)

    def close(self) -> None:
        self.is_open = False

    def reset_input_buffer(self) -> None:
        self._rx_buf.clear()

    def reset_output_buffer(self) -> None:
        self._tx_buf.clear()

    # Test helpers (not part of the pyserial API)

    def feed_rx(self, data: bytes) -> None:
        """Push bytes into the simulated cart-to-host RX buffer."""
        self._rx_buf.extend(data)

    def take_tx(self) -> bytes:
        """Drain and return everything the bridge has written so far."""
        out = bytes(self._tx_buf)
        self._tx_buf.clear()
        return out
```

- [ ] **Step 2: Commit (no separate test for the mock — its first user is `test_cc_client.py`)**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/tests/mock_serial.py
git commit -m "test(bridge): add MockSerial fixture"
```

---

### Task 5: Mock CC server fixture

**Files:**
- Create: `bridge/tests/mock_cc_server.py`

- [ ] **Step 1: Implement the simulator**

Create `bridge/tests/mock_cc_server.py`:

```python
"""In-memory simulation of an EDN8 + CC-patched cart, for unit tests.

Wraps a MockSerial. When the bridge writes a CC frame to the mock serial,
this simulator interprets it (via .step()) and pushes the appropriate response
into the mock serial's RX buffer.
"""
from __future__ import annotations

from .mock_serial import MockSerial


# CC protocol constants (mirror the real cart firmware)
ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B


class MockCCServer:
    """Simulates the cart-side of the CC protocol against a MockSerial."""

    def __init__(self, ram_size: int = 0x0800) -> None:
        self.serial = MockSerial()
        self.ram = bytearray(ram_size)
        self._tx_carryover = bytearray()  # partial frames from bridge that haven't completed yet

    def set_ram(self, addr: int, value: int | bytes) -> None:
        if isinstance(value, int):
            self.ram[addr] = value
        else:
            self.ram[addr:addr + len(value)] = value

    def step(self) -> None:
        """Process all pending bridge → cart frames in the mock serial's TX buffer.

        For each received frame, push the appropriate response into the cart → bridge
        RX buffer. Tests call this after issuing a bridge command, before reading the
        response.
        """
        tx = bytes(self._tx_carryover) + self.serial.take_tx()
        self._tx_carryover.clear()
        idx = 0
        while idx < len(tx):
            # Parse the USB MEM_WR header: P, P^FF, CMD, CMD^FF (4 bytes)
            if idx + 4 > len(tx):
                self._tx_carryover += tx[idx:]
                return
            if tx[idx] != P or tx[idx + 1] != (P ^ 0xFF):
                # Skip until next plausible header
                idx += 1
                continue
            cmd = tx[idx + 2]
            if tx[idx + 3] != (cmd ^ 0xFF):
                idx += 1
                continue
            if cmd != CMD_MEM_WR:
                idx += 4
                continue
            # MEM_WR: 4-byte addr, 4-byte len, 1-byte exec, payload
            if idx + 4 + 4 + 4 + 1 > len(tx):
                self._tx_carryover += tx[idx:]
                return
            payload_len = int.from_bytes(tx[idx + 8:idx + 12], "little")
            total = 4 + 4 + 4 + 1 + payload_len
            if idx + total > len(tx):
                self._tx_carryover += tx[idx:]
                return
            payload = tx[idx + 13:idx + 13 + payload_len]
            self._handle_mem_wr(payload)
            idx += total

    def _handle_mem_wr(self, payload: bytes) -> None:
        """A MEM_WR to ADDR_FIFO carries an inner CC frame: L, MID, ACTION, body."""
        if not payload:
            return
        L = payload[0]
        if L != len(payload) - 1:
            return
        if len(payload) < 3:
            return
        mid = payload[1]
        action = payload[2]
        body = payload[3:]
        if action == 0x00:
            # Read individual addresses: count + 2-byte addr each
            count = body[0]
            addrs = [int.from_bytes(body[1 + 2 * i:3 + 2 * i], "little") for i in range(count)]
            values = bytes(self.ram[a] if a < len(self.ram) else 0 for a in addrs)
            self._respond(mid, 0x00, values)
        elif action == 0x01:
            # Read array: 1-byte count + 2-byte base
            count = body[0]
            base = int.from_bytes(body[1:3], "little")
            values = bytes(self.ram[base:base + count])
            self._respond(mid, 0x01, values)
        elif action == 0x02:
            # Write pairs: count + (2-byte addr + 1-byte val) each
            count = body[0]
            for i in range(count):
                a = int.from_bytes(body[1 + 3 * i:3 + 3 * i], "little")
                v = body[3 + 3 * i]
                if a < len(self.ram):
                    self.ram[a] = v
            self._respond(mid, 0x02, b"\x01")
        elif action == 0x03:
            # Write array: 1-byte count + 2-byte base + count bytes
            count = body[0]
            base = int.from_bytes(body[1:3], "little")
            data = body[3:3 + count]
            self.ram[base:base + len(data)] = data
            self._respond(mid, 0x03, b"\x01")
        elif action == 0x05:
            # Return: ACK an outstanding read
            self._respond(mid, 0x00, b"\x01")

    def _respond(self, mid: int, action: int, values: bytes) -> None:
        """Push a CC response frame back to the bridge: 0x20, mid, action, values."""
        self.serial.feed_rx(bytes([0x20, mid, action]) + values)
```

- [ ] **Step 2: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/tests/mock_cc_server.py
git commit -m "test(bridge): add MockCCServer fixture"
```

---

### Task 6: CC client (frame protocol)

**Files:**
- Create: `bridge/bridge_core/cc_client.py`
- Create: `bridge/tests/test_cc_client.py`

- [ ] **Step 1: Write the failing tests**

Create `bridge/tests/test_cc_client.py`:

```python
import pytest

from bridge_core.cc_client import CCClient

from .mock_cc_server import MockCCServer


def make_client_with_mock(ram_size: int = 0x0800) -> tuple[CCClient, MockCCServer]:
    server = MockCCServer(ram_size=ram_size)
    client = CCClient(serial_port=server.serial)
    return client, server


def test_read_array_returns_correct_bytes():
    client, server = make_client_with_mock()
    server.set_ram(0x0010, b"\xab\xcd\xef")
    client.send_read_array(0x0010, 3)
    server.step()
    result = client.poll_response(timeout_ms=100)
    assert result == b"\xab\xcd\xef"


def test_read_individual_addresses():
    client, server = make_client_with_mock()
    server.set_ram(0x0010, 0xAB)
    server.set_ram(0x0050, 0xCD)
    server.set_ram(0x0100, 0xEF)
    client.send_read_addrs([0x0010, 0x0050, 0x0100])
    server.step()
    result = client.poll_response(timeout_ms=100)
    assert result == b"\xab\xcd\xef"


def test_write_pairs_updates_ram():
    client, server = make_client_with_mock()
    client.send_write_pairs([(0x0010, 0xAB), (0x0050, 0xCD)])
    server.step()
    assert server.ram[0x0010] == 0xAB
    assert server.ram[0x0050] == 0xCD


def test_write_array_updates_ram():
    client, server = make_client_with_mock()
    client.send_write_array(0x0010, b"\xab\xcd\xef")
    server.step()
    assert server.ram[0x0010:0x0013] == b"\xab\xcd\xef"


def test_msg_id_wraps_after_255():
    client, server = make_client_with_mock()
    for _ in range(257):
        client.send_read_array(0x0000, 4)
        server.step()
        client.poll_response(timeout_ms=100)
    # Should not raise; client should keep msg_id in 1-255 range (skipping 0)
    assert 1 <= client._msg_id <= 255


def test_poll_response_returns_none_on_timeout():
    client, _server = make_client_with_mock()
    # Don't issue a request; nothing should be in the RX buffer
    result = client.poll_response(timeout_ms=10)
    assert result is None
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_cc_client.py -v
```

Expected: import errors / all FAIL.

- [ ] **Step 3: Implement `bridge_core/cc_client.py`**

Create `bridge_core/cc_client.py`:

```python
"""CC USB serial protocol client.

Wraps a serial.Serial-like object and exposes methods to send CC frames
(read/write/freeze) and parse responses.

CC frame format (host -> cart, wrapped in a USB MEM_WR to ADDR_FIFO):
    L (1 byte) = total body length + 1
    MID (1 byte) = monotonic message id, 1..255
    ACTION (1 byte) = 0x00 read addrs, 0x01 read array, 0x02 write pairs,
                       0x03 write array, 0x04 freeze, 0x05 return
    body...

CC response (cart -> host):
    0x20, MID, ACTION, values...
"""
from __future__ import annotations

import time
from typing import Protocol


# USB-level constants
ADDR_FIFO = 0x01810000
CMD_MEM_WR = 0x1A
P = 0x2B


class SerialLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, n: int = 1) -> bytes: ...
    @property
    def in_waiting(self) -> int: ...
    def close(self) -> None: ...


def _make_usb_header(cmd: int) -> bytes:
    return bytes([P, P ^ 0xFF, cmd & 0xFF, (cmd ^ 0xFF) & 0xFF])


def _u32le(v: int) -> bytes:
    return bytes([(v >> 0) & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])


def _make_cc_frame(mid: int, action: int, payload: bytes) -> bytes:
    body = bytes((mid & 0xFF, action & 0xFF)) + payload
    L = 1 + len(body)
    if L > 255:
        raise ValueError(f"CC frame too large: {L}")
    return bytes((L,)) + body


def _strip_status_pairs(b: bytes) -> bytes:
    """Cart firmware periodically sends 0x00 0xA5 or 0x04 0xA5 status pairs;
    strip them from any received byte stream."""
    out = bytearray()
    i = 0
    while i < len(b):
        if i + 1 < len(b) and b[i] in (0x00, 0x04) and b[i + 1] == 0xA5:
            i += 2
            continue
        out.append(b[i])
        i += 1
    return bytes(out)


class CCClient:
    """Wraps a serial port and exposes the CC USB protocol primitives."""

    def __init__(self, serial_port: SerialLike) -> None:
        self._sp = serial_port
        self._msg_id = 0
        self._rx_buf = bytearray()

    def _next_mid(self) -> int:
        self._msg_id = (self._msg_id + 1) & 0xFF
        if self._msg_id == 0:
            self._msg_id = 1
        return self._msg_id

    def _usb_mem_wr(self, addr: int, data: bytes) -> None:
        self._sp.write(_make_usb_header(CMD_MEM_WR))
        self._sp.write(_u32le(addr))
        self._sp.write(_u32le(len(data)))
        self._sp.write(b"\x00")
        self._sp.write(data)

    def send_read_addrs(self, addrs: list[int]) -> None:
        mid = self._next_mid()
        payload = bytes((len(addrs),))
        for a in addrs:
            payload += bytes((a & 0xFF, (a >> 8) & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x00, payload))
        self._expected_mid = mid
        self._expected_action = 0x00
        self._expected_values = len(addrs)

    def send_read_array(self, base: int, length: int) -> None:
        mid = self._next_mid()
        payload = bytes((length & 0xFF, base & 0xFF, (base >> 8) & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x01, payload))
        self._expected_mid = mid
        self._expected_action = 0x01
        self._expected_values = length

    def send_write_pairs(self, pairs: list[tuple[int, int]]) -> None:
        mid = self._next_mid()
        payload = bytes((len(pairs),))
        for addr, val in pairs:
            payload += bytes((addr & 0xFF, (addr >> 8) & 0xFF, val & 0xFF))
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x02, payload))

    def send_write_array(self, base: int, data: bytes) -> None:
        mid = self._next_mid()
        payload = bytes((len(data) & 0xFF, base & 0xFF, (base >> 8) & 0xFF)) + data
        self._usb_mem_wr(ADDR_FIFO, _make_cc_frame(mid, 0x03, payload))

    def poll_response(self, timeout_ms: int = 100) -> bytes | None:
        """Wait up to timeout_ms for a response matching the last send_read_*."""
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            n = self._sp.in_waiting
            if n:
                self._rx_buf += self._sp.read(n)
            filt = _strip_status_pairs(bytes(self._rx_buf))
            for i in range(len(filt) - 3):
                if (
                    filt[i] == 0x20
                    and filt[i + 1] == (self._expected_mid & 0xFF)
                    and filt[i + 2] in (self._expected_action & 0xFF, 0x00)
                ):
                    start = i + 3
                    end = start + self._expected_values
                    if end <= len(filt):
                        result = bytes(filt[start:end])
                        self._rx_buf.clear()
                        return result
            time.sleep(0.001)
        return None

    def close(self) -> None:
        self._sp.close()
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_cc_client.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/cc_client.py bridge/tests/test_cc_client.py
git commit -m "feat(bridge): add CC client (USB serial frame protocol)"
```

---

## Phase 3: Sync engine

### Task 7: recordChanged port + tests

**Files:**
- Create: `bridge/bridge_core/sync_engine.py` (initial — just `record_changed()` function)
- Create: `bridge/tests/test_sync_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `bridge/tests/test_sync_engine.py`:

```python
"""Behavioral parity tests for record_changed() — verified against driver.lua."""
import pytest

from bridge_core.sync_engine import record_changed


def test_high_kind_send_when_increased():
    record = {"kind": "high", "size": 1}
    allow, value = record_changed(record, value=1, previous_value=0, receiving=False)
    assert allow is True
    assert value == 1


def test_high_kind_no_send_when_decreased():
    record = {"kind": "high", "size": 1}
    allow, _value = record_changed(record, value=0, previous_value=1, receiving=False)
    assert allow is False


def test_high_kind_no_send_when_same():
    record = {"kind": "high", "size": 1}
    allow, _value = record_changed(record, value=1, previous_value=1, receiving=False)
    assert allow is False


def test_delta_kind_send_when_changed():
    record = {"kind": "delta", "size": 1}
    allow, value = record_changed(record, value=8, previous_value=0, receiving=False)
    assert allow is True
    assert value == 8  # delta = 8 - 0


def test_delta_kind_receive_applies_delta():
    record = {"kind": "delta", "size": 1}
    allow, value = record_changed(record, value=8, previous_value=4, receiving=True)
    assert allow is True
    assert value == 12  # 4 + 8


def test_delta_kind_clamp_min():
    record = {"kind": "delta", "size": 1, "deltaMin": 1}
    allow, value = record_changed(record, value=5, previous_value=0, receiving=True)
    # without clamp, 0+5=5; clamp doesn't trigger
    assert allow is True
    assert value == 5


def test_delta_kind_no_send_zero_delta_on_receive():
    record = {"kind": "delta", "size": 1}
    allow, _value = record_changed(record, value=0, previous_value=4, receiving=True)
    # delta of 0 means no change; allow=False
    assert allow is False


def test_bitor_kind_changes_bits():
    record = {"kind": "bitOr", "size": 1}
    allow, value = record_changed(record, value=0b1010, previous_value=0b0001, receiving=True)
    assert allow is True
    assert value == 0b1011  # OR


def test_function_kind_invokes_callback():
    captured = []

    def custom_kind(val, prev, recv):
        captured.append((val, prev, recv))
        return True, val * 2

    record = {"kind": custom_kind}
    allow, value = record_changed(record, value=5, previous_value=2, receiving=True)
    assert allow is True
    assert value == 10
    assert captured == [(5, 2, True)]
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_sync_engine.py -v
```

Expected: import errors / all FAIL.

- [ ] **Step 3: Implement `record_changed()` in `bridge_core/sync_engine.py`**

Create `bridge_core/sync_engine.py`:

```python
"""Sync engine — Python port of driver.lua.

record_changed() is line-by-line equivalent to the Lua function. Other parts
(SyncEngine class with poll/cache/handleTable) come in a later task.
"""
from __future__ import annotations

from typing import Any, Callable


def record_changed(
    record: dict[str, Any],
    value: int,
    previous_value: int,
    receiving: bool,
) -> tuple[bool, int]:
    """Port of driver.lua's recordChanged().

    Returns (allow, value): whether to send/apply this change, and the resolved
    value to send/apply (which may differ from the input).
    """
    if record.get("kind") == "trigger":
        return False, value

    unaltered = value
    allow = True

    # Compute mask
    size = record.get("size", 1)
    if size == 2:
        mask = 0xFFFF
    elif size == 4:
        mask = 0xFFFFFFFF
    else:
        mask = 0xFF

    inverse_mask = 0
    masked_value = value

    if "mask" in record:
        mask = record["mask"]
        inverse_mask = (~mask) & 0xFFFFFFFF
        masked_value = (mask & value) | (inverse_mask & previous_value)

    kind = record.get("kind")

    if callable(kind):
        result = kind(value, previous_value, receiving)
        if isinstance(result, tuple):
            allow, value = result
        else:
            allow = bool(result)
        if value is None:
            value = unaltered
    elif kind == "high":
        allow = (mask & value) > (mask & previous_value)
        value = masked_value
    elif kind == "bitOr":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value | previous_value
    elif kind == "bitAnd":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value & previous_value
    elif kind == "delta":
        if not receiving:
            allow = masked_value != previous_value
            value = (mask & value) - (mask & previous_value)
        else:
            allow = value != 0
            masked_sum = previous_value + value
            if "deltaMin" in record and masked_sum < record["deltaMin"]:
                masked_sum = record["deltaMin"]
            if "deltaMax" in record and masked_sum > record["deltaMax"]:
                masked_sum = record["deltaMax"]
            value = (inverse_mask & previous_value) | (mask & masked_sum)
    else:
        allow = masked_value != previous_value
        value = masked_value

    if allow and "cond" in record:
        # cond is a callable: cond(value, size) -> bool
        cond_fn = record["cond"]
        if callable(cond_fn):
            allow = cond_fn(masked_value, size)

    return allow, value
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_sync_engine.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/sync_engine.py bridge/tests/test_sync_engine.py
git commit -m "feat(bridge): port record_changed() from driver.lua"
```

---

### Task 8: Port tloz_all mode

**Files:**
- Create: `bridge/bridge_core/modes/tloz_all.py`
- Create: `bridge/tests/test_modes_tloz_all.py`

- [ ] **Step 1: Write the failing tests**

Create `bridge/tests/test_modes_tloz_all.py`:

```python
"""Mode-parity tests: tloz_all.py must agree with modes/tloz_all.lua on guid + addresses."""
import pytest

from bridge_core.modes import tloz_all


def test_guid_matches_lua_mode():
    """Must match modes/tloz_all.lua's guid line-for-line."""
    assert tloz_all.GUID == "377c5683-3cf5-4c56-a921-ab40257b2ec1"


def test_format_matches_lua_mode():
    assert tloz_all.FORMAT == "1.2"


def test_running_predicate_for_z1_states():
    """Z1 state register is 0x12; 'running' = state in [0x4, 0xD]."""
    assert tloz_all.is_running({0x12: 0x4}) is True
    assert tloz_all.is_running({0x12: 0xD}) is True
    assert tloz_all.is_running({0x12: 0x0}) is False
    assert tloz_all.is_running({0x12: 0x3}) is False
    assert tloz_all.is_running({0x12: 0xE}) is False


def test_sync_includes_inventory_addresses():
    """Wood Sword (0x0657), Bow (0x065A), Recorder (0x065C) etc. must be in sync."""
    expected = [0x0657, 0x065A, 0x065C, 0x065F, 0x0660, 0x0661, 0x0663, 0x0664, 0x0665, 0x0666, 0x0674, 0x0675, 0x0676]
    for addr in expected:
        assert addr in tloz_all.SYNC, f"missing inventory addr 0x{addr:04X}"


def test_sync_includes_overworld_map_range():
    """Overworld map is 0x067F..0x06FE."""
    for addr in range(0x067F, 0x06FF):
        assert addr in tloz_all.SYNC, f"missing overworld map addr 0x{addr:04X}"


def test_sync_includes_dungeon_map_range():
    """Dungeon map is 0x06FF..0x07FE."""
    for addr in range(0x06FF, 0x07FF):
        assert addr in tloz_all.SYNC, f"missing dungeon map addr 0x{addr:04X}"


def test_heart_record_kind_is_callable():
    """Heart container handler is a function-as-kind."""
    assert callable(tloz_all.SYNC[0x066F]["kind"])


def test_bomb_record_has_delta_kind():
    record = tloz_all.SYNC[0x067C]
    assert record["kind"] == "delta"
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_modes_tloz_all.py -v
```

Expected: ImportError / FAIL.

- [ ] **Step 3: Implement the Python port of tloz_all.lua**

Create `bridge/bridge_core/modes/tloz_all.py`:

```python
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
    # keys (delta)
    0x066E: {"kind": "delta", "deltaMin": 0},
    # heart containers (function-as-kind)
    0x066F: {"kind": _heart_kind, "message": _heart_message},
    # bomb upgrade (delta with side-effect on receive)
    0x067C: {
        "kind": "delta",
        "deltaMin": 1,
        "deltaMax": 255,
        "receive_trigger": _bomb_receive_trigger,
    },
}

# Overworld map: 0x067F..0x06FE (each tile: 0x80 if requires-item-and-opened, 0x10 if obtained)
for _i in range(0x067F, 0x06FF):
    SYNC[_i] = {"kind": "bitOr", "mask": 0x80 | 0x10}

# Dungeon map: 0x06FF..0x07FE (top-room-flags + visited + item-collected + key-doors)
for _i in range(0x06FF, 0x07FF):
    SYNC[_i] = {"kind": "bitOr"}
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_modes_tloz_all.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/modes/tloz_all.py bridge/tests/test_modes_tloz_all.py
git commit -m "feat(bridge): port tloz_all mode from Lua"
```

---

### Task 9: SyncEngine class (poll/cache/handleTable/forceSend)

**Files:**
- Modify: `bridge/bridge_core/sync_engine.py`
- Modify: `bridge/tests/test_sync_engine.py`

- [ ] **Step 1: Add SyncEngine tests to test_sync_engine.py**

Append to `bridge/tests/test_sync_engine.py`:

```python
from bridge_core.cc_client import CCClient
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine

from .mock_cc_server import MockCCServer


def make_engine() -> tuple[SyncEngine, MockCCServer]:
    server = MockCCServer()
    client = CCClient(server.serial)
    engine = SyncEngine(cc_client=client, mode=tloz_all)
    return engine, server


def test_sync_engine_starts_idle():
    engine, _server = make_engine()
    assert engine.did_cache is False
    assert engine.is_game_running({0x12: 0x0}) is False


def test_sync_engine_detects_running():
    engine, _server = make_engine()
    assert engine.is_game_running({0x12: 0x5}) is True


def test_sync_engine_caches_on_first_running_tick():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)  # no sword
    server.set_ram(0x12, 0x5)  # running
    engine.check_first_running({0x0657: 0, 0x12: 0x5})
    assert engine.did_cache is True
    assert engine.cache[0x0657] == 0


def test_sync_engine_handle_table_writes_to_ram():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)
    engine.cache[0x0657] = 0
    sent_messages: list[str] = []
    msgs = engine.handle_table({"addr": 0x0657, "value": 1})
    server.step()
    assert server.ram[0x0657] == 1


def test_sync_engine_handle_table_emits_message():
    engine, server = make_engine()
    server.set_ram(0x0657, 0)
    engine.cache[0x0657] = 0
    msgs = engine.handle_table({"addr": 0x0657, "value": 1})
    assert any("Wood Sword" in m for m in msgs)


def test_sync_engine_resync_clears_cache():
    engine, _server = make_engine()
    engine.cache[0x0657] = 1
    engine.did_cache = True
    engine.resync()
    assert engine.did_cache is False
    assert engine.force_send is True
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_sync_engine.py -v
```

Expected: existing 9 still pass; 6 new FAIL with "SyncEngine not defined" or similar.

- [ ] **Step 3: Append SyncEngine class to bridge_core/sync_engine.py**

Append to `bridge_core/sync_engine.py`:

```python
from typing import Any
from bridge_core.cc_client import CCClient


class SyncEngine:
    """Polling-based equivalent of GameDriver in driver.lua.

    Holds a cache of last-known RAM values for the mode's sync set, diffs each
    poll snapshot against it, runs record_changed, and either emits outgoing
    data frames (via the caller) or applies incoming ones (via cc_client).
    """

    def __init__(self, cc_client: CCClient, mode: Any) -> None:
        self.cc = cc_client
        self.mode = mode
        self.cache: dict[int, int] = {}
        self.did_cache = False
        self.force_send = False
        self.sleep_queue: list[dict] = []

    def is_game_running(self, snapshot: dict[int, int]) -> bool:
        return self.mode.is_running(snapshot)

    def check_first_running(self, snapshot: dict[int, int]) -> list[tuple[int, int]]:
        """Populate cache on the first running tick. If force_send is True,
        return a list of (addr, value) pairs to broadcast."""
        if self.did_cache:
            return []
        to_send: list[tuple[int, int]] = []
        for addr in self.mode.SYNC:
            value = snapshot.get(addr, 0)
            if addr not in self.cache:
                self.cache[addr] = value
            if self.force_send and value != 0:
                to_send.append((addr, value))
        self.did_cache = True
        return to_send

    def diff(self, snapshot: dict[int, int]) -> list[tuple[int, int, str | None]]:
        """For each watched address that changed since last poll, run
        record_changed (sending side). Returns list of (addr, send_value, message)
        for changes that should be transmitted."""
        out: list[tuple[int, int, str | None]] = []
        for addr, record in self.mode.SYNC.items():
            cur = snapshot.get(addr, 0)
            prev = self.cache.get(addr, cur)
            if cur == prev:
                continue
            allow, send_value = record_changed(record, cur, prev, receiving=False)
            if allow:
                self.cache[addr] = cur
                msg = self._build_send_message(record, cur, prev)
                out.append((addr, send_value, msg))
        return out

    def handle_table(self, t: dict) -> list[str]:
        """Apply a partner's data frame to RAM. Returns any user-visible messages."""
        addr = t.get("addr")
        if addr is None:
            return []
        record = self.mode.SYNC.get(addr)
        if record is None:
            return [f"Partner changed unknown address 0x{addr:04X}"]
        prev_bytes = self._read_ram_byte(addr)
        allow, value = record_changed(record, t["value"], prev_bytes, receiving=True)
        messages: list[str] = []
        if allow:
            self.cc.send_write_pairs([(addr, value & 0xFF)])
            self.cache[addr] = value & 0xFF
            # Receive trigger
            if "receive_trigger" in record:
                msg = record["receive_trigger"](value, prev_bytes)
                if msg:
                    messages.append(msg)
            # Function-kind messages
            elif "message" in record:
                msg = record["message"](value, prev_bytes)
                if msg:
                    messages.append(msg)
            # Single-name items
            elif "name" in record and value != prev_bytes:
                messages.append(f"Partner got {record['name']}")
            # Multi-name items
            elif "name_map" in record and value > 0 and value != prev_bytes:
                idx = value - 1
                if 0 <= idx < len(record["name_map"]):
                    messages.append(f"Partner got {record['name_map'][idx]}")
        return messages

    def resync(self) -> None:
        """Clear cache and arm force_send so the next running tick re-broadcasts state."""
        self.cache.clear()
        self.did_cache = False
        self.force_send = True

    # --- internals ---

    def _read_ram_byte(self, addr: int) -> int:
        """Synchronous read of a single byte for handle_table prior-value lookup."""
        self.cc.send_read_addrs([addr])
        result = self.cc.poll_response(timeout_ms=200)
        if result and len(result) >= 1:
            return result[0]
        return 0

    def _build_send_message(self, record: dict, cur: int, prev: int) -> str | None:
        """Local-side analog of handle_table's message construction (for the
        sending peer's own UI: 'You picked up Wood Sword')."""
        if "name" in record and cur > prev:
            return f"You got {record['name']}"
        if "name_map" in record and cur > prev:
            idx = cur - 1
            if 0 <= idx < len(record["name_map"]):
                return f"You got {record['name_map'][idx]}"
        return None
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_sync_engine.py -v
```

Expected: `15 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/sync_engine.py bridge/tests/test_sync_engine.py
git commit -m "feat(bridge): add SyncEngine class (poll/cache/handleTable/resync)"
```

---

## Phase 4: Pipe client

### Task 10: Mock socket fixture

**Files:**
- Create: `bridge/tests/mock_socket.py`

- [ ] **Step 1: Implement the mock**

Create `bridge/tests/mock_socket.py`:

```python
"""Paired in-memory mock for socket.socket — for unit tests of pipe_client."""
from __future__ import annotations

from collections import deque


class MockSocketPair:
    """Two MockSockets that share buffers cross-wise.

    Use mock_pair() to create a pair where what side A writes is readable by B
    and vice versa.
    """

    def __init__(self) -> None:
        self.a_to_b: deque[int] = deque()
        self.b_to_a: deque[int] = deque()
        self.a_closed = False
        self.b_closed = False


class MockSocket:
    def __init__(self, pair: MockSocketPair, side: str) -> None:
        self._pair = pair
        self._side = side  # "a" or "b"
        self._timeout: float | None = 0.0
        self._closed = False

    def settimeout(self, t: float | None) -> None:
        self._timeout = t

    def setblocking(self, blocking: bool) -> None:
        self._timeout = None if blocking else 0.0

    def send(self, data: bytes) -> int:
        if self._closed:
            raise OSError("socket closed")
        if self._side == "a":
            if self._pair.b_closed:
                raise OSError("peer closed")
            self._pair.a_to_b.extend(data)
        else:
            if self._pair.a_closed:
                raise OSError("peer closed")
            self._pair.b_to_a.extend(data)
        return len(data)

    def recv(self, n: int) -> bytes:
        if self._closed:
            raise OSError("socket closed")
        buf = self._pair.b_to_a if self._side == "a" else self._pair.a_to_b
        peer_closed = self._pair.b_closed if self._side == "a" else self._pair.a_closed
        if not buf:
            if peer_closed:
                return b""
            if self._timeout == 0.0:
                # Non-blocking: would block → raise as pyserial does
                import errno
                raise BlockingIOError(errno.EAGAIN, "would block")
            return b""
        out = bytearray()
        for _ in range(min(n, len(buf))):
            out.append(buf.popleft())
        return bytes(out)

    def close(self) -> None:
        self._closed = True
        if self._side == "a":
            self._pair.a_closed = True
        else:
            self._pair.b_closed = True


def mock_pair() -> tuple[MockSocket, MockSocket]:
    pair = MockSocketPair()
    return MockSocket(pair, "a"), MockSocket(pair, "b")
```

- [ ] **Step 2: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/tests/mock_socket.py
git commit -m "test(bridge): add MockSocket fixture"
```

---

### Task 11: Length-prefix JSON framing

**Files:**
- Create: `bridge/bridge_core/pipe_client.py` (initial — just framing helpers)
- Create: `bridge/tests/test_pipe_client.py`

- [ ] **Step 1: Write the failing tests**

Create `bridge/tests/test_pipe_client.py`:

```python
import json
import struct

import pytest

from bridge_core import pipe_client

from .mock_socket import mock_pair


def test_encode_frame_format():
    raw = pipe_client.encode_frame({"kind": "hello", "v": 1})
    length = int.from_bytes(raw[:4], "big")
    body = raw[4:].decode()
    assert json.loads(body) == {"kind": "hello", "v": 1}
    assert length == len(body)


def test_decode_full_frame():
    raw = pipe_client.encode_frame({"kind": "ping"})
    decoded, consumed = pipe_client.try_decode_frame(raw)
    assert decoded == {"kind": "ping"}
    assert consumed == len(raw)


def test_decode_partial_frame_returns_none():
    raw = pipe_client.encode_frame({"kind": "ping"})
    decoded, consumed = pipe_client.try_decode_frame(raw[:5])
    assert decoded is None
    assert consumed == 0


def test_decode_oversized_frame_raises():
    # Header claims 1 MB
    raw = (1024 * 1024).to_bytes(4, "big") + b"x"
    with pytest.raises(pipe_client.WireError):
        pipe_client.try_decode_frame(raw)


def test_decode_invalid_json_raises():
    raw = (4).to_bytes(4, "big") + b"badd"
    with pytest.raises(pipe_client.WireError):
        pipe_client.try_decode_frame(raw)
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: ImportError / FAIL.

- [ ] **Step 3: Implement framing in `bridge_core/pipe_client.py`**

Create `bridge_core/pipe_client.py`:

```python
"""Pipe client — Python equivalent of pipe_relay.lua + pipe.lua's RelayPipe.

This module's first commit ships only the framing helpers; the connection
state machine (hello/heartbeat/reconnect) comes in subsequent tasks.
"""
from __future__ import annotations

import json


MAX_PAYLOAD = 4096


class WireError(Exception):
    pass


def encode_frame(obj: dict) -> bytes:
    payload = json.dumps(obj).encode()
    if len(payload) > MAX_PAYLOAD:
        raise WireError(f"frame too large: {len(payload)} > {MAX_PAYLOAD}")
    return len(payload).to_bytes(4, "big") + payload


def try_decode_frame(buf: bytes) -> tuple[dict | None, int]:
    """Returns (decoded_frame_or_None, bytes_consumed).

    If buf doesn't yet contain a full frame, returns (None, 0). On oversized
    or malformed JSON, raises WireError.
    """
    if len(buf) < 4:
        return None, 0
    length = int.from_bytes(buf[:4], "big")
    if length > MAX_PAYLOAD:
        raise WireError(f"frame too large: {length}")
    if len(buf) < 4 + length:
        return None, 0
    payload = buf[4:4 + length]
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as e:
        raise WireError(f"malformed JSON: {e}")
    return obj, 4 + length
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/pipe_client.py bridge/tests/test_pipe_client.py
git commit -m "feat(bridge): add length-prefix JSON framing"
```

---

### Task 12: PipeClient connection + hello handshake

**Files:**
- Modify: `bridge/bridge_core/pipe_client.py`
- Modify: `bridge/tests/test_pipe_client.py`

- [ ] **Step 1: Add PipeClient hello tests**

Append to `bridge/tests/test_pipe_client.py`:

```python
from bridge_core.pipe_client import PipeClient, PROTOCOL_VERSION

from .mock_socket import mock_pair


def test_pipe_client_sends_join_on_open():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    # Drain partner_sock and decode
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    decoded, _ = pipe_client.try_decode_frame(bytes(raw))
    assert decoded == {"kind": "join", "code": "abcdef", "peer_id": "p1"}


def test_pipe_client_handles_joined_then_sends_hello():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    # Drain join
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    # Partner sends "joined"
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    # Tick the pipe
    for _ in range(5):
        pipe.tick()
    # Now bridge should have sent hello
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    decoded, _ = pipe_client.try_decode_frame(bytes(raw))
    assert decoded == {"kind": "hello", "v": PROTOCOL_VERSION}


def test_pipe_client_reaches_established_after_partner_hello():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    for _ in range(5):
        pipe.tick()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    # Partner sends hello
    partner_sock.send(pipe_client.encode_frame({"kind": "hello", "v": PROTOCOL_VERSION}))
    for _ in range(5):
        pipe.tick()
    assert pipe.state == "ESTABLISHED"


def test_pipe_client_aborts_on_version_mismatch():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    pipe.send_join()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "joined"}))
    for _ in range(5):
        pipe.tick()
    while True:
        try:
            partner_sock.recv(1024)
        except BlockingIOError:
            break
    partner_sock.send(pipe_client.encode_frame({"kind": "hello", "v": 999}))
    for _ in range(5):
        pipe.tick()
    assert pipe.state == "FAILED"
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: ImportError on `PipeClient`. New tests FAIL.

- [ ] **Step 3: Add PipeClient class to bridge_core/pipe_client.py**

Append to `bridge_core/pipe_client.py`:

```python
PROTOCOL_VERSION = 1


class PipeClient:
    """Python equivalent of RelayPipe in pipe_relay.lua.

    States: INIT → CONNECTING → JOIN_SENT → JOINED → HELLO_SENT → ESTABLISHED
                                                                ↓
                                                           FAILED / RECONNECTING
    """

    def __init__(self, socket, code: str, peer_id: str) -> None:
        self._sock = socket
        self.code = code
        self.peer_id = peer_id
        self.state = "INIT"
        self._rx_buf = bytearray()
        self._hello_sent = False
        self._hello_received = False
        self._joined = False
        # Frame handlers receive raw frames before state-machine routing
        self.on_data: callable | None = None
        self.on_partner_reconnected: callable | None = None
        self.on_abort: callable | None = None

    def send_join(self) -> None:
        self.state = "JOIN_SENT"
        self._send_frame({"kind": "join", "code": self.code, "peer_id": self.peer_id})

    def send_hello(self) -> None:
        if self._hello_sent:
            return
        self._hello_sent = True
        self.state = "HELLO_SENT"
        self._send_frame({"kind": "hello", "v": PROTOCOL_VERSION})

    def send_data(self, body: dict) -> None:
        if self.state != "ESTABLISHED":
            return
        self._send_frame({"kind": "data", "body": body})

    def abort(self, reason: str) -> None:
        self._send_frame({"kind": "abort", "reason": reason})
        self._fail(f"Aborted: {reason}")

    def tick(self) -> None:
        if self.state in ("FAILED", "CLOSED"):
            return
        # Drain any pending bytes
        try:
            chunk = self._sock.recv(4096)
            if chunk:
                self._rx_buf += chunk
            elif self.state in ("ESTABLISHED", "HELLO_SENT", "JOINED"):
                # Peer closed
                self._fail("Connection lost")
                return
        except BlockingIOError:
            pass
        except OSError:
            self._fail("Connection lost")
            return
        # Process whole frames
        while True:
            try:
                frame, consumed = try_decode_frame(bytes(self._rx_buf))
            except WireError as e:
                self._fail(f"Wire protocol error: {e}")
                return
            if frame is None:
                break
            del self._rx_buf[:consumed]
            self._handle_frame(frame)
            if self.state in ("FAILED", "CLOSED"):
                return

    def _handle_frame(self, frame: dict) -> None:
        kind = frame.get("kind")
        if kind == "joined":
            if not self._joined:
                self._joined = True
                self.state = "JOINED"
                self.send_hello()
        elif kind == "hello":
            if self._hello_received:
                self._fail("duplicate hello")
                return
            if frame.get("v") != PROTOCOL_VERSION:
                self._send_frame({"kind": "abort", "reason": "version mismatch"})
                self._fail(f"Partner version mismatch: v={frame.get('v')}, expected v={PROTOCOL_VERSION}")
                return
            self._hello_received = True
            if self._hello_sent and self.state != "ESTABLISHED":
                self.state = "ESTABLISHED"
        elif kind == "data":
            if self.state == "ESTABLISHED" and self.on_data:
                self.on_data(frame.get("body", {}))
        elif kind == "ping":
            self._send_frame({"kind": "pong"})
        elif kind == "pong":
            pass
        elif kind == "abort":
            reason = frame.get("reason", "unknown")
            if self.on_abort:
                self.on_abort(reason)
            self._fail(f"Partner aborted: {reason}")
        elif kind == "partner-reconnected":
            self._hello_sent = False
            self._hello_received = False
            self.state = "JOINED"
            self.send_hello()
            if self.on_partner_reconnected:
                self.on_partner_reconnected()

    def _send_frame(self, obj: dict) -> None:
        try:
            self._sock.send(encode_frame(obj))
        except OSError:
            self._fail("send failed")

    def _fail(self, msg: str) -> None:
        if self.state in ("FAILED", "CLOSED"):
            return
        self.state = "FAILED"
        try:
            self._sock.close()
        except Exception:
            pass

    def close(self) -> None:
        self.state = "CLOSED"
        try:
            self._sock.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/pipe_client.py bridge/tests/test_pipe_client.py
git commit -m "feat(bridge): add PipeClient with hello state machine"
```

---

### Task 13: Heartbeat

**Files:**
- Modify: `bridge/bridge_core/pipe_client.py`
- Modify: `bridge/tests/test_pipe_client.py`

- [ ] **Step 1: Add heartbeat tests**

Append to `bridge/tests/test_pipe_client.py`:

```python
def test_heartbeat_sends_ping_after_interval():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Advance clock past 5s interval
    pipe._clock = lambda: 5.1
    pipe.heartbeat_tick()
    raw = bytearray()
    while True:
        try:
            chunk = partner_sock.recv(1024)
            if not chunk:
                break
            raw += chunk
        except BlockingIOError:
            break
    frame, _ = pipe_client.try_decode_frame(bytes(raw))
    assert frame == {"kind": "ping"}


def test_heartbeat_fails_after_timeout():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Advance past 15s timeout
    pipe._clock = lambda: 15.5
    pipe.heartbeat_tick()
    assert pipe.state == "FAILED"


def test_heartbeat_does_not_fail_with_recent_traffic():
    bridge_sock, partner_sock = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._init_heartbeat()
    # Simulate inbound traffic (resets _last_rx)
    pipe._clock = lambda: 10.0
    pipe._last_rx = 10.0
    pipe._clock = lambda: 20.0  # 10s after last RX, well under 15s timeout
    pipe.heartbeat_tick()
    assert pipe.state == "ESTABLISHED"
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: 9 pass; 3 new FAIL on missing `clock` parameter or `_init_heartbeat`.

- [ ] **Step 3: Add heartbeat to PipeClient**

In `bridge_core/pipe_client.py`, modify the `__init__` and add new methods:

```python
HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0
```

Modify the `__init__` signature to accept an optional clock:

```python
    def __init__(self, socket, code: str, peer_id: str, clock=None) -> None:
        import time
        self._sock = socket
        self.code = code
        self.peer_id = peer_id
        self.state = "INIT"
        self._rx_buf = bytearray()
        self._hello_sent = False
        self._hello_received = False
        self._joined = False
        self._clock = clock or time.monotonic
        self._last_rx = self._clock()
        self._last_ping = self._clock()
        self.on_data: callable | None = None
        self.on_partner_reconnected: callable | None = None
        self.on_abort: callable | None = None
```

Add an `_init_heartbeat()` method (called when entering ESTABLISHED — but since tests directly call it, expose it):

```python
    def _init_heartbeat(self) -> None:
        self._last_rx = self._clock()
        self._last_ping = self._clock()

    def heartbeat_tick(self) -> None:
        if self.state not in ("ESTABLISHED", "HELLO_SENT"):
            return
        now = self._clock()
        if (now - self._last_rx) > HEARTBEAT_TIMEOUT:
            self._fail("Connection lost (heartbeat timeout)")
            return
        if (now - self._last_ping) > HEARTBEAT_INTERVAL:
            self._send_frame({"kind": "ping"})
            self._last_ping = now
```

In `_handle_frame`, at the very top, add:

```python
        # Any received frame resets the liveness timer
        self._last_rx = self._clock()
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: `12 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/pipe_client.py bridge/tests/test_pipe_client.py
git commit -m "feat(bridge): add heartbeat (ping/pong + 15s silence timeout)"
```

---

### Task 14: Reconnect machinery

**Files:**
- Modify: `bridge/bridge_core/pipe_client.py`
- Modify: `bridge/tests/test_pipe_client.py`

- [ ] **Step 1: Add reconnect tests**

Append to `bridge/tests/test_pipe_client.py`:

```python
def test_fail_with_reconnect_enabled_goes_to_reconnecting():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1", clock=lambda: 0.0)
    pipe.state = "ESTABLISHED"
    pipe._reconnect_enabled = True
    pipe._fail("test failure")
    assert pipe.state == "RECONNECTING"


def test_backoff_sequence():
    bridge_sock, _ = mock_pair()
    pipe = PipeClient(socket=bridge_sock, code="abcdef", peer_id="p1")
    expected = [1, 2, 4, 8, 16, 30, 30, 30]
    for want in expected:
        assert pipe._next_backoff() == want
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: 12 pass; 2 new FAIL.

- [ ] **Step 3: Add reconnect machinery**

In `bridge_core/pipe_client.py`:

Add at module level:

```python
BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 30]
```

Modify `__init__` to add reconnect state:

```python
        self._reconnect_enabled = False
        self._reconnect_attempt = 0
        self._next_retry_at: float | None = None
        self._post_reconnect = False
```

Modify `_fail` to honor reconnect-enabled:

```python
    def _fail(self, msg: str) -> None:
        if self.state in ("FAILED", "CLOSED"):
            return
        try:
            self._sock.close()
        except Exception:
            pass
        if self._reconnect_enabled:
            self.state = "RECONNECTING"
            self._next_retry_at = self._clock() + self._next_backoff()
        else:
            self.state = "FAILED"
```

Add the new method:

```python
    def _next_backoff(self) -> int:
        attempt = self._reconnect_attempt
        self._reconnect_attempt += 1
        if attempt < len(BACKOFF_SCHEDULE):
            return BACKOFF_SCHEDULE[attempt]
        return 30
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_pipe_client.py -v
```

Expected: `14 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/pipe_client.py bridge/tests/test_pipe_client.py
git commit -m "feat(bridge): add reconnect state machine + backoff schedule"
```

---

## Phase 5: CLI wire-up

### Task 15: Status sink interface + console implementation

**Files:**
- Create: `bridge/bridge_core/status_sink.py`
- Create: `bridge/tests/test_status_sink.py`

- [ ] **Step 1: Write the failing tests**

Create `bridge/tests/test_status_sink.py`:

```python
from bridge_core.status_sink import ConsoleStatusSink, StatusSink, MultiSink


def test_console_status_sink_prints_to_capsys(capsys):
    sink = ConsoleStatusSink()
    sink.message("Partner got Wood Sword")
    sink.log("connected to relay", level="INFO")
    sink.state("CONNECTED")
    captured = capsys.readouterr()
    assert "Wood Sword" in captured.out
    assert "connected to relay" in captured.out


def test_multi_sink_dispatches_to_all_subscribers():
    captured: list[str] = []

    class Capture(StatusSink):
        def message(self, text: str) -> None:
            captured.append(("message", text))

        def log(self, text: str, level: str = "INFO") -> None:
            captured.append(("log", text))

        def state(self, state: str) -> None:
            captured.append(("state", state))

    cap1 = Capture()
    cap2 = Capture()
    multi = MultiSink([cap1, cap2])
    multi.message("hi")
    assert captured.count(("message", "hi")) == 2
```

- [ ] **Step 2: Run tests to verify red**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_status_sink.py -v
```

Expected: ImportError / FAIL.

- [ ] **Step 3: Implement status_sink**

Create `bridge_core/status_sink.py`:

```python
"""Pluggable status sink. GUI subscribes; CLI prints; tests capture."""
from __future__ import annotations

import time
from typing import Protocol


class StatusSink(Protocol):
    def message(self, text: str) -> None: ...
    def log(self, text: str, level: str = "INFO") -> None: ...
    def state(self, state: str) -> None: ...


class ConsoleStatusSink:
    """Prints to stdout. Useful for CLI use and tests."""

    def message(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {text}", flush=True)

    def log(self, text: str, level: str = "INFO") -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {text}", flush=True)

    def state(self, state: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] state -> {state}", flush=True)


class MultiSink:
    """Fan-out to multiple sinks."""

    def __init__(self, sinks: list[StatusSink]) -> None:
        self._sinks = sinks

    def message(self, text: str) -> None:
        for s in self._sinks:
            s.message(text)

    def log(self, text: str, level: str = "INFO") -> None:
        for s in self._sinks:
            s.log(text, level)

    def state(self, state: str) -> None:
        for s in self._sinks:
            s.state(state)
```

- [ ] **Step 4: Run tests to verify green**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/test_status_sink.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_core/status_sink.py bridge/tests/test_status_sink.py
git commit -m "feat(bridge): add StatusSink interface + ConsoleStatusSink"
```

---

### Task 16: CLI entry point + wire-up

**Files:**
- Create: `bridge/bridge_cli/__main__.py`

- [ ] **Step 1: Implement the CLI**

Create `bridge/bridge_cli/__main__.py`:

```python
"""CLI entry point for the bridge.

Usage:
  python -m bridge_cli run --mode tloz_all --port COM3 --code mycode \
                            [--relay coop.z1rracing.com] [--relay-port 9999]
                            [--force-send]
  python -m bridge_cli patch <input.nes> -o <output.nes>
  python -m bridge_cli read --port COM3 --addr 0x0657 --length 16
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
import uuid
from importlib import import_module
from pathlib import Path

import serial

from bridge_core import ips
from bridge_core.cc_client import CCClient
from bridge_core.pipe_client import PipeClient
from bridge_core.status_sink import ConsoleStatusSink
from bridge_core.sync_engine import SyncEngine

POLL_HZ = 10
POLL_PERIOD = 1.0 / POLL_HZ


def cmd_patch(args: argparse.Namespace) -> int:
    src = Path(args.input).read_bytes()
    patch_path = Path(__file__).parent.parent / "bridge_core" / "patches" / "zelda_cc.ips"
    patch_bytes = patch_path.read_bytes()
    if ips.is_patched(src, patch_bytes):
        print(f"Already patched: {args.input}")
        if args.output:
            Path(args.output).write_bytes(src)
        return 0
    out = ips.apply(src, patch_bytes)
    out_path = args.output or args.input.replace(".nes", "_CC.nes")
    Path(out_path).write_bytes(out)
    print(f"Patched: {args.input} -> {out_path}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    cc = CCClient(sp)
    cc.send_read_array(args.addr, args.length)
    result = cc.poll_response(timeout_ms=500)
    if result is None:
        print("timeout", file=sys.stderr)
        return 1
    print(" ".join(f"{b:02X}" for b in result))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    sink = ConsoleStatusSink()
    sink.log(f"Loading mode: {args.mode}")
    mode = import_module(f"bridge_core.modes.{args.mode}")

    sink.log(f"Opening serial port {args.port} @ {args.baud}")
    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    cc = CCClient(sp)

    sink.log(f"Connecting to relay {args.relay}:{args.relay_port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((args.relay, args.relay_port))
    sock.setblocking(False)

    peer_id = uuid.uuid4().hex
    pipe = PipeClient(socket=sock, code=args.code, peer_id=peer_id)
    pipe._reconnect_enabled = True

    engine = SyncEngine(cc_client=cc, mode=mode)
    if args.force_send:
        engine.force_send = True
        sink.log("force_send enabled")

    pipe.on_data = lambda body: _on_data(engine, sink, body)
    pipe.on_abort = lambda reason: sink.message(f"Partner aborted: {reason}")
    pipe.on_partner_reconnected = lambda: engine.resync()
    pipe.send_join()

    # App-level hello (after pipe ESTABLISHED)
    app_hello_sent = False
    sink.state("CONNECTING")

    try:
        while pipe.state not in ("FAILED", "CLOSED"):
            loop_start = time.monotonic()

            pipe.tick()
            pipe.heartbeat_tick()

            if pipe.state == "ESTABLISHED" and not app_hello_sent:
                pipe.send_data({"op": "hello", "guid": mode.GUID, "version": "0.1.0"})
                app_hello_sent = True
                sink.state("ESTABLISHED")

            if pipe.state == "ESTABLISHED":
                # Poll the running register
                cc.send_read_addrs([mode.RUNNING_ADDR])
                running_byte = cc.poll_response(timeout_ms=200)
                if running_byte and len(running_byte) >= 1:
                    snapshot = {mode.RUNNING_ADDR: running_byte[0]}
                    if engine.is_game_running(snapshot):
                        # Read the full sync set
                        addrs = sorted(mode.SYNC.keys())
                        cc.send_read_addrs(addrs)
                        values = cc.poll_response(timeout_ms=500)
                        if values and len(values) == len(addrs):
                            full_snapshot = {addr: values[i] for i, addr in enumerate(addrs)}
                            full_snapshot[mode.RUNNING_ADDR] = running_byte[0]
                            if not engine.did_cache:
                                to_send = engine.check_first_running(full_snapshot)
                                for addr, value in to_send:
                                    pipe.send_data({"addr": addr, "value": value})
                            for addr, send_value, msg in engine.diff(full_snapshot):
                                pipe.send_data({"addr": addr, "value": send_value})
                                if msg:
                                    sink.message(msg)
                    else:
                        if engine.did_cache:
                            sink.log("Game stopped running; pausing sync")
                            engine.did_cache = False

            elapsed = time.monotonic() - loop_start
            sleep = POLL_PERIOD - elapsed
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        sink.log("Interrupted by user")

    pipe.close()
    sp.close()
    sock.close()
    sink.state("DISCONNECTED")
    return 0 if pipe.state != "FAILED" else 1


def _on_data(engine: SyncEngine, sink: ConsoleStatusSink, body: dict) -> None:
    if body.get("op") == "hello":
        if body.get("guid") != engine.mode.GUID:
            sink.message(f"Partner has incompatible mode: {body.get('guid')}")
            return
        sink.log(f"Partner's app hello OK (guid={body['guid']}, version={body.get('version')})")
        return
    messages = engine.handle_table(body)
    for m in messages:
        sink.message(m)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_patch = sub.add_parser("patch", help="Apply CC IPS patch to a ROM")
    p_patch.add_argument("input")
    p_patch.add_argument("-o", "--output")

    p_read = sub.add_parser("read", help="One-shot RAM read for diagnostics")
    p_read.add_argument("--port", required=True)
    p_read.add_argument("--baud", type=int, default=115200)
    p_read.add_argument("--addr", type=lambda s: int(s, 0), required=True)
    p_read.add_argument("--length", type=int, default=1)

    p_run = sub.add_parser("run", help="Run the bridge: connect to relay and sync game state")
    p_run.add_argument("--mode", required=True, help="Mode module name, e.g. tloz_all")
    p_run.add_argument("--port", required=True, help="Serial port (e.g. COM3)")
    p_run.add_argument("--baud", type=int, default=115200)
    p_run.add_argument("--code", required=True, help="Session code (6+ chars)")
    p_run.add_argument("--relay", default="coop.z1rracing.com")
    p_run.add_argument("--relay-port", type=int, default=9999)
    p_run.add_argument("--force-send", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "patch":
        return cmd_patch(args)
    elif args.cmd == "read":
        return cmd_read(args)
    elif args.cmd == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test the CLI**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_cli --help
python -m bridge_cli patch --help
python -m bridge_cli run --help
```

All three should print help text without errors.

- [ ] **Step 3: Run all tests**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/ -v
```

Expected: all green (still 14 + 9 + 8 + 15 + 5 + 6 + 2 = 59 ish, depending on count).

- [ ] **Step 4: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_cli/__main__.py
git commit -m "feat(bridge): add CLI entry point with patch/read/run subcommands"
```

---

### Task 17: Manual hardware smoke test (USER-DRIVEN)

**Files:** None (manual checkpoint)

This task is for the user. Verify the CLI bridge works end-to-end with real hardware against the OCI relay.

- [ ] **Step 1: Setup**

Have ready:
- A NES with EDN8 plugged in
- A Z1R seed ROM file
- The bridge code installed via `pip install -e bridge[test]` from the repo

- [ ] **Step 2: Patch the ROM**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_cli patch "C:\path\to\zelda_seed.nes" -o "C:\path\to\zelda_seed_CC.nes"
```

Should print: `Patched: ... -> .._CC.nes`. Copy the output ROM to the EDN8's SD card via Windows Explorer (USB mass storage mode).

- [ ] **Step 3: Identify the COM port**

After plugging in the EDN8, find the assigned COM port:

```powershell
Get-PnpDevice -Class Ports | Format-Table -AutoSize
```

Or use Device Manager → Ports (COM & LPT). Note the COM number (e.g., COM3).

- [ ] **Step 4: Run the bridge against OCI relay**

```powershell
python -m bridge_cli run --mode tloz_all --port COM3 --code testbridge1 --relay coop.z1rracing.com
```

You should see:
- "Loading mode: tloz_all"
- "Opening serial port COM3..."
- "Connecting to relay..."
- "state -> CONNECTING"

The bridge will hold in WAITING for a partner.

- [ ] **Step 5: Connect a FCEUX peer**

In FCEUX, load the same Z1R seed (unpatched is fine for FCEUX), load coop.lua, set transport=Relay, host=coop.z1rracing.com, port=9999, code=`testbridge1`.

Both should pair within 1 second. Bridge logs "state -> ESTABLISHED".

- [ ] **Step 6: Test sync**

Launch the patched ROM on the EDN8 (via the cart's menu). Walk into the wood sword cave on the NES. Pick up the sword. The FCEUX peer should display "Partner got Wood Sword" within ~1 second.

Pick up an item on the FCEUX side; the NES inventory should update via the bridge writing to RAM.

- [ ] **Step 7: Document outcomes**

Append a section to `bridge/docs/cc-patch-capabilities.md`:

```markdown
## CLI smoke test — <DATE>

- ROM: <Z1R seed name>
- Cart: <model + firmware>
- Result: <PASS/FAIL>
- Observations: <bandwidth at 10Hz, item-pickup latency, anything weird>
```

- [ ] **Step 8: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/docs/cc-patch-capabilities.md
git commit -m "docs(bridge): record CLI smoke test results"
```

---

## Phase 6: GUI

### Task 18: GUI app skeleton + screen navigation

**Files:**
- Create: `bridge/bridge_gui/__main__.py`
- Create: `bridge/bridge_gui/app.py`

- [ ] **Step 1: Create app shell**

Create `bridge/bridge_gui/app.py`:

```python
"""CustomTkinter app shell with screen navigation."""
from __future__ import annotations

import customtkinter as ctk


class BridgeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("emu-coop bridge")
        self.geometry("700x500")
        self.minsize(600, 400)

        self._screens: dict[str, ctk.CTkFrame] = {}
        self._current_screen: ctk.CTkFrame | None = None

        # Will be registered by individual screen modules in later tasks
        self._register_screens()
        self.show_screen("rom_setup")

    def _register_screens(self) -> None:
        from bridge_gui.setup_screen import ROMSetupScreen
        from bridge_gui.relay_setup_screen import RelaySetupScreen
        from bridge_gui.session_screen import SessionScreen

        self._screens["rom_setup"] = ROMSetupScreen(self, controller=self)
        self._screens["relay_setup"] = RelaySetupScreen(self, controller=self)
        self._screens["session"] = SessionScreen(self, controller=self)

    def show_screen(self, name: str) -> None:
        if self._current_screen is not None:
            self._current_screen.pack_forget()
        screen = self._screens[name]
        screen.pack(fill="both", expand=True, padx=20, pady=20)
        self._current_screen = screen
        # Each screen can react to becoming visible
        if hasattr(screen, "on_show"):
            screen.on_show()
```

- [ ] **Step 2: Create entry point**

Create `bridge/bridge_gui/__main__.py`:

```python
"""GUI entry point.

Usage: python -m bridge_gui
"""
from bridge_gui.app import BridgeApp


def main() -> None:
    ctk_init()
    app = BridgeApp()
    app.mainloop()


def ctk_init() -> None:
    import customtkinter as ctk
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add stub screens (will be filled in later tasks)**

Create `bridge/bridge_gui/setup_screen.py`:

```python
import customtkinter as ctk


class ROMSetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="ROM Setup (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Continue → Relay Setup", command=self._continue).pack(pady=10)

    def _continue(self) -> None:
        self.controller.show_screen("relay_setup")
```

Create `bridge/bridge_gui/relay_setup_screen.py`:

```python
import customtkinter as ctk


class RelaySetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="Relay Setup (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Connect → Session", command=self._connect).pack(pady=10)
        ctk.CTkButton(self, text="← Back to ROM Setup", command=self._back).pack(pady=5)

    def _connect(self) -> None:
        self.controller.show_screen("session")

    def _back(self) -> None:
        self.controller.show_screen("rom_setup")
```

Create `bridge/bridge_gui/session_screen.py`:

```python
import customtkinter as ctk


class SessionScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="Session (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Disconnect → Relay Setup", command=self._disconnect).pack(pady=10)

    def _disconnect(self) -> None:
        self.controller.show_screen("relay_setup")
```

- [ ] **Step 4: Smoke-test the GUI loads**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

A window should open showing "ROM Setup (placeholder)" with a "Continue" button. Click through all three screens to verify navigation. Close the window.

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_gui/
git commit -m "feat(bridge): add GUI app shell with screen navigation"
```

---

### Task 19: ROM Setup screen

**Files:**
- Modify: `bridge/bridge_gui/setup_screen.py`

- [ ] **Step 1: Replace the placeholder with the real screen**

Overwrite `bridge/bridge_gui/setup_screen.py`:

```python
"""ROM Setup screen: pick a ROM, optionally apply CC patch, optionally upload to EDN8."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from bridge_core import ips


class ROMSetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        self._rom_path: Path | None = None
        self._patched_path: Path | None = None

        ctk.CTkLabel(
            self,
            text="ROM Setup",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            self,
            text="Choose your Z1 ROM (vanilla or Z1R seed).\n"
                 "We'll apply the CC patch if it's not already patched.",
            justify="center",
        ).pack(pady=(0, 20))

        self._file_label = ctk.CTkLabel(self, text="(no file selected)", wraplength=500)
        self._file_label.pack(pady=10)

        ctk.CTkButton(self, text="Browse...", command=self._pick_file).pack(pady=10)

        self._status_label = ctk.CTkLabel(self, text="", wraplength=500, text_color="gray")
        self._status_label.pack(pady=10)

        self._continue_btn = ctk.CTkButton(
            self,
            text="Continue",
            state="disabled",
            command=self._continue,
        )
        self._continue_btn.pack(pady=20)

    def _pick_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Choose Z1 ROM",
            filetypes=[("NES ROMs", "*.nes"), ("All files", "*.*")],
        )
        if not filename:
            return
        self._rom_path = Path(filename)
        self._file_label.configure(text=str(self._rom_path))
        self._inspect_rom()

    def _inspect_rom(self) -> None:
        assert self._rom_path is not None
        try:
            rom_bytes = self._rom_path.read_bytes()
        except OSError as e:
            self._status_label.configure(text=f"Error reading file: {e}", text_color="red")
            self._continue_btn.configure(state="disabled")
            return
        if len(rom_bytes) < 16 or rom_bytes[:4] != b"NES\x1a":
            self._status_label.configure(text="This doesn't look like a NES ROM (.nes header missing).", text_color="red")
            self._continue_btn.configure(state="disabled")
            return
        patch_bytes = self._load_patch()
        if ips.is_patched(rom_bytes, patch_bytes):
            self._status_label.configure(text="✓ ROM is already patched. Ready.", text_color="green")
            self._patched_path = self._rom_path
        else:
            self._status_label.configure(
                text=f"ROM is not patched. Will save as <name>_CC.nes when you click Continue.",
                text_color="gray",
            )
            self._patched_path = None
        self._continue_btn.configure(state="normal")

    def _continue(self) -> None:
        assert self._rom_path is not None
        rom_bytes = self._rom_path.read_bytes()
        patch_bytes = self._load_patch()
        if not ips.is_patched(rom_bytes, patch_bytes):
            patched = ips.apply(rom_bytes, patch_bytes)
            out_path = self._rom_path.with_name(self._rom_path.stem + "_CC.nes")
            out_path.write_bytes(patched)
            self._patched_path = out_path
            self._status_label.configure(text=f"✓ Patched and saved: {out_path.name}", text_color="green")
        # Stash the patched path on the controller for later screens
        self.controller.patched_rom_path = self._patched_path
        self.controller.show_screen("relay_setup")

    @staticmethod
    def _load_patch() -> bytes:
        path = files("bridge_core").joinpath("patches/zelda_cc.ips")
        return path.read_bytes()
```

- [ ] **Step 2: Manual smoke-test**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

- Click Browse, pick any `.nes` file. Status should reflect patched/unpatched.
- Pick a non-NES file (e.g. a `.txt`). Should show error.
- With a valid ROM, click Continue. Should advance to Relay Setup screen.

- [ ] **Step 3: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_gui/setup_screen.py
git commit -m "feat(bridge): implement ROM Setup screen (file picker, IPS detection)"
```

---

### Task 20: Relay Setup screen

**Files:**
- Modify: `bridge/bridge_gui/relay_setup_screen.py`

- [ ] **Step 1: Implement the screen**

Overwrite `bridge/bridge_gui/relay_setup_screen.py`:

```python
"""Relay Setup: mode + relay address + session code + COM port + force_send."""
from __future__ import annotations

import customtkinter as ctk
import serial.tools.list_ports


AVAILABLE_MODES = ["tloz_all"]  # extend as more modes are ported
DEFAULT_RELAY = "coop.z1rracing.com"
DEFAULT_RELAY_PORT = 9999


class RelaySetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller

        ctk.CTkLabel(
            self,
            text="Relay Setup",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(20, 10))

        form = ctk.CTkFrame(self)
        form.pack(pady=20, padx=40, fill="x")

        # Mode
        ctk.CTkLabel(form, text="Mode:").grid(row=0, column=0, sticky="e", padx=10, pady=8)
        self._mode_var = ctk.StringVar(value=AVAILABLE_MODES[0])
        ctk.CTkOptionMenu(form, variable=self._mode_var, values=AVAILABLE_MODES).grid(
            row=0, column=1, sticky="w", padx=10, pady=8
        )

        # Relay
        ctk.CTkLabel(form, text="Relay address:").grid(row=1, column=0, sticky="e", padx=10, pady=8)
        self._relay_var = ctk.StringVar(value=DEFAULT_RELAY)
        ctk.CTkEntry(form, textvariable=self._relay_var, width=200).grid(
            row=1, column=1, sticky="w", padx=10, pady=8
        )

        # Port
        ctk.CTkLabel(form, text="Relay port:").grid(row=2, column=0, sticky="e", padx=10, pady=8)
        self._port_var = ctk.StringVar(value=str(DEFAULT_RELAY_PORT))
        ctk.CTkEntry(form, textvariable=self._port_var, width=80).grid(
            row=2, column=1, sticky="w", padx=10, pady=8
        )

        # Session code
        ctk.CTkLabel(form, text="Session code:").grid(row=3, column=0, sticky="e", padx=10, pady=8)
        self._code_var = ctk.StringVar()
        self._code_entry = ctk.CTkEntry(form, textvariable=self._code_var, width=200)
        self._code_entry.grid(row=3, column=1, sticky="w", padx=10, pady=8)
        self._code_var.trace_add("write", lambda *_: self._update_connect_state())

        # COM port
        ctk.CTkLabel(form, text="COM port:").grid(row=4, column=0, sticky="e", padx=10, pady=8)
        com_ports = self._detect_com_ports()
        self._com_var = ctk.StringVar(value=com_ports[0] if com_ports else "")
        ctk.CTkOptionMenu(
            form,
            variable=self._com_var,
            values=com_ports if com_ports else ["(none detected)"],
        ).grid(row=4, column=1, sticky="w", padx=10, pady=8)

        # Force send
        self._force_send_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            form,
            text="Resending all my state on connect (after a crash)",
            variable=self._force_send_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=8)

        # Status text
        self._status_label = ctk.CTkLabel(self, text="", text_color="red", wraplength=500)
        self._status_label.pack(pady=5)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=20)

        ctk.CTkButton(btn_row, text="← Back", command=self._back).pack(side="left", padx=5)
        self._connect_btn = ctk.CTkButton(
            btn_row,
            text="Connect",
            command=self._connect,
            state="disabled",
        )
        self._connect_btn.pack(side="left", padx=5)

    def _detect_com_ports(self) -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def _update_connect_state(self) -> None:
        code = self._code_var.get().strip()
        ok = len(code) >= 6 and len(self._com_var.get()) > 0 and self._com_var.get() != "(none detected)"
        self._connect_btn.configure(state="normal" if ok else "disabled")

    def _back(self) -> None:
        self.controller.show_screen("rom_setup")

    def _connect(self) -> None:
        # Validate port number
        try:
            port = int(self._port_var.get())
        except ValueError:
            self._status_label.configure(text="Port must be a number")
            return
        # Stash session config on the controller
        self.controller.session_config = {
            "mode": self._mode_var.get(),
            "relay": self._relay_var.get(),
            "relay_port": port,
            "code": self._code_var.get().strip(),
            "com_port": self._com_var.get(),
            "force_send": self._force_send_var.get(),
        }
        self.controller.show_screen("session")

    def on_show(self) -> None:
        # Re-detect COM ports each time (user may have plugged in cart)
        com_ports = self._detect_com_ports()
        if com_ports and self._com_var.get() not in com_ports:
            self._com_var.set(com_ports[0])
        self._update_connect_state()
```

- [ ] **Step 2: Smoke-test**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

Navigate ROM Setup → Relay Setup. Verify:
- Mode dropdown shows "tloz_all"
- Relay defaults populated correctly
- Session code Connect button stays disabled until 6+ chars
- COM port auto-detects (or "(none detected)" if no serial devices)

- [ ] **Step 3: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_gui/relay_setup_screen.py
git commit -m "feat(bridge): implement Relay Setup screen with COM port detection"
```

---

### Task 21: Session screen

**Files:**
- Modify: `bridge/bridge_gui/session_screen.py`

- [ ] **Step 1: Implement the screen**

Overwrite `bridge/bridge_gui/session_screen.py`:

```python
"""Session: live status panel with two readiness indicators + Log/Messages tabs."""
from __future__ import annotations

import customtkinter as ctk

from bridge_core.status_sink import StatusSink


class SessionScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller

        ctk.CTkLabel(
            self,
            text="Session",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(10, 5))

        # Readiness indicators row
        indicators = ctk.CTkFrame(self, fg_color="transparent")
        indicators.pack(pady=10, padx=20, fill="x")

        # Cart panel
        cart_panel = ctk.CTkFrame(indicators)
        cart_panel.pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkLabel(cart_panel, text="Cart connection", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 0))
        self._cart_usb_label = ctk.CTkLabel(cart_panel, text="USB: ⚫ disconnected")
        self._cart_usb_label.pack(pady=2)
        self._cart_game_label = ctk.CTkLabel(cart_panel, text="Game: ⚫ unknown")
        self._cart_game_label.pack(pady=(2, 8))

        # Network panel
        net_panel = ctk.CTkFrame(indicators)
        net_panel.pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkLabel(net_panel, text="Network connection", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 0))
        self._net_relay_label = ctk.CTkLabel(net_panel, text="Relay: ⚫ disconnected")
        self._net_relay_label.pack(pady=2)
        self._net_partner_label = ctk.CTkLabel(net_panel, text="Partner: ⚫ unpaired")
        self._net_partner_label.pack(pady=(2, 8))

        # Sync state
        self._sync_label = ctk.CTkLabel(self, text="Sync: ⚫ IDLE", font=ctk.CTkFont(size=14, weight="bold"))
        self._sync_label.pack(pady=10)

        # Tabs
        self._tabs = ctk.CTkTabview(self, height=250)
        self._tabs.pack(pady=10, padx=20, fill="both", expand=True)
        self._tabs.add("Messages")
        self._tabs.add("Log")
        self._tabs.set("Messages")

        # Messages textbox
        self._messages_text = ctk.CTkTextbox(self._tabs.tab("Messages"), state="disabled")
        self._messages_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Log textbox
        self._log_text = ctk.CTkTextbox(self._tabs.tab("Log"), state="disabled")
        self._log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Disconnect button
        ctk.CTkButton(self, text="Disconnect", command=self._disconnect).pack(pady=10)

    def on_show(self) -> None:
        # The actual session worker is wired up in Task 22
        self._append_log("Entered Session screen")

    def _disconnect(self) -> None:
        # Confirmation will be added when worker exists in Task 22
        self.controller.show_screen("relay_setup")

    # --- StatusSink-style methods (called by worker thread via after()) ---

    def message(self, text: str) -> None:
        self._append_messages(text)

    def log(self, text: str, level: str = "INFO") -> None:
        self._append_log(f"[{level}] {text}")

    def state(self, state: str) -> None:
        self._append_log(f"state -> {state}")
        # Update the sync label color/text based on state
        color = {"ESTABLISHED": "green", "RECONNECTING": "orange", "DISCONNECTED": "red"}.get(state, "gray")
        self._sync_label.configure(text=f"Sync: {state}", text_color=color)

    def update_cart_usb(self, connected: bool) -> None:
        self._cart_usb_label.configure(text=f"USB: {'🟢 connected' if connected else '🔴 disconnected'}")

    def update_cart_game(self, running: bool) -> None:
        self._cart_game_label.configure(text=f"Game: {'🟢 running' if running else '🟡 not running'}")

    def update_net_relay(self, connected: bool) -> None:
        self._net_relay_label.configure(text=f"Relay: {'🟢 connected' if connected else '⚫ disconnected'}")

    def update_net_partner(self, paired: bool) -> None:
        self._net_partner_label.configure(text=f"Partner: {'🟢 paired' if paired else '🟡 unpaired'}")

    # --- internals ---

    def _append_messages(self, text: str) -> None:
        import time as _t
        ts = _t.strftime("%H:%M:%S")
        self._messages_text.configure(state="normal")
        self._messages_text.insert("end", f"[{ts}] {text}\n")
        self._messages_text.see("end")
        self._messages_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        import time as _t
        ts = _t.strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] {text}\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
```

- [ ] **Step 2: Smoke-test**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

Navigate to Session screen. Verify:
- Two readiness panels render (Cart, Network)
- Tabs switch between Messages and Log
- Disconnect button returns to Relay Setup

- [ ] **Step 3: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_gui/session_screen.py
git commit -m "feat(bridge): implement Session screen with two-readiness indicators + tabs"
```

---

### Task 22: Wire SyncEngine + PipeClient into the Session screen

**Files:**
- Create: `bridge/bridge_gui/session_worker.py`
- Modify: `bridge/bridge_gui/session_screen.py`

- [ ] **Step 1: Create the session worker**

Create `bridge/bridge_gui/session_worker.py`:

```python
"""Worker thread that drives the bridge during a session.

Runs the same loop as bridge_cli.cmd_run, but emits events to a thread-safe
queue that the GUI consumes via tkinter's after() callback.
"""
from __future__ import annotations

import queue
import socket
import threading
import time
import uuid
from importlib import import_module
from typing import Any

import serial

from bridge_core.cc_client import CCClient
from bridge_core.pipe_client import PipeClient
from bridge_core.sync_engine import SyncEngine


class SessionEvent:
    """Tagged event passed from worker to GUI thread."""

    def __init__(self, kind: str, **kwargs: Any) -> None:
        self.kind = kind
        self.data = kwargs


class SessionWorker:
    POLL_HZ = 10
    POLL_PERIOD = 1.0 / POLL_HZ

    def __init__(self, config: dict, event_queue: queue.Queue) -> None:
        self._config = config
        self._events = event_queue
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _emit(self, kind: str, **kwargs: Any) -> None:
        self._events.put(SessionEvent(kind, **kwargs))

    def _run(self) -> None:
        cfg = self._config
        try:
            self._emit("log", text=f"Loading mode: {cfg['mode']}")
            mode = import_module(f"bridge_core.modes.{cfg['mode']}")

            self._emit("log", text=f"Opening serial port {cfg['com_port']}")
            sp = serial.Serial(cfg["com_port"], baudrate=115200, timeout=0)
            cc = CCClient(sp)
            self._emit("cart_usb", connected=True)

            self._emit("log", text=f"Connecting to relay {cfg['relay']}:{cfg['relay_port']}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((cfg["relay"], cfg["relay_port"]))
            sock.setblocking(False)

            peer_id = uuid.uuid4().hex
            pipe = PipeClient(socket=sock, code=cfg["code"], peer_id=peer_id)
            pipe._reconnect_enabled = True
            engine = SyncEngine(cc_client=cc, mode=mode)
            if cfg.get("force_send"):
                engine.force_send = True

            pipe.on_data = lambda body: self._on_data(engine, body)
            pipe.on_abort = lambda reason: self._emit("message", text=f"Partner aborted: {reason}")
            pipe.on_partner_reconnected = lambda: engine.resync()
            pipe.send_join()
            self._emit("net_relay", connected=True)

            app_hello_sent = False

            while not self._stop_flag.is_set() and pipe.state not in ("FAILED", "CLOSED"):
                loop_start = time.monotonic()
                pipe.tick()
                pipe.heartbeat_tick()

                if pipe.state == "ESTABLISHED" and not app_hello_sent:
                    pipe.send_data({"op": "hello", "guid": mode.GUID, "version": "0.1.0"})
                    app_hello_sent = True
                    self._emit("net_partner", paired=True)
                    self._emit("state", state="ESTABLISHED")

                if pipe.state == "ESTABLISHED":
                    cc.send_read_addrs([mode.RUNNING_ADDR])
                    running_byte = cc.poll_response(timeout_ms=200)
                    if running_byte and len(running_byte) >= 1:
                        snapshot = {mode.RUNNING_ADDR: running_byte[0]}
                        running = engine.is_game_running(snapshot)
                        self._emit("cart_game", running=running)
                        if running:
                            addrs = sorted(mode.SYNC.keys())
                            cc.send_read_addrs(addrs)
                            values = cc.poll_response(timeout_ms=500)
                            if values and len(values) == len(addrs):
                                full_snapshot = {addr: values[i] for i, addr in enumerate(addrs)}
                                full_snapshot[mode.RUNNING_ADDR] = running_byte[0]
                                if not engine.did_cache:
                                    to_send = engine.check_first_running(full_snapshot)
                                    for addr, value in to_send:
                                        pipe.send_data({"addr": addr, "value": value})
                                for addr, send_value, msg in engine.diff(full_snapshot):
                                    pipe.send_data({"addr": addr, "value": send_value})
                                    if msg:
                                        self._emit("message", text=msg)
                        else:
                            if engine.did_cache:
                                self._emit("log", text="Game stopped running; pausing sync")
                                engine.did_cache = False

                elapsed = time.monotonic() - loop_start
                sleep = self.POLL_PERIOD - elapsed
                if sleep > 0:
                    time.sleep(sleep)

            pipe.close()
            sp.close()
            sock.close()
            self._emit("state", state="DISCONNECTED")
        except Exception as e:
            self._emit("log", text=f"ERROR: {e}", level="ERROR")
            self._emit("state", state="FAILED")

    def _on_data(self, engine: SyncEngine, body: dict) -> None:
        if body.get("op") == "hello":
            if body.get("guid") != engine.mode.GUID:
                self._emit("message", text=f"Partner has incompatible mode (guid mismatch)")
                return
            self._emit("log", text=f"Partner app hello OK (guid={body['guid']})")
            return
        for msg in engine.handle_table(body):
            self._emit("message", text=msg)
```

- [ ] **Step 2: Wire the worker into SessionScreen**

Modify `bridge/bridge_gui/session_screen.py` — replace the `on_show` and `_disconnect` methods, and add a new poll method:

```python
    def on_show(self) -> None:
        from bridge_gui.session_worker import SessionWorker
        import queue

        config = getattr(self.controller, "session_config", None)
        if config is None:
            self._append_log("ERROR: no session config on controller")
            return
        self._event_queue = queue.Queue()
        self._worker = SessionWorker(config, self._event_queue)
        self._worker.start()
        self._poll_events()

    def _poll_events(self) -> None:
        while True:
            try:
                ev = self._event_queue.get_nowait()
            except Exception:
                break
            self._handle_event(ev)
        # Schedule next poll (10 Hz)
        self._poll_after_id = self.after(100, self._poll_events)

    def _handle_event(self, ev) -> None:
        kind = ev.kind
        d = ev.data
        if kind == "message":
            self.message(d["text"])
        elif kind == "log":
            self.log(d["text"], d.get("level", "INFO"))
        elif kind == "state":
            self.state(d["state"])
        elif kind == "cart_usb":
            self.update_cart_usb(d["connected"])
        elif kind == "cart_game":
            self.update_cart_game(d["running"])
        elif kind == "net_relay":
            self.update_net_relay(d["connected"])
        elif kind == "net_partner":
            self.update_net_partner(d["paired"])

    def _disconnect(self) -> None:
        if hasattr(self, "_worker"):
            self._worker.stop()
        if hasattr(self, "_poll_after_id"):
            self.after_cancel(self._poll_after_id)
        self.controller.show_screen("relay_setup")
```

- [ ] **Step 3: Smoke-test (no hardware)**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

Navigate ROM → Relay → Session. With NO hardware connected, the session screen should show error in Log "ERROR: ... [Errno 2] could not open port COM3" or similar — that's fine. Click Disconnect; should return to Relay Setup.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/ -v
```

Expected: all tests pass (the session_worker isn't unit-tested yet, but the unit tests for individual components still pass).

- [ ] **Step 5: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge_gui/session_worker.py bridge/bridge_gui/session_screen.py
git commit -m "feat(bridge): wire SyncEngine + PipeClient into Session screen via worker thread"
```

---

### Task 23: Manual GUI smoke test (USER-DRIVEN)

**Files:** None (manual checkpoint)

This task is for the user. Verify the GUI works end-to-end with real hardware.

- [ ] **Step 1: Launch the GUI**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
python -m bridge_gui
```

- [ ] **Step 2: ROM Setup**

Browse to a Z1R seed `.nes`. Verify status reflects unpatched/patched correctly. Click Continue.

- [ ] **Step 3: Relay Setup**

Verify defaults populated. Enter session code (6+ chars). Pick the COM port the EDN8 is on. Click Connect.

- [ ] **Step 4: Session — observe live state**

Should show:
- Cart USB: 🟢
- Cart Game: 🟡 (until ROM is launched on cart)
- Relay: 🟢 (after a moment)
- Partner: 🟡 (until partner joins)

In FCEUX, connect a Z1 peer with the same session code via the Relay transport. Within ~1s, both should pair:
- Network Partner: 🟢
- Sync state: ESTABLISHED

Launch the patched ROM on the EDN8. After getting in-game:
- Cart Game: 🟢 running
- Sync: ACTIVE

Pick up wood sword on the NES; the FCEUX peer should receive it. Vice versa.

- [ ] **Step 5: Test Disconnect**

Click Disconnect on the bridge GUI. Should return to Relay Setup. The FCEUX peer should see "Partner aborted" and disconnect.

- [ ] **Step 6: Document outcome**

Append to `bridge/docs/cc-patch-capabilities.md`:

```markdown
## GUI smoke test — <DATE>

- Result: <PASS/FAIL>
- Anything weird: <list>
```

- [ ] **Step 7: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/docs/cc-patch-capabilities.md
git commit -m "docs(bridge): record GUI smoke test results"
```

---

## Phase 7: Distribution

### Task 24: PyInstaller spec + Windows .exe build

**Files:**
- Create: `bridge/bridge.spec`
- Create: `bridge/build-windows.ps1`

- [ ] **Step 1: Create the PyInstaller spec**

Create `bridge/bridge.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bridge.exe (Windows-first)."""

from pathlib import Path

block_cipher = None

a = Analysis(
    ['bridge_gui/__main__.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('bridge_core/patches/zelda_cc.ips', 'bridge_core/patches'),
    ],
    hiddenimports=[
        'bridge_core.modes.tloz_all',  # imported dynamically
        'serial.tools.list_ports_windows',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 2: Create the Windows build script**

Create `bridge/build-windows.ps1`:

```powershell
# Builds the bridge as a single Windows .exe via PyInstaller.
# Usage: powershell -ExecutionPolicy Bypass -File .\build-windows.ps1

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

# Ensure dev/dist deps are installed in current Python env
python -m pip install -e ".[test,dist]" --quiet

# Run PyInstaller
python -m PyInstaller bridge.spec --clean

$exe = Join-Path $PSScriptRoot "dist\bridge.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Built: $exe ($size MB)"
} else {
    Write-Error "Build failed — bridge.exe not found"
    exit 1
}

Pop-Location
```

- [ ] **Step 3: Build the .exe**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

Expected output: `Built: ...\bridge.exe (XX.X MB)`. Target is under 30 MB.

- [ ] **Step 4: Smoke-test the .exe**

Double-click `bridge\dist\bridge.exe` (or run from PowerShell). The GUI should launch identically to `python -m bridge_gui`.

- [ ] **Step 5: Add dist/ to gitignore**

Append to `bridge/.gitignore`:

```
dist/
build/
*.spec.bak
```

(May already be present from earlier task; verify and skip if so.)

- [ ] **Step 6: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/bridge.spec bridge/build-windows.ps1 bridge/.gitignore
git commit -m "feat(bridge): add PyInstaller spec + Windows build script"
```

---

### Task 25: Manual distribution smoke test (USER-DRIVEN)

**Files:** None (manual checkpoint)

This is the final hardware test. Verify the bundled `.exe` works on a fresh machine.

- [ ] **Step 1: Build a clean copy**

```powershell
cd D:\Projects\Streaming\z1rr-coop\bridge
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

- [ ] **Step 2: Test on a "clean" Windows environment**

Ideally, run on a Windows machine that does NOT have Python installed (e.g., a Hyper-V VM, or a friend's laptop). Copy `bridge\dist\bridge.exe` over and double-click.

If you don't have a clean machine handy, at minimum verify that the `.exe` is self-contained by:
1. Renaming your local Python install temporarily (or running from a path where it's not in the PATH)
2. Running `bridge.exe` and confirming it still launches

- [ ] **Step 3: End-to-end with hardware**

Same as Task 23 (GUI smoke), but using `bridge.exe` instead of `python -m bridge_gui`.

- [ ] **Step 4: Document in a release notes file**

Create or append `bridge/dist/RELEASE_NOTES.md` (note: `dist/` is gitignored; this is a local artifact for your reference):

```markdown
# bridge.exe v0.1.0 release smoke test

- Built: <DATE>
- Built on: Windows <version>, Python <version>
- Bundle size: <XX MB>
- Test result: <PASS/FAIL>
- Tested with: <ROM, partner setup>
- Notes: <any quirks>
```

No commit for this step (release notes stay local).

---

## Phase 8: Polish

### Task 26: bridge/README.md end-user docs

**Files:**
- Create: `bridge/README.md`

- [ ] **Step 1: Write the README**

Create `bridge/README.md`:

```markdown
# emu-coop bridge

Connect a real NES + Everdrive Pro N8 to emu-coop sessions, alongside FCEUX peers.

## What this is

A Windows app (with macOS support best-effort) that:
- Patches a Z1 ROM with the CC USB protocol
- Uploads it to your EDN8 (or you can copy manually)
- Talks to the cart over USB serial to read/write game memory
- Connects to the emu-coop relay on the internet
- Pairs with a partner running FCEUX (or another bridge)
- Syncs items, dungeon progress, and other game state in real time

## Quick start

1. **Download `bridge.exe`** (single file, ~25 MB).
2. **Plug in your EDN8** to a USB port.
3. **Run `bridge.exe`** — it walks you through:
   - Picking your Z1 ROM (vanilla or Z1R seed; both work)
   - Auto-detecting your EDN8's COM port
   - Choosing a session code (any 6+ char string you and your partner agree on)
   - Connecting to the relay
4. **Launch the patched ROM** on your NES via the EDN8 menu.
5. **Play co-op.**

## Modes

The bridge currently supports `tloz_all` (Zelda 1, syncs items + map progress).
Both peers must select the same mode. Future modes will be added by porting from
the FCEUX-side `modes/*.lua` files.

## CLI usage (advanced)

If you don't want the GUI:

```powershell
# Patch a ROM
python -m bridge_cli patch zelda.nes -o zelda_CC.nes

# Run a session
python -m bridge_cli run --mode tloz_all --port COM3 --code mycode
```

## Troubleshooting

### "Could not open COM port"

EDN8 isn't plugged in, or another program is holding the port. Close any other
program using the cart and click Connect again.

### "Partner has incompatible mode (guid mismatch)"

You and your partner picked different modes. Both peers must use the same mode
(e.g., both `tloz_all`).

### "Connection lost (heartbeat timeout)"

Network drop. Bridge auto-reconnects with exponential backoff. Should recover
within ~30 seconds when the network is back.

### My inventory shows a phantom Heart Container or bomb upgrade

This is a known emu-coop quirk (not specific to the bridge). When you and your
partner connect on the title screen and then start a new game, the cache snapshot
can race ahead of the game's initial inventory writes. Workaround: load a save
state of an already-running game on both peers before connecting.

## Development

See `bridge/README.md` (this file) plus the architectural design at
`docs/superpowers/specs/2026-05-06-edn8-bridge-design.md`.

To set up for development:

```powershell
cd bridge
python -m pip install -e ".[test,dist]"
python -m pytest tests/ -v
python -m bridge_gui  # run the GUI
python -m bridge_cli --help  # CLI options
```

To build a Windows distributable:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
# Output: dist/bridge.exe
```
```

- [ ] **Step 2: Commit**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add bridge/README.md
git commit -m "docs(bridge): add end-user README"
```

---

### Task 27: Top-level README + version bump

**Files:**
- Modify: `README.md`
- Modify: `version.lua`

- [ ] **Step 1: Read top-level README**

```powershell
cd D:\Projects\Streaming\z1rr-coop
type README.md
```

- [ ] **Step 2: Add bridge section**

Edit `README.md`. Add a new section after the existing "Connection modes" section:

```markdown
## EDN8 hardware bridge

If you want to play emu-coop on a real NES with an [Everdrive Pro N8](https://krikzz.com/store/home/55-everdrive-n8-pro-nes.html)
instead of an emulator, see [bridge/README.md](bridge/README.md). Same OCI relay,
same session-code workflow, same Z1 modes — just with a USB cable to the cart
instead of FCEUX.
```

- [ ] **Step 3: Bump release version**

Edit `version.lua`. Change `release = "1.3"` to `release = "1.4"` (this isn't strictly required for the bridge, but it marks a meaningful release point).

- [ ] **Step 4: Run all tests as a final regression check**

```powershell
cd D:\Projects\Streaming\z1rr-coop
C:\Users\bogie\AppData\Local\Programs\LuaJIT\bin\luajit.exe tests/run.lua tests/test_json.lua tests/test_mock_socket.lua tests/test_frame.lua tests/test_handshake.lua tests/test_pipe_direct.lua tests/test_heartbeat.lua tests/test_reconnect.lua tests/test_driver_resync.lua tests/test_pipe_relay.lua

cd D:\Projects\Streaming\z1rr-coop\relay
python -m pytest tests/ --timeout=15

cd D:\Projects\Streaming\z1rr-coop\bridge
python -m pytest tests/ --timeout=15
```

Expected: 27 Lua + 6 Python (relay) + ~50 Python (bridge). All green.

- [ ] **Step 5: Commit and push**

```powershell
cd D:\Projects\Streaming\z1rr-coop
git add README.md version.lua
git commit -m "docs: link to bridge from top-level README; bump to 1.4"
git push origin stable
```

---

## Verification checklist

After all phases complete:

- [ ] `lua tests/run.lua tests/test_*.lua` — 27 passes (Lua client side, unchanged)
- [ ] `cd relay && python -m pytest tests/ --timeout=15` — 6 passes + 1 skip (relay daemon, unchanged)
- [ ] `cd bridge && python -m pytest tests/ --timeout=15` — all bridge unit tests pass
- [ ] `python -m bridge_gui` opens the GUI; navigation works
- [ ] `bridge.exe` (PyInstaller bundle) under 30 MB and works on a clean Windows machine
- [ ] Real-hardware end-to-end: bridge ↔ FCEUX peer ↔ OCI relay → items sync both ways
- [ ] CC patch capabilities documented in `bridge/docs/cc-patch-capabilities.md`
- [ ] Top-level README points to bridge/README.md
- [ ] Version bumped to 1.4 in version.lua
