# MiSTer NES port — strategy & resources

Forward-looking notes on extending emu-coop-plus to a third endpoint: a real
MiSTer FPGA running the NES core. Today the bridge supports FCEUX (Lua) and
the Everdrive Pro N8 cart (USB serial). MiSTer is a natural third because
the same Linux-on-Cyclone-V SBC that runs the cores can also host a small
bridge daemon and talk to the same shared relay as our other endpoints.

## What we need

emu-coop-plus's bridge protocol is small. To support any new endpoint we
need exactly two operations against NES memory:

- `Read(addr, len)` — poll Z1's CPU RAM ($0000-$07FF)
- `WritePairs([(addr, byte), ...])` — apply incoming peer writes

That's it. No debugger, no breakpoints, no save-state plumbing.

Current Z1 modes sync state entirely from CPU RAM. Cart SRAM support is a
future capability only if a later mode needs it.

Architecturally, MiSTer should look much closer to the FCEUX endpoint than to
the EDN8 endpoint. EDN8 is the outlier: it needs a CC-patched ROM because the
cart needs game-side code to service USB memory commands. MiSTer should not need
that patch. Instead, the MiSTer PC/client process is the equivalent of FCEUX's
Lua layer: it loads the same mode semantics, polls/writes MiSTer memory through
MiSTer-specific primitives, and speaks the existing emu-coop relay protocol.

POC decision, May 2026: use a nearby PC client plus a tiny MiSTer helper. The PC
client owns relay pairing, mode selection, logs, item messages, and the eventual
GUI. The MiSTer helper is deliberately small: read the RA mirror from `/dev/mem`
and expose memory operations to the PC. Writes stay unsupported until a custom
NES-core write path exists.

## Where we are today

