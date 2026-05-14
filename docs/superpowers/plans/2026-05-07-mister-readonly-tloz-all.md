# MiSTer Read-Only tloz_all Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first MiSTer-facing z1rr-coop milestone: `tloz_all` can run through the Python bridge against a generic memory endpoint, with a read-only MiSTer endpoint able to produce outgoing sync frames.

**Architecture:** Decouple `SyncEngine` and the session loops from `CCClient` by introducing a small `MemoryEndpoint` interface. Keep EDN8 behavior working through a `CCMemoryEndpoint` adapter, then add a read-only MiSTer memory endpoint scaffold and a diagnostic/sender path that feeds `tloz_all` snapshots into the existing sync engine.

**Tech Stack:** Python 3.10+, pytest, existing `bridge_core` modules, odelot MiSTer DDRAM mirror design notes.

---

## Scope

This plan intentionally stops before custom NES-core HDL writes. The target is a one-way path:

`MiSTer read mirror -> Python SyncEngine.diff(tloz_all) -> relay frame payloads`

The first proof can use fake/captured MiSTer mirror data. Real MiSTer `/dev/mem` support can be added behind the same endpoint after the interface is stable.

## File Structure

- Create `bridge/bridge_core/memory_endpoint.py`
  - Defines the memory endpoint protocol and shared helpers for `read_ranges`, `read_byte`, and `write_pairs`.
- Create `bridge/bridge_core/cc_endpoint.py`
  - Wraps existing `CCClient` in the generic endpoint interface.
- Modify `bridge/bridge_core/sync_engine.py`
  - Replace direct `CCClient` dependency with `MemoryEndpoint`.
  - Use `endpoint.read_byte()` and `endpoint.write_pairs()` in receive handling.
- Modify `bridge/bridge_cli/__main__.py`
  - Use `CCMemoryEndpoint` for existing EDN8 commands.
  - Add the smallest CLI shape for future endpoint selection only after tests cover the refactor.
- Modify `bridge/bridge_gui/session_worker.py`
  - Use `CCMemoryEndpoint` for current GUI sessions.
- Create `bridge/bridge_core/mister_endpoint.py`
  - Starts with a testable read-only endpoint that consumes a mirror provider object or bytes-like source.
  - Raises a clear `NotImplementedError` for `write_pairs()` until HDL write support exists.
- Create `bridge/tests/test_memory_endpoint.py`
  - Unit tests for the endpoint protocol helpers and fake endpoint behavior.
- Create `bridge/tests/test_cc_endpoint.py`
  - Tests that `CCMemoryEndpoint` preserves existing `CCClient` read/write behavior through `MockCCServer`.
- Create `bridge/tests/test_mister_endpoint.py`
  - Tests read-only MiSTer snapshot behavior against synthetic mirror data.
- Modify `bridge/tests/test_sync_engine.py`
  - Change existing tests to construct `SyncEngine(endpoint=..., mode=tloz_all)`.
  - Add read-only send-path coverage for `tloz_all`.

---

### Task 1: Memory Endpoint Interface

**Files:**
- Create: `bridge/bridge_core/memory_endpoint.py`
- Test: `bridge/tests/test_memory_endpoint.py`

- [ ] **Step 1: Write failing tests for endpoint helper semantics**

Add tests that define the API from the consumer side:

```python
from bridge_core.memory_endpoint import DictMemoryEndpoint


def test_dict_endpoint_reads_ranges_as_address_map():
    endpoint = DictMemoryEndpoint({0x0012: 0x05, 0x0657: 0x01})

    snapshot = endpoint.read_ranges([(0x0012, 1), (0x0657, 1)])

    assert snapshot == {0x0012: 0x05, 0x0657: 0x01}


def test_dict_endpoint_reads_single_byte():
    endpoint = DictMemoryEndpoint({0x0657: 0x02})

    assert endpoint.read_byte(0x0657) == 0x02


def test_dict_endpoint_write_pairs_updates_memory():
    endpoint = DictMemoryEndpoint({0x0657: 0x00})

    assert endpoint.write_pairs([(0x0657, 0x01)]) is True
    assert endpoint.read_byte(0x0657) == 0x01
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_memory_endpoint.py -v
```

Expected: FAIL because `bridge_core.memory_endpoint` does not exist.

- [ ] **Step 3: Implement the minimal endpoint module**

