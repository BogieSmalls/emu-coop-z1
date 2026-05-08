# MiSTer Read-Only Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-way `tloz_all` MiSTer POC that sends MiSTer memory changes to the existing emu-coop relay without modifying the NES core.

**Architecture:** The MiSTer helper remains the only MiSTer-side process and exposes RA mirror reads. The PC-side runner uses `MisterHelperMemoryEndpoint`, `SyncEngine`, and `PipeClient` to poll MiSTer RAM and send relay `data` frames. Incoming partner writes are logged as unsupported until the custom NES-core write path exists.

**Tech Stack:** Python, existing bridge `PipeClient`, `SyncEngine`, `MemoryEndpoint`, odelot RA mirror helper, pytest.

---

### Task 1: Read-Only Session Driver

**Files:**
- Create: `bridge/bridge_core/readonly_session.py`
- Test: `bridge/tests/test_readonly_session.py`

- [x] **Step 1: Write failing tests**

Cover app hello, outgoing `tloz_all` diffs, and read-only incoming write handling.

- [x] **Step 2: Run focused test and verify failure**

Run: `uv run python -m pytest tests/test_readonly_session.py -v`

- [x] **Step 3: Implement minimal session driver**

Create `ReadOnlySyncSession` with `tick_once()` and `on_data()`.

- [x] **Step 4: Run focused test and verify pass**

Run: `uv run python -m pytest tests/test_readonly_session.py -v`

### Task 2: `mister-run` CLI Wiring

**Files:**
- Modify: `bridge/bridge_cli/__main__.py`
- Test: `bridge/tests/test_mister_cli.py`

- [x] **Step 1: Write failing CLI wiring test**

Verify `mister-run --mode tloz_all --mister-host ... --code ...` creates a helper endpoint and invokes the read-only runner.

- [x] **Step 2: Run focused test and verify failure**

Run: `uv run python -m pytest tests/test_mister_cli.py -v`

- [x] **Step 3: Implement `cmd_mister_run` and parser args**

Wire helper endpoint, relay socket, `PipeClient`, imported mode, and `ConsoleStatusSink`.

- [x] **Step 4: Run focused test and verify pass**

Run: `uv run python -m pytest tests/test_mister_cli.py -v`

### Task 3: Verification

**Files:**
- No new files.

- [x] **Step 1: Run focused MiSTer tests**

Run: `uv run python -m pytest tests/test_readonly_session.py tests/test_mister_cli.py tests/test_mister_helper.py tests/test_mister_ra.py tests/test_mister_endpoint.py tests/test_mister_tloz_all_sender.py -v`

- [x] **Step 2: Run full bridge suite**

Run: `uv run python -m pytest tests/ -v`
