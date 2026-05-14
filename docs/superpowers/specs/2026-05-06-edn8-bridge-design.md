# emu-coop EDN8 bridge — design

**Date:** 2026-05-06
**Status:** Approved (pending user review of this written spec)
**Scope:** Cross-platform (Windows-first, macOS nice-to-have) GUI app + headless library that lets a real NES with an Everdrive Pro N8 cart participate in emu-coop sessions exactly as if it were a FCEUX peer. Z1R is the first concrete game mode; architecture supports adding more.

## 1. Goals and non-goals

### Goals

- A bridge app that connects a real NES (via EDN8 + USB serial + CC-patched ROM) to the existing emu-coop wire format, behaving as another peer of the OCI relay.
- The relay cannot tell the difference between a FCEUX peer and a bridge peer.
- Multi-mode architecture from day one. `tloz_all` ships first; future modes are just new Python files.
- Single-language Python stack (CustomTkinter GUI, no Rust/JS/C# dependencies).
- Single downloadable executable per OS, target ~25 MB bundled. No "install Python first" requirement.
- Bundle the IPS patch internally — user picks an unpatched ROM, app handles patching silently.
- Support both Windows and macOS via CustomTkinter. Windows is the priority target; macOS shipping is conditional on CustomTkinter behaving acceptably there.

### Non-goals (deferred or out of scope)

- Replacing or modifying the FCEUX-side Lua code — that stays unchanged.
- Replacing the OCI relay — bridge connects to the same relay as Lua peers do.
- Running emu-coop on Bizhawk, Mesen, or other emulators (a separate future bridge project per emulator).
- TLS / encryption — out of scope; same threat model as the Lua side.
- Mobile platforms.
- TTS / on-NES on-screen-text output for status messages — Phase 2 GUI shows status in a panel; OBS browser source overlay is a future enhancement.
- A "patch any game" universal patcher — the bundled IPS patch is Z1-specific. Adding new games would require new IPS patches and per-game mode files.

## 2. Architecture

```
[NES + EDN8 + CC-patched ROM]
         ↑↓ USB serial @ 115200 baud
[Bridge app process]
   ├─ bridge_core (library)
   │    ├─ ips           IPS parser/applier
   │    ├─ cc_client     USB serial driver, CC frame protocol
   │    ├─ sync_engine   cache, recordChanged port, mode loader
   │    ├─ pipe_client   length-prefix JSON; hello/heartbeat/reconnect
   │    ├─ status_sink   pluggable event sink (GUI subscribes; CLI prints)
   │    └─ modes/        Python mode files (tloz_all.py first)
   ├─ bridge_cli         argparse wrapper for power users
   └─ bridge_gui         CustomTkinter GUI app
         ↑↓ TCP @ 9999
[OCI relay] coop.z1rracing.com:9999
         ↑↓ TCP
[FCEUX peer running coop.lua]
```

### Three-component split (strict isolation)

- **CC client** speaks USB serial to the cart. Read/write/freeze primitives. No game logic. No JSON.
- **Sync engine** is the Python equivalent of `driver.lua`. Diffs poll snapshots against a cache, runs `recordChanged` semantics, generates outgoing data frames, applies incoming ones. No USB. No JSON.
- **Pipe client** speaks emu-coop's wire protocol to the relay. Identical contract to the Lua `RelayPipe`, just in Python. No USB. No game logic.

These three stitch together via a main loop in the CLI/GUI entry point. Each component has its own module, its own tests, its own interface.

### Codebase location

`z1rr-coop/bridge/` as a sibling to `relay/`. Same monorepo philosophy. Independent `pyproject.toml`, independent tests, independent deployable.

```
z1rr-coop/
├── bridge/
│   ├── pyproject.toml
│   ├── bridge_core/             pure-Python library; no GUI deps
│   │   ├── __init__.py
│   │   ├── ips.py
│   │   ├── cc_client.py
│   │   ├── sync_engine.py
│   │   ├── pipe_client.py
│   │   ├── status_sink.py
│   │   ├── modes/
│   │   │   ├── __init__.py
│   │   │   └── tloz_all.py
│   │   └── patches/
│   │       └── zelda_cc.ips
│   ├── bridge_cli/
│   │   ├── __init__.py
│   │   └── __main__.py
│   ├── bridge_gui/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── app.py
│   │   ├── setup_screen.py
│   │   ├── relay_setup_screen.py
│   │   ├── session_screen.py
│   │   └── assets/
│   ├── tests/
│   │   ├── test_ips.py
│   │   ├── test_cc_client.py
│   │   ├── test_sync_engine.py
│   │   ├── test_pipe_client.py
│   │   ├── test_modes_tloz_all.py
│   │   ├── test_integration.py
│   │   ├── mock_cc_server.py
│   │   └── mock_serial.py
│   ├── docs/
│   │   └── cc-patch-capabilities.md   (output of Phase 1 hardware audit)
│   └── README.md
```

### GUI framework

CustomTkinter. Reasoning:

- Same language as backend; everything stays Python.
- Two tabs + a setup wizard + a status panel is well within Tkinter capability.
- Bundled `.exe` / `.app` ~25-35 MB via PyInstaller.
- Single dependency (no Rust toolchain, no Node.js, no .NET runtime).
- If the macOS build proves too rough, the GUI can swap to PySide6 or another toolkit without changing `bridge_core/`.

### Two distributions

- **End user:** `bridge.exe` (Windows-first), `bridge.app` (macOS, target). Single download, double-click to run, no Python install.
- **Developer:** `pip install -e bridge/` in cloned repo. Gets CLI + library for testing/scripting.

## 3. Wire format and protocol participation

### Same wire format as the Lua client

The bridge speaks the existing emu-coop length-prefix JSON protocol unchanged. Full compatibility with current FCEUX peers and the OCI relay; no protocol changes required.

Frame format (4-byte big-endian length + JSON), kinds (`hello`, `data`, `ping`, `pong`, `abort`, `join`, `joined`, `partner-reconnected`), state machine — all identical to the Lua design (`docs/superpowers/specs/2026-04-30-emu-coop-transport-design.md`).

### App-level handshake

After protocol-level hello succeeds, both peers exchange the app-level `{op:"hello", guid, version}` message. The bridge uses the **same guid** as the corresponding Lua mode file. For `tloz_all`, that's `377c5683-3cf5-4c56-a921-ab40257b2ec1`. Mismatched guids → `pipe.abort()` with "Partner has an incompatible mode file."

### Mode file parity rule

For each Lua mode file in `modes/*.lua`, there's an equivalent Python file in `bridge/bridge_core/modes/*.py` with the **same guid** and **same address coverage**. CI test diffs the two and warns on drift. When a Lua mode bumps its guid, the Python equivalent must follow.

## 4. GUI screen flow

```
[App launch]
    ↓
[ROM Setup screen]
  - "Choose your Z1 ROM:" file picker
  - When file picked: app detects unpatched/patched, shows summary
  - [Continue] — silently applies CC patch (if needed) and uploads to EDN8
    ↓
[Relay Setup screen]
  - Mode dropdown (default: tloz_all)
  - Relay address (default: coop.z1rracing.com) + port (9999)
  - Session code (text, must be 6+ chars to enable Connect)
  - COM port (auto-detected; manual override available)
  - "Resending all my state on connect" checkbox (forceSend; default off)
  - [Connect]
    ↓
[Session screen]
  - Two-readiness indicator panel:
        Cart connection (USB)         Network connection (TCP)
        - USB: 🟢 / 🔴                - Relay: 🟢 / 🔴
        - Game: 🟢 RUNNING /          - Partner: 🟢 PAIRED /
                🟡 NOT RUNNING                  🟡 WAITING
                                       - Peer: 🟢 HELLO OK / etc.
  - Sync state: ⚫ IDLE / 🟢 ACTIVE / 🟠 RECONNECTING
  - Tabs: [Messages] [Log]
  - [Disconnect] — confirms, sends abort to partner, returns to Relay Setup
```

### Independent readiness states

The cart and network connections succeed/fail independently. Sync flows only when:

1. USB serial open to EDN8 (cart-side green)
2. ROM running (mode's `running` predicate returns true; for Z1: `addr 0x12 in [0x4, 0xD]`)
3. Relay TCP connected (network-side green)
4. Partner paired and hello-ok (network-side green)

Any of those failing pauses sync without tearing down others. Specifically: pulling the USB cable doesn't disconnect from the relay; resetting the ROM mid-session pauses sync until game-running returns; relay drop triggers reconnect logic without affecting USB connection.

### Status display

Two-tab live view in the Session screen:

- **Messages tab** — game-event narrative (the equivalent of FCEUX's `gui.text` overlay): "Partner got Wood Sword", "Connected to partner", "Reconnecting (attempt 2)..."
- **Log tab** — diagnostic / debug-level: connection state changes, frame events, timing data, errors with stack traces.

Default tab: Messages. Both tabs auto-scroll; have a "pause autoscroll" toggle for inspection.

### Future enhancement (deferred)

HTTP overlay on `localhost:5555` that streams Messages-tab events as server-sent events. Streamers add it as an OBS browser source for in-stream message display. Same `StatusSink` interface; just an additional subscriber.

## 5. Data flow

### Setup phase (one-time per ROM)

```
User picks input.nes
       ↓
ips.is_patched(input.nes)?
   ├─ yes → use as-is
   └─ no  → ips.apply(input.nes, vendored_cc.ips) → output_CC.nes
       ↓
[optional, automatic] cc_client.upload_rom(output, port=detected)
       ↓
ROM file path remembered for the session
```

### Connection establishment

```
1. open USB serial to EDN8 (verify CC firmware responds to a sentinel read)
2. open TCP to relay
3. PipeClient: send {kind:"join", code, peer_id}
4. PipeClient: await {kind:"joined"}
5. PipeClient: send {kind:"hello", v:1}
6. PipeClient: await partner's {kind:"hello", v:1} → state ESTABLISHED
7. SyncEngine: send {op:"hello", guid:"377c5683-...", version:"<bridge version>"}
8. SyncEngine: await partner's {op:"hello"} → guid match → session live
   (mismatch: pipe.abort with "Partner has an incompatible mode file")
9. SyncEngine: enter polling loop (subject to game-running gate)
```

### Active session loop (10 Hz default; tuned per Phase 1 audit)

```
every 100ms:
  if mode.running_predicate(cc_client.read([running_addr])):
    state = GAME_RUNNING
    if not didCache: SyncEngine.checkFirstRunning()
    snapshot = cc_client.read_array(spec.sync.address_set)
    for addr, cur in snapshot:
      prev = cache[addr]
      if cur != prev:
        allow, send_value = recordChanged(spec.sync[addr], cur, prev,
                                          receiving=False)
        if allow:
          pipe.send_table({addr, value: send_value})
          cache[addr] = cur
  else:
    state = GAME_NOT_RUNNING
    didCache = False  (so next time game starts, fresh cache)
  pipe.heartbeat_tick()       # send ping if 5s, fail if 15s silence
  pipe.pump_frames():
    for each incoming frame:
      if kind == "data":
        if state == GAME_RUNNING: SyncEngine.handle_table(frame.body)
        else: sleep_queue.append(frame.body)
      if kind == "ping":   send pong
      if kind == "abort":  display reason, disconnect
      if kind == "partner-reconnected": helloSent=False; sendHello; postReconnect=True
```

### Receive-side data application

```
Frame {kind:"data", body:{addr, value}} arrives
       ↓
SyncEngine.handle_table(t):
  record = spec.sync[t.addr]
  prev = memoryRead(t.addr) (via cc_client)
  allow, value = recordChanged(record, t.value, prev, receiving=True)
  if allow:
    cc_client.write_pairs([(t.addr, value)])
    cache[t.addr] = value      # prevents self-echo on next poll
    if record.receiveTrigger:
      record.receiveTrigger(value, prev)
      → status_sink.message("Partner got Wood Sword")
```

### Disconnect & reconnect

Same lifecycle as the Lua client (existing design). Heartbeat timeout → state RECONNECTING → exponential backoff → re-dial relay → re-send `join` with same peer-id → relay's HALF_BROKEN window matches → relay sends `partner-reconnected` to the held partner → both peers re-do hello → SyncEngine.resync() (clear cache, force re-poll & re-send full state on next running tick).

The GUI stays on the Session screen during reconnect; sync indicator goes 🟠 RECONNECTING and the Log tab shows attempt count.

## 6. Error handling and edge cases

Organized by phase.

### ROM Setup phase

| Failure | Handling |
|---|---|
| File picked isn't a .nes ROM (header check fails) | Inline error, stay on Setup, Continue stays disabled. |
| Disk full / can't write `_CC.nes` | Inline error with target path, Continue stays disabled. |
| EDN8 not detected at upload time | Show "Plug in your EDN8 and click Continue", skip upload step but remember the patched file for later copy. |
| Upload fails partway | Inline error with file path; Continue enables anyway (file is on disk; user can copy via SD card). |

### Relay Setup phase

| Failure | Handling |
|---|---|
| COM port can't open | Inline: "Can't open COM3. Plug in your cart and click Connect again." |
| Relay TCP unreachable | Inline: "Can't reach coop.z1rracing.com:9999. Check your internet." |
| Session code under 6 chars | Connect button stays disabled; tooltip explains. |
| Relay returns `code in use` | Inline: "Session code already in use. Pick a different one." |
| Mode/version mismatch | Brief Session screen with state going red, then auto-return to Relay Setup with hint: "Partner is using mode X. Pick the same mode and reconnect." |

### Session active phase

| Failure | Handling |
|---|---|
| Heartbeat timeout (15s silence) | State → 🟠 RECONNECTING. Re-dial with same peer-id; relay's HALF_BROKEN holds partner. Auto-recovers when network/relay back. |
| Partner aborts mid-session | Display reason, return to Relay Setup. |
| USB serial drops (cable yanked) | Cart state → 🔴. Sync pauses. Network stays. Auto-retry COM open every 2s. |
| Cart reset (RAM goes to garbage) | `running` predicate flips false → state GAME_NOT_RUNNING → polling stops, incoming queues in sleep_queue. Resumes when ROM restarts. |
| Frame parse / oversized frame | Send abort to partner with reason, disconnect. |
| CC poll timeout | Log warning. 3+ consecutive → treat as cart-disconnected. |

### App-lifecycle

| Action | Handling |
|---|---|
| User clicks Disconnect | Send abort with "user disconnected", close TCP, close USB, return to Relay Setup. |
| User closes window | Same as Disconnect (graceful). |
| User clicks back arrow | Confirm dialog before disconnecting. |
| Unhandled exception | Log to file, error dialog, attempt graceful shutdown. No silent crashes. |

### Two-readiness independence matrix

```
Cart state ↓     Network state →  DISCONNECTED  CONNECTED  RECONNECTING
DISCONNECTED                     wait for both wait for both wait for both
CONNECTED + GAME RUNNING                       ▶ SYNC ACTIVE  paused, queue
CONNECTED + GAME NOT RUNNING     wait for both wait for both wait for both
```

### Cold-start state sharing (forceSend)

Inherited from existing emu-coop: when two peers connect mid-game, neither broadcasts existing inventory state. Bridge's Relay Setup screen has the same checkbox the Lua dialog has: "Resending all my state on connect (use after a crash or to sync up an in-progress game)". When checked, on first `running=True` tick, broadcasts all current spec.sync values (subject to recordChanged filtering).

## 7. Testing strategy

Layered tests, each independently runnable.

### Layer 1: unit (pytest, no hardware, no network)

- `ips.py`: golden test against vendored CC patch
- `cc_client.py`: frame encoding/decoding, msg_id wrapping, RX parser, against `mock_cc_server`
- `sync_engine.py`: `recordChanged` port verified case-by-case against Lua reference, cache, delta, mask logic
- `pipe_client.py`: hello/heartbeat/reconnect lifecycle, against mock socket
- `modes/tloz_all.py`: guid matches Lua mode's guid, spec.sync addresses match

### Layer 2: integration (real TCP, no hardware)

- Two bridge instances connected via real Python relay (pytest fixture). Validates the full Python wire-format path bridge↔bridge.
- One bridge + Lua peer (subprocess) via real relay. Cross-implementation validation.
- Reuses the `relay/tests/test_integration.py` pattern.

### Layer 3: hardware (manual, requires real EDN8 + NES + patched ROM)

- Phase 1 hardware audit (capability + bandwidth)
- End-to-end: bridge + FCEUX peer, items sync both directions
- Drop-and-recover: yank USB cable mid-session
- Network drop mid-session via `sudo systemctl restart relay`

### Layer 4: GUI (manual smoke checks)

- Setup → Relay → Session navigation
- Error states render correctly
- Status indicators flip in/out of red/yellow/green correctly

### Test fixtures

- `tests/mock_cc_server.py` — Python EDN8 simulator. Methods to set RAM bytes, inspect writes, simulate ROM reset, USB hiccup.
- `tests/mock_serial.py` — pyserial-compatible mock; tests don't need a real COM port.
- `tests/golden/` — placeholder/synthetic files for IPS apply tests (real Z1 ROM not committed for licensing).

## 8. Build sequence (eight phases)

### Phase 1 — Hardware audit (no code; data collection)

A small Python script run against real NES + EDN8 + CC-patched ROM. Tests:

- Read latency at varying address counts (10 / 100 / 400 bytes)
- Sustained rate at 1 Hz, 10 Hz, 30 Hz, 60 Hz
- Memory regions accessible: confirm 0x0000-0x07FF (NES RAM), maybe 0x6000-0x7FFF (cart SRAM)
- Stability: 1 hour continuous polling, count timeouts/errors

Output: `bridge/docs/cc-patch-capabilities.md`. Informs polling architecture; might shift defaults (e.g., 30 Hz tier vs 10 Hz uniform).

### Phase 2 — Foundation libraries

- `bridge_core/ips.py` + tests
- `tests/mock_cc_server.py` + `tests/mock_serial.py`
- `bridge_core/cc_client.py` + tests against mock
- Tiny smoke CLI: `python -m bridge_cli read <addr>` prints RAM at given address

### Phase 3 — Sync engine (no network)

- Port `recordChanged` from `driver.lua` to `bridge_core/sync_engine.py` (line-by-line equivalence)
- Port `modes/tloz_all.lua` to `bridge_core/modes/tloz_all.py`
- SyncEngine class with poll/cache/handleTable/forceSend/sleepQueue
- Tests verify behavior parity with Lua reference

### Phase 4 — Pipe client (network only, no CC)

- Length-prefix JSON framing
- Hello + heartbeat + reconnect state machine (Python port of Lua design)
- Tests against mock socket
- Integration test: pipe client connects to real OCI relay, joins, hellos, disconnects

### Phase 5 — Wire it all together (CLI mode)

- `bridge_cli/__main__.py`: `python -m bridge_cli run --mode tloz_all --port COM3 --code mycode`
- Wires CC client + Sync engine + Pipe client + console StatusSink
- Manual smoke test with hardware: bridge ↔ FCEUX peer through OCI relay; items sync

### Phase 6 — GUI (`bridge_gui`)

- Setup screen: file picker, IPS apply, optional EDN8 upload
- Relay Setup screen: mode dropdown, relay+code+port, COM port detection, forceSend checkbox
- Session screen: two readiness indicators, Log + Messages tabs, Disconnect
- StatusSink subscribes to GUI; same backend
- Manual smoke through full GUI flow

### Phase 7 — Distribution

- PyInstaller spec; `bridge.exe` (Windows) target
- Bundle size verification (target: under 30 MB)
- Smoke test the bundled binary on a clean Windows VM (no Python installed)
- Same on macOS if hardware available; ship on macOS only if CustomTkinter behaves acceptably

### Phase 8 — Polish

- `bridge/README.md` end-user docs (with screenshots)
- Top-level `README.md` updated with bridge link
- Optional: GitHub Releases workflow that auto-builds on tag push

## 9. Risks

- **CC patch capability gaps.** Phase 1 might reveal the firmware can't sustain 10 Hz of 400 bytes. Don't commit to polling architecture until Phase 1 data lands.
- **CustomTkinter macOS quirks.** Tkinter on macOS has historical UI weirdness. May need extra effort or a different framework for macOS. Windows ships first regardless.
- **PyInstaller bundling.** Hidden imports / file-resource paths sometimes catch users off-guard. Plan for a half-day debug session.
- **EDN8 ROM upload protocol.** Re-implementing requires reading KRIKzz source. If unclear, fall back to bundling `edlink-n8.exe` (~40 KB) and shelling out.
- **Mode parity drift.** Every change to a Lua mode file (guid bump, address change) must be mirrored in Python. Mitigated with a CI test that diffs the address sets.

## 10. Out-of-scope work captured for later

- HTTP overlay endpoint for OBS browser source (Section 4 future enhancement)
- TTS / voice-prompt status output
- Universal "patch any game" flow (currently Z1-only IPS bundled)
- Bizhawk / Mesen bridges (separate projects, same wire format)
- Self-hosted local relay mode in the bridge GUI (small relay daemon bundled inside bridge.exe; useful for LAN-only co-op without OCI)
- Mode hot-swap during a session (currently requires disconnect → change → reconnect)
- Auto-update mechanism for the bridge binary