Create `bridge/bridge_core/memory_endpoint.py`:

```python
"""Generic memory endpoint interface for non-Lua emu-coop clients."""
from __future__ import annotations

from typing import Protocol


class MemoryEndpoint(Protocol):
    def read_ranges(self, ranges: list[tuple[int, int]], timeout_ms: int = 300) -> dict[int, int] | None: ...
    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None: ...
    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool: ...
    def close(self) -> None: ...


class DictMemoryEndpoint:
    """In-memory endpoint for unit tests and dry-run prototypes."""

    def __init__(self, memory: dict[int, int] | None = None) -> None:
        self.memory = dict(memory or {})

    def read_ranges(self, ranges: list[tuple[int, int]], timeout_ms: int = 300) -> dict[int, int] | None:
        snapshot: dict[int, int] = {}
        for base, length in ranges:
            for offset in range(length):
                addr = base + offset
                snapshot[addr] = self.memory.get(addr, 0)
        return snapshot

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        return self.memory.get(addr, 0)

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        for addr, value in pairs:
            self.memory[addr] = value & 0xFF
        return True

    def close(self) -> None:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_memory_endpoint.py -v
```

Expected: PASS.

---

### Task 2: CC Endpoint Adapter

**Files:**
- Create: `bridge/bridge_core/cc_endpoint.py`
- Test: `bridge/tests/test_cc_endpoint.py`

- [ ] **Step 1: Write failing tests for `CCMemoryEndpoint`**

```python
from bridge_core.cc_client import CCClient
from bridge_core.cc_endpoint import CCMemoryEndpoint

from .mock_cc_server import MockCCServer


def test_cc_endpoint_reads_ranges_through_cc_client():
    server = MockCCServer()
    server.set_ram(0x0012, 0x05)
    server.set_ram(0x0657, 0x01)
    endpoint = CCMemoryEndpoint(CCClient(server.serial))

    endpoint._client.send_read_array = endpoint._client.send_read_array
    result = endpoint.read_ranges([(0x0012, 1)], timeout_ms=300)
    server.step()

    # If this direct call shape is awkward, adapt the test to use a helper
    # that steps the mock server between send and poll.
    assert result == {0x0012: 0x05}


def test_cc_endpoint_write_pairs_updates_cart_ram():
    server = MockCCServer()
    endpoint = CCMemoryEndpoint(CCClient(server.serial))

    assert endpoint.write_pairs([(0x0657, 0x01)]) is True
    server.step()

    assert server.ram[0x0657] == 0x01
```

If the synchronous read test cannot pass because `MockCCServer.step()` must run between send and poll, introduce a test-only `SteppingCCMemoryEndpoint` subclass or use `CCClient` tests as the lower-level coverage and keep `CCMemoryEndpoint` tests focused on write forwarding.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_cc_endpoint.py -v
```

Expected: FAIL because `bridge_core.cc_endpoint` does not exist.

- [ ] **Step 3: Implement `CCMemoryEndpoint`**

```python
"""MemoryEndpoint adapter for the EDN8 Crowd Control USB client."""
from __future__ import annotations

from bridge_core.cc_client import CCClient


class CCMemoryEndpoint:
    def __init__(self, client: CCClient) -> None:
        self._client = client

    def read_ranges(self, ranges: list[tuple[int, int]], timeout_ms: int = 300) -> dict[int, int] | None:
        return self._client.read_ranges(ranges, timeout_ms=timeout_ms)

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        self._client.send_read_addrs([addr])
        result = self._client.poll_response(timeout_ms=timeout_ms)
        if result and len(result) >= 1:
            return result[0]
        return None

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        self._client.send_write_pairs(pairs)
        return True

    def close(self) -> None:
        self._client.close()
```

- [ ] **Step 4: Run adapter tests**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_cc_endpoint.py -v
```

Expected: PASS after any mock stepping adjustment.

---

### Task 3: SyncEngine Endpoint Refactor

**Files:**
- Modify: `bridge/bridge_core/sync_engine.py`
- Modify: `bridge/tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests that use `DictMemoryEndpoint`**

Change the test helper:

```python
from bridge_core.memory_endpoint import DictMemoryEndpoint


def make_engine(memory=None):
    endpoint = DictMemoryEndpoint(memory or {})
    engine = SyncEngine(endpoint=endpoint, mode=tloz_all)
    return engine, endpoint
