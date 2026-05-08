# MiSTer DDRAM Write Mailbox POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end MiSTer proof of concept where emu-coop-plus reads NES RAM from odelot's RA mirror and applies incoming `WritePairs` through a tiny DDRAM mailbox handled by a custom NES core.

**Architecture:** Keep the PC bridge and relay runner generic. The MiSTer helper runs on MiSTer, mmaps odelot's RA DDRAM region, serves reads from the existing mirror, and writes request batches into a new ARM-to-FPGA mailbox. The NES core polls that mailbox and applies CPU-RAM writes through the existing SDRAM channel-2 arbiter.

**Tech Stack:** Python bridge/helper tests with pytest; MiSTer userspace `/dev/mem` mmap; SystemVerilog changes in odelot/NES_MiSTer.

---

### Task 1: Bridge Mailbox Protocol

**Files:**
- Create: `bridge/bridge_core/mister_mailbox.py`
- Create: `bridge/bridge_core/mister_smartcache.py`
- Modify: `bridge/bridge_core/mister_helper.py`
- Test: `bridge/tests/test_mister_mailbox.py`
- Test: `bridge/tests/test_mister_smartcache.py`
- Test: `bridge/tests/test_mister_helper.py`

- [ ] **Step 1: Write failing mailbox tests**

Add tests for a bytearray-backed DDRAM mailbox:

- `write_pairs([(0x0657, 0x01), (0x0671, 0x03)])` writes one 64-bit word per pair.
- Control word is written last with request sequence and count.
- `wait_for_ack()` succeeds only when the FPGA writes the matching ack sequence.
- Invalid addresses outside CPU RAM are rejected before touching the mailbox.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run python -m pytest tests/test_mister_mailbox.py tests/test_mister_helper.py -v`

Expected: fails because `bridge_core.mister_mailbox` does not exist or helper writes still report unsupported.

- [ ] **Step 3: Implement minimal mailbox writer**

Protocol:

- RA DDRAM physical base remains `0x3D000000`.
- Existing odelot smart-cache regions remain unchanged.
- Write control byte offset: `0x58000`.
- Write pair byte offset: `0x58008`.
- Pair word layout: bits `[15:0] = NES address`, bits `[23:16] = byte value`.
- Control word layout: bits `[7:0] = request_seq`, `[15:8] = count`, `[23:16] = ack_seq`, `[31:24] = status`.
- ARM/helper writes pair words first, then writes control with `ack_seq = 0`.
- FPGA writes control back with `ack_seq = request_seq`.

- [ ] **Step 4: Wire helper writes through mailbox endpoint**

Keep `ReadOnlyMisterMemoryEndpoint` unchanged. Add a write-capable endpoint wrapper used by `mister-helper` when launched with write mailbox support. `handle_helper_request({"op":"write_pairs"})` should return `{"ok": true}` for the write-capable endpoint and keep returning `writes_not_supported` for read-only endpoints.

- [ ] **Step 5: Add odelot smart-cache reads**

The active odelot NES module uses the address-list/value-cache protocol, not the older full-region mirror module. Add a smart-cache reader that writes requested addresses at DDRAM byte offset `0x40000`, waits for the matching response at `0x48000`, and exposes the same `read_ranges` / `read_byte` endpoint API.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run python -m pytest tests/test_mister_mailbox.py tests/test_mister_smartcache.py tests/test_mister_helper.py tests/test_mister_endpoint.py -v`

Commit bridge changes separately from RTL changes.

### Task 2: Core Mailbox Consumer

**Files:**
- Modify: `D:/tmp/odelot-NES_MiSTer/rtl/ra_ram_mirror_nes.sv`
- Modify: `D:/tmp/odelot-NES_MiSTer/NES.sv`

- [ ] **Step 1: Create a core feature branch**

Run in `D:/tmp/odelot-NES_MiSTer`: `git switch -c emu-coop-ddram-mailbox-poc`

- [ ] **Step 2: Add write mailbox state to `ra_ram_mirror_nes.sv`**

Add polling for the write-control word at DDRAM offset `0x58000`. When `request_seq != last_seen_seq`, `count > 0`, and `ack_seq == 0`, read up to the capped pair count from `0x58008`, validate each address is CPU RAM `$0000-$1FFF`, mirror it down with `addr[10:0]`, and pulse `sdram_wr` with `sdram_din`.

- [ ] **Step 3: Connect SDRAM write signals in `NES.sv`**

Add `ra_sdram_wr` and `ra_sdram_din` wires. When `ra_sdram_active` owns channel 2, route `ch2_wr` and `ch2_din` from the RA mailbox module instead of forcing writes off.

- [ ] **Step 4: Add completion ack**

After all valid writes are applied, write the control word back with `ack_seq = request_seq` and `status = 0`. If a pair is invalid or times out, still ack the request and set a non-zero status.

- [ ] **Step 5: Run available HDL checks**

Run a syntax/build check if Quartus tooling is installed. If it is not installed in the environment, record that explicitly and rely on source review plus bridge-side tests until the branch is built on the MiSTer toolchain.

### Task 3: End-to-End Smoke

**Files:**
- Modify docs as needed after first hardware run.

- [ ] **Step 1: Deploy custom `.rbf` and helper to MiSTer**

Boot the custom odelot NES core, start `mister-helper` with mailbox writes enabled, and run Zelda 1.

- [ ] **Step 2: One-byte write smoke**

Use a CLI/helper diagnostic to write `$0657 = 0x01` and confirm the next mirror snapshot reports the new value.

- [ ] **Step 3: Relay smoke with `tloz_all`**

Run `bridge_cli mister-run --mode tloz_all ...` against an FCEUX or EDN8 peer. Confirm MiSTer sends local changes and applies incoming peer writes.