**Read path: solved.** The
[odelot/NES_MiSTer](https://github.com/odelot/NES_MiSTer) fork already mirrors
NES CPU RAM and cart SRAM into MiSTer's DDRAM at physical address
`0x3D000000`, refreshed every VBlank. It was built for RetroAchievements but
the CPU-RAM portion is exactly what current Z1 modes need. Any userspace
process on the MiSTer (it's just Linux) can `mmap /dev/mem` at that offset and
read NES state at 60 Hz with no FPGA work required.

**Write path: blocked at the HDL boundary.** odelot's mirror is
one-directional — FPGA writes, ARM reads. RetroAchievements doesn't need
writes, so the channel was never built. There is no documented JTAG / UART /
shared-memory path from userspace back into the NES core's BRAM. Writes
require an FPGA change to expose a write port into the core.

## The new template — SNES_MiSTer SNI

In March 2026, [SNES_MiSTer PR #462](https://github.com/MiSTer-devel/SNES_MiSTer/pull/462)
landed in upstream master, adding SNI (Super Nintendo Interface) support to
the SNES core. Crucially, it is a full read **and** write channel from
userspace into the running console. The architecture is what we want to
mirror:

- **FPGA side:** a new `rtl/sni.sv` command-handler state machine, a
  `rtl/uart.sv` refactor to share the existing UART pin with multiple
  consumers, and a third SDRAM arbiter channel that steals idle cycles so
  reads/writes don't disturb console timing.
- **ARM side:** a companion patch to `Main_MiSTer` adds a UART mode helper,
  and a separate userspace daemon (`snid`) speaks the QUsb2snes/SNI wire
  protocol over a TCP socket.

The address decoder, register layout, and SNI command set are SNES-specific.
The transport — FPGA UART block → ARM daemon → TCP socket — is
console-agnostic and is exactly what a NES port would reuse.

The official MiSTer-devel/NES_MiSTer master branch does **not** have anything
analogous, and recent commit history shows the maintainer set focused on
mapper accuracy with no signals of interest in external memory interfaces.
An upstream merge is unlikely; a maintained fork is the realistic path.

## Proposed approach

Fork odelot's NES core (not the official one) and layer a write channel on
top of their existing read mirror. Concretely:

1. **Start from `odelot/NES_MiSTer`.** Their RA mirror keeps working
   unchanged and gives us reads for free.
2. **Add an FPGA write port.** Pull in `rtl/sni.sv` and the `rtl/uart.sv`
   refactor from SNES_MiSTer PR #462 as a reference, then write
   `rtl/nes_bridge.sv` that arbitrates a write port into the NES core's
   iram / prg_ram / cart-RAM modules (entry points are in `NES.sv` and
   `MMU.sv`).
3. **Reuse odelot's v1.1 "smart cache" request channel as a read-side
   shortcut.** The infrastructure to send specific addresses from ARM to
   FPGA already exists; it can be extended to carry write commands instead
   of (or alongside) read requests.
4. **Ship a minimal MiSTer client.** This is the FCEUX-Lua-equivalent layer for
   MiSTer. It loads the emu-coop mode logic, polls the MiSTer memory mirror,
   applies incoming writes through the new write channel, and speaks the same
   relay protocol as FCEUX and EDN8. It can run directly on MiSTer's Linux side
   or on a nearby PC talking to a small ARM-side helper.
5. **Keep the memory transport behind an interface.** The current EDN8 bridge is
   built around `CCClient`; MiSTer should force a small abstraction boundary:
   `Read(addr, len)` / `WritePairs(...)`. EDN8 implements both over CC USB
   serial. MiSTer composes two independent transports: reads come from the DDRAM
   mirror via mmap, while writes go through the new FPGA UART/TCP write channel.
   Future endpoints can reuse the same sync engine.
6. **Choose protocol scope deliberately.** emu-coop-plus only needs
   `Read(addr, len)` and `WritePairs(...)`. We can run a tiny framed protocol
   over the UART/TCP pipe and skip full SNI/QUsb2snes. Optionally: implement the
   SNI write subset for interop with future randomizer tooling.

NES is structurally simpler than SNES for this work — no LoROM/HiROM/ExHiROM
mapping zoo, no SA-1, much smaller RAM footprint. The hard part is the
Verilog, not the protocol.

## Work required

This is not a single bridge feature. It splits into three layers that can be
advanced independently: the shared emu-coop client/runtime, a MiSTer memory
transport, and the NES-core FPGA write path.

### 1. Decouple the current bridge from EDN8

The EDN8 bridge already gave us useful pieces: `PipeClient`, the mode ports,
`record_changed`, reconnect behavior, status sinks, and the GUI/CLI session
loop. The main cleanup before MiSTer is separating those reusable parts from
`CCClient`.

Concrete work:

- Define a small memory endpoint interface in `bridge_core`, roughly:
  - `read_ranges([(base, len), ...]) -> {addr: byte} | None`
  - `read_byte(addr) -> int | None`
  - `write_pairs([(addr, byte), ...]) -> bool`
  - optional `close()` / health state
- Wrap `CCClient` in an `Edn8MemoryEndpoint` without changing its protocol.
- Change `SyncEngine` to depend on that endpoint interface instead of importing
  or naming `CCClient`.
- Move the active session loop out of `bridge_cli` / `SessionWorker` into a
  reusable runner that accepts:
  - mode module or mode instance
  - memory endpoint
  - pipe client
  - status sink
  - poll rate
- Keep EDN8 behavior passing after this refactor before adding MiSTer.

This turns the current bridge into a general non-Lua mode runner. MiSTer can
then plug into the same runner the same way FCEUX plugs into `driver.lua`.

### 2. Preserve mode semantics outside Lua

FCEUX executes the Lua mode file in-process and calls emulator memory APIs
directly. MiSTer will need the same semantics in the PC/client process:

- Mode selection and GUID handshake must remain byte-for-byte compatible with
  FCEUX peers.
- Python mode ports must continue to match the Lua mode tables.
- DIBS/Z1R modes need ROM byte access from the selected source ROM, since Lua's
  `rom.readbyte(...)` has no direct MiSTer equivalent.
- Function-kind rules, `receiveTrigger`, startup/force-send handling, custom
  messages, and non-scalar payloads need to be represented in Python.
- For DIBS specifically, the polling client must emulate the useful part of
  FCEUX write callbacks: detect room item flags before emitting the inventory
  DIBS payload that references the last item room.

This work is shared with EDN8 v2.1 DIBS support. Any improvement made here for
MiSTer should also make the EDN8 bridge less special.

### 3. Build a read-only MiSTer prototype first

Before attempting HDL writes, prove the client can observe a running NES core
cleanly.

Concrete work:

- Install and boot odelot's NES core plus its matching Main_MiSTer binary.
- Write a small prototype that mmaps `/dev/mem` at `0x3D000000`.
- Parse the RA mirror header rather than assuming a flat buffer:
  - validate the magic value
  - read the frame counter
  - locate the CPU-RAM and cart-SRAM region descriptors
  - copy a frame-stable snapshot
- Map emu-coop addresses onto the mirror regions:
  - `$0000-$07FF` -> CPU RAM mirror
  - `$6000-$7FFF` -> cart SRAM mirror only if a future mode needs SRAM
- Verify the Z1 running predicate (`$0012` between `$04` and `$0D`, inclusive)
  updates correctly.
- Verify known inventory bytes (`$0657`, `$0671`, map room flags) update at
  VBlank cadence while playing.
- Feed snapshots into `SyncEngine.diff()` with network sending disabled and log
  what would have been sent.

Success here proves most of the MiSTer client path without risking FPGA write
changes. It also gives us a diagnostic tool for later hardware work.

### 4. Decide where the MiSTer client runs

There are two practical deployment shapes:

1. **On-MiSTer client.** Run the emu-coop client directly on MiSTer's Linux side.
   This has the cleanest topology: MiSTer reads/writes its own memory and opens
   the relay TCP connection. The constraint is packaging: the current bridge is
   Python, while MiSTer may not have our expected Python environment or wheels.

2. **Nearby-PC client plus MiSTer helper.** Run the Python emu-coop client on a
   Windows/macOS/Linux PC and use a tiny helper on MiSTer for memory access.
   The helper exposes `Read` and `WritePairs` over LAN or localhost-forwarded
   TCP. This keeps the main bridge code and GUI closer to the EDN8 app, but adds
   an extra connection to configure.

Chosen proof-of-concept shape: nearby-PC client for relay/session UX plus a
minimal MiSTer helper for `/dev/mem` reads and, later, writes. This matches how
most MiSTer users already move ROMs and files through a PC, keeps the first UX
work in the existing bridge app, and avoids forcing Python/package management
onto MiSTer's Linux side too early.

For item messages, the POC should display them in the PC client/log. MiSTer has
Main_MiSTer OSD/info overlay internals, but not a drop-in public equivalent of
FCEUX Lua's `message()` for arbitrary helpers. A Main_MiSTer notification hook
can be explored later; the NES core video path should stay out of scope.

### 5. Add the FPGA write channel

This is the core-specific work and the main unknown.

Concrete work:

- Fork odelot's NES core and build it locally before changing behavior.
- Identify where CPU RAM, cart SRAM/PRG-RAM, and mapper-backed RAM writes enter
  the core for MMC1/SNROM.
- Decide the first supported write scope. For current Zelda 1 emu-coop modes,
  CPU RAM `$0000-$07FF` is the required target. Cart SRAM is not used by current
  Z1 modes, so it should not block the first proof of concept.
- Study SNES_MiSTer PR #462 as a pattern, not a drop-in:
  - UART mode handoff
  - command-handler state machine
  - read/write request framing
  - idle-cycle arbitration
  - timing-closure fixes
- Add a NES-specific command handler, likely `rtl/nes_bridge.sv`, that accepts
  write requests from the ARM side and asserts writes into the correct NES
  storage module without racing the emulated CPU.
- Preserve odelot's RA mirror path so reads keep working while writes are added.
- Add HDL simulation or a testbench if practical: issue write requests while
  the NES CPU is active and verify the correct byte lands without corrupting
  adjacent addresses.
- Build multiple `.rbf` outputs and check timing. The SNES SNI PR history shows
  timing closure was a real review concern, so this cannot be hand-waved.

First FPGA milestone: write one byte to `$0657` and observe Link's sword value
change in the next read mirror frame. Second milestone: apply a realistic
`WritePairs` batch from an emu-coop incoming packet.

### 6. Add a MiSTer memory endpoint

Once read mirror parsing exists and the write channel has a callable path, wrap
it in the shared bridge interface.

Possible modules:

- `bridge_core/memory_endpoint.py` — protocol/interface and shared helpers.
- `bridge_core/cc_endpoint.py` — adapter around existing `CCClient`.
- `bridge_core/mister_endpoint.py` — mmap reader plus write-channel client.
  Reads and writes should remain separate internally even though they share the
  same endpoint interface.
- `bridge_cli mister-read` — diagnostic command for `$0012`, inventory bytes,
  and arbitrary ranges.
- `bridge_cli mister-helper` — MiSTer-side JSON-line TCP helper for the PC
  client. For the read-only POC it serves RA mirror reads only and reports
  writes as unsupported.
- `bridge_cli mister-run` — PC-side one-way runner. It connects to the MiSTer
  helper and the normal emu-coop relay, sends `tloz_all` changes outward, and
  logs incoming partner writes as unsupported until the NES core write path
  exists.
- `bridge_cli run --endpoint mister ...` — run the relay client against MiSTer.

The MiSTer endpoint should expose snapshots in the same `{addr: byte}` shape
as the current EDN8 `read_ranges()` result, so `SyncEngine` does not care where
memory came from.

### 7. Integrate setup and UX

MiSTer setup should avoid EDN8's patch/upload assumptions.

Work items:

- Add endpoint selection: FCEUX remains Lua-only, EDN8 uses USB serial, MiSTer
  uses either local `/dev/mem` or a MiSTer helper host.
- Let users choose a source ROM path for mode logic and optional staging.
- For MiSTer, do not apply the CC IPS patch.
  - EDN8's Freeze action, WritePairs behavior, and dispatcher live in
    game-side 6502 code added by the patch. A MiSTer FPGA write port bypasses
    the 6502 entirely, so those handlers are unnecessary.
- If running from a PC, support configuring the MiSTer host/IP and helper port.
- If running on MiSTer, default relay settings should match the existing bridge.
- Surface readiness states separately:
  - MiSTer core detected
  - RAM mirror valid
  - write channel ready
  - relay connected
  - partner paired
  - mode hello OK

The first version can be CLI-only. GUI support can come after the memory path is
proven.

### 8. Test and validation path

Testing should progress from pure software to hardware:

- Unit tests for `MemoryEndpoint` adapters using fake memory backends.
- Existing `record_changed` and mode parity tests unchanged after endpoint
  decoupling.
- Tests for RA mirror parsing with captured/synthetic mirror frames.
- MiSTer read-only smoke: launch Z1, watch `$0012`, `$0657`, `$0671`, and map
  room flags change.
- Local write smoke: write `$0657` and confirm the mirror reports the update.
- Bridge-to-FCEUX smoke through the relay:
  - FCEUX picks up an item -> MiSTer receives and writes it
  - MiSTer changes memory -> FCEUX receives and writes it
  - reconnect/force-send works
- DIBS-specific smoke after v2.1 mode work:
  - Triforce DIBS cap works
  - exclusive item room flag is written on the peer
  - entrance discovery syncs correctly

Hardware validation should include long idle polling, gameplay with frequent
room transitions, reset/reload behavior, and MiSTer OSD interactions.

### 9. Likely sequence

1. Refactor bridge memory access behind an endpoint interface while preserving
   EDN8 behavior.
2. Build a read-only MiSTer mirror reader and diagnostic CLI.
3. Add the tiny MiSTer helper protocol and PC-side helper client.
4. Feed MiSTer snapshots through the existing sync engine without writes.
5. Run a one-way MiSTer-to-FCEUX/EDN8 smoke through the relay.
6. Fork/build odelot's NES core and identify the write insertion points.
7. Add the smallest possible CPU-RAM write path and prove one-byte writes.
8. Wrap that path as `MisterMemoryEndpoint.write_pairs`.
9. Broaden to `tloz_progress`, `tloz_all`, then DIBS modes after Python DIBS
   parity exists.
10. Revisit whether to ship as PC client plus helper only, on-MiSTer client, or
    both.

## Open questions

- **Cart RAM vs. PRG-RAM vs. CIRAM** — confirm exactly which storage modules
  the NES core uses for Z1's MMC1 SNROM cart, and whether each has a clean
  arbitration boundary for adding a write port.
- **ROM staging on MiSTer.** Unlike EDN8, MiSTer should not need the CC-patched
  ROM. The MiSTer client should stage or launch the selected source ROM from
  `games/NES/`, and keep the source ROM bytes/path available for mode logic
  that depends on ROM reads (for example DIBS/Z1R room-address derivation).
- **Maintenance overhead of a fork.** odelot already maintains a fork of the
  official core; we'd be maintaining a fork of a fork. Worth merging changes
  upstream into odelot if they'll take them, to reduce drift.

## Resource links

- [odelot/NES_MiSTer](https://github.com/odelot/NES_MiSTer) — read-side
  DDRAM mirror, our starting point
- [odelot/Main_MiSTer](https://github.com/odelot/Main_MiSTer) — companion
  ARM-side reader (`shmem.cpp`, `ra_ramread.cpp`)
- [SNES_MiSTer PR #462](https://github.com/MiSTer-devel/SNES_MiSTer/pull/462) —
  reference write-channel implementation, merged upstream
- [Main_MiSTer PR #1092](https://github.com/MiSTer-devel/Main_MiSTer/pull/1092) —
  ARM-side UART mode helper that the SNI work depends on
- [MiSTer-devel/NES_MiSTer](https://github.com/MiSTer-devel/NES_MiSTer) —
  upstream NES core for reference; not the fork target

## Status

This is **not** scheduled for any current milestone. v2.1 is focused on
porting DIBS! competitive modes to the bridge. The MiSTer port is parked
here so that when we do pick it up, the analysis and references are already
in one place.