```

Add a receive/write test:

```python
def test_sync_engine_handle_table_writes_through_endpoint():
    engine, endpoint = make_engine({0x0657: 0})

    msgs = engine.handle_table({"addr": 0x0657, "value": 1})

    assert endpoint.read_byte(0x0657) == 1
    assert any("Wood Sword" in m for m in msgs)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_sync_engine.py -v
```

Expected: FAIL because `SyncEngine.__init__` still accepts `cc_client`, not `endpoint`.

- [ ] **Step 3: Refactor `SyncEngine`**

Update constructor and internals:

```python
from bridge_core.memory_endpoint import MemoryEndpoint


class SyncEngine:
    def __init__(self, endpoint: MemoryEndpoint, mode: Any) -> None:
        self.endpoint = endpoint
        self.mode = mode
        ...

    def handle_table(self, t: dict) -> list[str]:
        ...
        prev = self.endpoint.read_byte(addr)
        if prev is None:
            return [f"Could not read address 0x{addr:04X}"]
        allow, value = record_changed(record, t["value"], prev, receiving=True)
        ...
        if allow:
            self.endpoint.write_pairs([(addr, value & 0xFF)])
            self.cache[addr] = value & 0xFF
```

Remove `_read_ram_byte()` or make it delegate to `self.endpoint.read_byte()`.

- [ ] **Step 4: Run sync-engine tests**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_sync_engine.py -v
```

Expected: PASS.

---

### Task 4: Keep EDN8 CLI/GUI Working Through Adapter

**Files:**
- Modify: `bridge/bridge_cli/__main__.py`
- Modify: `bridge/bridge_gui/session_worker.py`
- Test: existing bridge tests

- [ ] **Step 1: Write or update tests if constructor coverage exists**

Search existing tests for `SyncEngine(cc_client=` and update them to assert the new constructor shape. If there is no direct CLI/GUI unit coverage, rely on `test_sync_engine.py` plus import smoke.

Run:

```powershell
cd bridge
Select-String -Path bridge_core\*.py,bridge_cli\*.py,bridge_gui\*.py,tests\*.py -Pattern "SyncEngine\\("
```

- [ ] **Step 2: Update CLI**

In `bridge_cli/__main__.py`:

```python
from bridge_core.cc_endpoint import CCMemoryEndpoint
...
cc = CCClient(sp)
endpoint = CCMemoryEndpoint(cc)
engine = SyncEngine(endpoint=endpoint, mode=mode)
...
full_snapshot = endpoint.read_ranges(mode.READ_RANGES, timeout_ms=300)
```

- [ ] **Step 3: Update GUI session worker**

In `bridge_gui/session_worker.py`:

```python
from bridge_core.cc_endpoint import CCMemoryEndpoint
...
cc = CCClient(sp)
endpoint = CCMemoryEndpoint(cc)
engine = SyncEngine(endpoint=endpoint, mode=mode)
...
full_snapshot = endpoint.read_ranges(mode.READ_RANGES, timeout_ms=300)
```

- [ ] **Step 4: Run bridge tests**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_sync_engine.py tests/test_cc_client.py tests/test_modes_tloz_all.py -v
```

Expected: PASS.

---

### Task 5: Read-Only MiSTer Endpoint Scaffold

**Files:**
- Create: `bridge/bridge_core/mister_endpoint.py`
- Test: `bridge/tests/test_mister_endpoint.py`

- [ ] **Step 1: Write failing tests for synthetic MiSTer snapshots**

Start with an endpoint that accepts already-mapped memory bytes as a provider. This avoids `/dev/mem` in unit tests.

```python
import pytest

from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint


def test_mister_endpoint_reads_cpu_ram_ranges():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0657] = 0x01
    endpoint = ReadOnlyMisterMemoryEndpoint(cpu_ram=cpu_ram)

    assert endpoint.read_ranges([(0x0012, 1), (0x0657, 1)]) == {
        0x0012: 0x05,
        0x0657: 0x01,
    }


def test_mister_endpoint_is_read_only_until_write_channel_exists():
    endpoint = ReadOnlyMisterMemoryEndpoint(cpu_ram=bytearray(0x0800))

    with pytest.raises(NotImplementedError):
        endpoint.write_pairs([(0x0657, 0x01)])
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_endpoint.py -v
```

Expected: FAIL because `bridge_core.mister_endpoint` does not exist.

- [ ] **Step 3: Implement minimal read-only endpoint**

```python
"""Read-only MiSTer memory endpoint scaffold."""
from __future__ import annotations


class ReadOnlyMisterMemoryEndpoint:
    def __init__(self, cpu_ram: bytes | bytearray | memoryview) -> None:
        self._cpu_ram = memoryview(cpu_ram)

    def read_ranges(self, ranges: list[tuple[int, int]], timeout_ms: int = 300) -> dict[int, int] | None:
        snapshot: dict[int, int] = {}
        for base, length in ranges:
            for offset in range(length):
                addr = base + offset
                if 0 <= addr < len(self._cpu_ram):
                    snapshot[addr] = int(self._cpu_ram[addr])
                else:
                    snapshot[addr] = 0
        return snapshot

    def read_byte(self, addr: int, timeout_ms: int = 200) -> int | None:
        if 0 <= addr < len(self._cpu_ram):
            return int(self._cpu_ram[addr])
        return 0

    def write_pairs(self, pairs: list[tuple[int, int]]) -> bool:
        raise NotImplementedError("MiSTer writes require the custom NES core write channel")

    def close(self) -> None:
        return None
```

- [ ] **Step 4: Run MiSTer endpoint tests**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_endpoint.py -v
```

Expected: PASS.

---

### Task 6: tloz_all Read-Only Sender Test

**Files:**
- Modify: `bridge/tests/test_mister_endpoint.py` or create `bridge/tests/test_mister_tloz_all_sender.py`

- [ ] **Step 1: Write failing behavior test**

```python
from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint
from bridge_core.modes import tloz_all
from bridge_core.sync_engine import SyncEngine


def test_readonly_mister_tloz_all_emits_sword_pickup():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0657] = 0x00
    endpoint = ReadOnlyMisterMemoryEndpoint(cpu_ram=cpu_ram)
    engine = SyncEngine(endpoint=endpoint, mode=tloz_all)
    engine.check_first_running(endpoint.read_ranges(tloz_all.READ_RANGES))

    cpu_ram[0x0657] = 0x01
    changes = engine.diff(endpoint.read_ranges(tloz_all.READ_RANGES))

    assert (0x0657, 0x01, "You got Wood Sword") in changes
```

- [ ] **Step 2: Run test and verify failure if endpoint or constructor is missing**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_tloz_all_sender.py -v
```

Expected: FAIL until Tasks 3 and 5 are implemented.

- [ ] **Step 3: Implement minimal code already covered by earlier tasks**

No extra production code should be needed if `SyncEngine` and `ReadOnlyMisterMemoryEndpoint` are correct.

- [ ] **Step 4: Run sender test**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_tloz_all_sender.py -v
```

Expected: PASS.

---

### Task 7: Optional Diagnostic CLI Skeleton

**Files:**
- Modify: `bridge/bridge_cli/__main__.py`
- Test: optional CLI smoke or manual command help

- [ ] **Step 1: Decide whether to include this in the first implementation pass**

If staying strictly unit-test-only, skip this task. If useful for immediate hardware exploration, add:

```powershell
uv run python -m bridge_cli mister-read --help
```

The command should describe the future `/dev/mem` reader but can initially operate only on a synthetic/captured mirror file.

- [ ] **Step 2: Keep real `/dev/mem` access out of unit tests**

Do not add tests that require root or MiSTer hardware. Add a captured-frame parser later when real mirror samples exist.

---

## Final Verification

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_memory_endpoint.py tests/test_cc_endpoint.py tests/test_sync_engine.py tests/test_mister_endpoint.py tests/test_mister_tloz_all_sender.py tests/test_modes_tloz_all.py -v
```

Expected: all selected tests pass.

Then run broader bridge tests if time permits:

```powershell
cd bridge
uv run python -m pytest tests/ -v
```

Expected: all bridge tests pass.

## Handoff Notes

- Do not start HDL work in this phase.
- Do not apply the CC IPS patch for MiSTer.
- `tloz_all` is the test bed because it exercises inventory, progress, map flags, custom function-kind heart handling, and delta records.
- The first real MiSTer network milestone after this plan is one-way MiSTer-to-FCEUX sync using the read-only sender path.
