# emu-coop transport replacement: design

**Date:** 2026-04-30
**Status:** Approved (pending user review of this written spec)
**Scope:** Replace IRC-based networking in emu-coop with Direct (peer-to-peer TCP) and Relay (outbound TCP through a hosted relay) transports. Designed bridge-ready so an external bridge process can later speak the same wire format without changes.

## 1. Goals and non-goals

### Goals

- **Drop IRC entirely.** No fallback. The existing `IrcPipe` and IRC-specific dialog fields are deleted at the end of the build. Old code is recoverable from git history.
- **Two new transports**, both subclasses of the existing `Pipe` base, both speaking the same wire format:
  1. **`DirectPipe`** — peer-to-peer TCP. One peer hosts (listens on a port), the other connects to `host:port`. Use case: LAN, Tailscale/ZeroTier users, port-forwarders.
  2. **`RelayPipe`** — both peers connect outbound to a relay daemon running on the OCI Always Free VM. They identify themselves with a shared session code (one peer makes it up and shares it out-of-band, e.g. Discord); the relay matches the pair and forwards bytes transparently.
- **Bridge-ready.** The wire format is the same shape an external bridge process would speak. Future `BridgePipe` (FCEUX ⇄ local-bridge over TCP, bridge ⇄ peer over the same wire) is a sibling subclass with no changes to format.
- **Driver layer untouched.** `Driver:sendTable(t)` / `:handleTable(t)` API is unchanged. Existing modes (`tloz_*`, `lttp`, `super_metroid`) need zero modifications.
- **Auto-reconnect with state resync.** A transient network drop or brief emulator hiccup recovers without restarting either emulator. Both peers' Pipes auto-reconnect with backoff; on successful reconnect the Driver re-dumps state, both sides merge idempotently.

### Non-goals (deferred to future work)

- Reconnection while preserving the *exact* message stream (sequence-numbered replay). Bulk re-dump via `Driver:resync()` is sufficient because the existing protocol is idempotent.
- Encryption. Game-sync data is uninteresting plaintext; the relay's session-code pairing authenticates well enough for this threat model. TLS can be added later via `stunnel` in front of the relay.
- More than two players per session. The `Pipe` base assumes one peer.
- A separate bridge process (FCEUX ⇄ local-bridge ⇄ partner). Architecture supports it; not built here.
- Multi-emulator support (Bizhawk, Mesen). Out of scope; design choices (pure-Lua JSON, no C extensions) keep the door open.

## 2. Wire format

### Frame format (all transports)

```
+----------+-----------------+
| len32-be | json payload    |
+----------+-----------------+
  4 bytes    N bytes
```

- **`len32-be`** — big-endian unsigned 32-bit length of the payload in bytes.
- **`json payload`** — UTF-8 JSON object.
- **Max payload size:** 4 KiB. Today's emu-coop tables are <1 KB. Cap catches misframing fast (a corrupted length prefix consumes at most 4 KiB before the parser bails).

Reading uses a small state machine in the receive pump: read 4 bytes header → read N bytes body → dispatch → repeat. LuaSocket's `:receive(N)` returns partial data with `"timeout"` on EAGAIN, so we accumulate across `tick()` calls — same mechanism the existing IrcPipe uses for line buffering, just length-counted instead of `\n`-terminated.

### Message kinds

**Both transports, post-connection (peer ⇄ peer):**

| kind | shape | direction | purpose |
|---|---|---|---|
| `hello` | `{kind:"hello", v:1}` | both peers, immediately after connect | version handshake |
| `abort` | `{kind:"abort", reason:"..."}` | either peer | sent before close on fatal error; receiver displays reason and exits |
| `data` | `{kind:"data", body:<table>}` | either peer, post-handshake | the table that today goes through `pretty.write` |
| `ping` | `{kind:"ping"}` | both peers, every 5s | heartbeat |
| `pong` | `{kind:"pong"}` | reply to ping | symmetry |

**Relay-only (peer ⇄ relay):**

| kind | shape | direction | purpose |
|---|---|---|---|
| `join` | `{kind:"join", code:"abc123", peer_id:"<uuid>"}` | peer → relay | "pair me with whoever else uses this code" |
| `joined` | `{kind:"joined"}` | relay → peer | "you're paired, frames now flow to the other peer" |
| `partner-reconnected` | `{kind:"partner-reconnected", peer_id:"<rejoiner>"}` | relay → surviving peer | "your partner just rejoined; expect fresh hello + resync" |

### Two-phase relay design

The relay parses JSON only for the initial `join` frame. Once a pair is established, it sends `joined` to both sides and becomes a transparent byte forwarder — it never inspects gameplay traffic. Cleaner trust boundary, simpler relay code, lower CPU. The exception is `partner-reconnected`: when the relay needs to inject this frame into a paired connection (during a swap), the relay constructs the framed JSON itself and writes it to the surviving peer's socket. This is a single relay-controlled write; gameplay traffic remains uninspected.

Heartbeats traverse the relay as opaque bytes. The relay does not parse them. Per-connection 30s idle timeout on the relay side catches dead TCP that didn't FIN cleanly.

### Session codes

User-chosen strings. Peers type the same code into both clients and share it out-of-band (Discord, etc.). Relay enforces:

- Min length 6 chars (rejects collisions like "test").
- Only one active pair per code (third `join` from a non-matching peer_id → reject with `abort`).
- Code TTL: if a peer waits >10 minutes for a partner, relay closes with `abort{reason:"no partner"}`.

No relay-side persistence, no auth, no accounts. The session code plus peer_id is the only identification.

### Peer ID

Each emu-coop instance generates a random UUID at startup and reuses it for the lifetime of the session (including all reconnect attempts). The relay uses `peer_id` to distinguish "this is a brand new partner" from "this is the existing peer reconnecting." Without it, the relay would reject reconnects as third-party intrusions.

### JSON library

Pure-Lua, no native deps (FCEUX's Lua env doesn't reliably have C extensions, and we want this to also work in Bizhawk/Mesen later without recompilation). Use `rxi/json.lua` — ~250 lines, MIT, single file, drops into `vendor/json.lua`.

### Protocol versioning

Single integer `v` in `hello`. Bump on any wire-format-breaking change. Today: `v=1`. Cleanly separate from `version.lua`'s app version.

## 3. Component layout

### Lua side

```
z1rr-coop/
├── coop.lua              modified — pipe instantiation switches on dialog choice
├── debug.lua             unchanged
├── dialog.lua            modified — new UI: pick Direct/Relay, gather config
├── pipe.lua              modified — Pipe base only; framing + hello + heartbeat + reconnect state machines (IrcPipe deleted at end of build)
├── pipe_direct.lua       new — DirectPipe(Pipe): TCP listen-or-connect
├── pipe_relay.lua        new — RelayPipe(Pipe): TCP-out + join handshake + partner-reconnected handling
├── driver.lua            modified — adds Driver:resync() (no-op base, GameDriver implements)
├── util.lua              unchanged
├── version.lua           modified — bump, add `protocolVersion = 1`, remove `ircPipe`
├── vendor/
│   └── json.lua          new — rxi/json.lua dropped in
├── modes/
│   └── ...               unchanged
├── tests/                new directory
│   ├── run.lua           test runner
│   ├── mock_socket.lua   in-memory LuaSocket API stub; two mocks can be paired
│   ├── test_frame.lua    framing roundtrip, partial reads, oversized frame, malformed JSON
│   ├── test_handshake.lua hello v-match, v-mismatch → abort
│   ├── test_pipe_direct.lua paired DirectPipes against paired mock sockets
│   ├── test_pipe_relay.lua paired RelayPipes against a mock relay
│   ├── test_heartbeat.lua ping/pong cadence, silence detection
│   ├── test_reconnect.lua FAILED → RECONNECTING → CONNECTING → resync
│   └── integration/
│       ├── run.sh        spawns 2× lua + 1× python; asserts frame exchange
│       └── peer.lua      tiny Lua harness wrapping the real Pipe classes
└── relay/                new sibling project (Python; deploys to OCI)
    ├── pyproject.toml
    ├── relay/
    │   ├── __init__.py
    │   └── server.py     asyncio TCP server (~150 lines)
    ├── tests/
    │   └── test_server.py
    ├── deploy/
    │   └── relay.service systemd unit
    └── README.md         OCI Always Free setup, firewall rules, systemd install
```

### Pipe class hierarchy

```
Pipe (pipe.lua)
├── framing (read 4-byte header → read body → parse JSON → dispatch)
├── send(table) — JSON-serialize, length-prefix, write
├── hello state machine (sent? received? validated? data-phase?)
├── heartbeat (ping every 5s, dead after 15s of silence)
├── reconnect lifecycle (FAILED → RECONNECTING → CONNECTING with backoff)
└── abstract: _init_transport, _post_transport_connect, _reconnect_transport
    │
    ├── DirectPipe(Pipe)
    │     _init_transport: if host, socket.bind+listen+accept; if client, socket.connect
    │     _post_transport_connect: send hello, enter receive loop
    │     _reconnect_transport: same as _init_transport (host re-listens, client re-dials)
    │
    └── RelayPipe(Pipe)
          _init_transport: socket.connect to relay
          _post_transport_connect: send join frame, await `joined`, send hello, enter receive loop
          _reconnect_transport: same with the same peer_id
          handles partner-reconnected: transition back to HELLO_SENT, trigger Driver:resync after hello
```

The `Pipe` base owns framing, hello, heartbeat, and reconnect. Subclasses own only transport-specific connection establishment.

### Relay (Python, asyncio)

`relay/relay/server.py` — single file, ~150 lines:

**Per-connection state machine:**
1. Accept TCP. Read one frame (4-byte header + body, capped at 4 KiB).
2. Parse JSON; expect `{"kind":"join","code":"...","peer_id":"..."}`. If malformed/oversized/missing fields → close.
3. **Pairing** (see relay state machine below).
4. **Forwarding phase:** two `asyncio.create_task` coroutines per pair, each shuttling bytes one-way. No JSON parsing, no inspection.
5. **Cleanup:** on either peer's disconnect, transition pair to `HALF_BROKEN` with 60s grace.

**Per-code state machine:**

For each session code, the relay tracks:
- `peers: { peer_id → socket }` — active sockets keyed by peer ID
- `state: WAITING (1 peer) | PAIRED (2 peers) | HALF_BROKEN (1 peer + 60s timer)`

On incoming `join{code, peer_id}`:
- **Code unknown** → `WAITING`, register peer.
- **Code in `WAITING` with different peer_id** → second peer arrives → `PAIRED`, send `joined` to both, start byte forwarding.
- **Code in `WAITING` with same peer_id** → reconnect of waiting peer; swap socket.
- **Code in `PAIRED` with matching peer_id** → reconnect of an existing peer → close old socket, replace with new; send `partner-reconnected{peer_id}` to the other peer; restart per-peer hello with the rejoining side.
- **Code in `PAIRED` with different peer_id (third party)** → reject with `abort{reason:"code in use"}`.
- **Code in `HALF_BROKEN` with matching peer_id** → restore to `PAIRED`, send `partner-reconnected` to surviving peer.
- **Code in `HALF_BROKEN` with different peer_id** → reject.

On socket death (read EOF, write fail, or 30s idle timeout):
- If pair was `PAIRED` → `HALF_BROKEN` for 60s.
- If 60s expires without rejoin → send `abort{reason:"partner did not return"}` to surviving peer, close.

**Config (env vars):**
- `RELAY_PORT` (default 9999)
- `RELAY_MAX_PAIRS` (default 100)
- `RELAY_TTL_SECONDS` (default 600) — wait time for partner to first arrive
- `RELAY_GRACE_SECONDS` (default 60) — wait time for peer to reconnect after disconnect
- `RELAY_IDLE_SECONDS` (default 30) — per-connection inactivity timeout

**Logging:** stdout. systemd captures into journald.

**No DB, no auth, no accounts.** Relay is stateless across restarts; pair state lives in memory only. Restart loses in-flight pairs — surviving peers see "Connection lost" and auto-reconnect.

## 4. Lifecycle and error handling

### Pipe state machine

```
                                                           (RelayPipe only)
INIT → CONNECTING → TRANSPORT_READY ──┬── JOIN_SENT → JOINED ──┐
                                       │                        │
                                       └───────────────────────┴── HELLO_SENT → ESTABLISHED
                                                                                      │
                              ┌───────────────────────────────────────────────────────┘
                              ↓ (heartbeat timeout, write fail, socket close)
                          FAILED → RECONNECTING → (back to CONNECTING)
                                       │
                                       └ exponential backoff: 1, 2, 4, 8, 16, 30, 30s...
                                         retries forever, status updates each attempt
```

The Pipe stores its original connection params on first wake (`host:port` for Direct, `relay+code+peer_id` for Relay). On `FAILED`, it does NOT set `self.dead = true`. Instead: closes the dead socket, schedules a backoff timer, transitions to `RECONNECTING`. The `gui.register(tick)` callback stays installed across reconnects.

Status messages: `"Connection lost. Reconnecting (attempt 3, last error: connection refused)..."`

No auto-give-up. User can quit the emulator if they truly want to abandon.

### Heartbeat

- Each peer sends `ping` (empty body) every 5 seconds.
- Receiver replies with `pong`.
- Liveness: any inbound byte resets the timer (pong is symmetric, not strictly required for liveness).
- If no inbound bytes for 15 seconds → connection declared dead, transition to `FAILED`.

Heartbeat uses wall-clock time (not FCEUX tick counts) because the emulator may pause or run slow.

### Driver resync

`Driver:resync()` — new method on the `Driver` base class as a no-op. On `GameDriver`:

```lua
function GameDriver:resync()
  self.didCache = false
  self.forceSend = true
end
```

Next `checkFirstRunning` re-dumps all tracked memory addresses. Both peers do this on every successful reconnect; both states merge idempotently.

Triggered by:
- Direct: after a reconnect's hello completes, the side that initiated the reconnect calls `Driver:resync()`. The partner does the same when its own reconnect's hello completes (since both peers' heartbeats trip and both reconnect).
- Relay: same as Direct for a full disconnect. Additionally, when a `partner-reconnected` frame arrives, the surviving peer transitions to `HELLO_SENT`, awaits the partner's fresh hello, then calls `Driver:resync()` once handshake completes.

### Error categories (peer side)

| Failure | When | UI behavior | Action |
|---|---|---|---|
| TCP connect refused / timeout / DNS | CONNECTING (initial) | `"Could not reach <peer/relay>: <reason>"` | hard exit |
| TCP connect refused (during reconnect) | CONNECTING (post-FAILED) | `"Reconnecting (attempt N)..."` | continue retrying |
| Relay says "code in use" | JOIN_SENT (initial) | `"Session code already in use, pick another"` | hard exit |
| Relay TTL expired | JOIN_SENT | `"No partner showed up"` | hard exit |
| Version mismatch | HELLO_SENT | `"Partner's emu-coop version is incompatible (got v=N, expected v=1)"` | send `abort`, hard exit |
| Malformed frame | any post-CONNECTING | `"Wire protocol error: <detail>"` | hard exit |
| Oversized frame (>4 KiB) | any post-CONNECTING | `"Wire protocol error: frame too large"` | hard exit |
| Mid-session disconnect (heartbeat timeout, RST, EOF) | ESTABLISHED | `"Connection lost. Reconnecting..."` | enter RECONNECTING |
| Peer sent `abort` frame | any | `"Partner aborted: <reason>"` | hard exit |

Errors that hard-exit are protocol-level errors where retrying is futile (version mismatch, malformed wire, code conflict). Errors that trigger reconnect are network-level (TCP refused, RST, EOF, idle timeout, heartbeat timeout).

### Error categories (relay side)

| Failure | Action |
|---|---|
| First frame not a valid `join` | log, close connection silently |
| Code shorter than 6 chars | send `abort{reason:"session code too short"}`, close |
| Code already has 2 paired peers (third peer_id) | send `abort{reason:"code in use"}`, close |
| TTL expired waiting for partner | send `abort{reason:"no partner"}`, close |
| Partner disconnects during forwarding | transition to HALF_BROKEN, start grace timer |
| Grace timer expires | send `abort{reason:"partner did not return"}` to surviving peer, close |
| Forwarding-phase exception (network I/O fail) | close both, log |

Relay never crashes on malformed input; it just closes the offending connection. systemd auto-restarts on actual process crash.

### Lifecycle invariants

- **Tick safety.** The `gui.register(tick)` callback is the only place reads happen. After `CLOSED` (terminal), `tick()` is a no-op. The callback is registered once and stays for the entire emu-coop lifetime, including across reconnects.
- **Non-blocking I/O.** All sockets `:settimeout(0)`. Reads return `nil, "timeout"` on EAGAIN; we resume on next tick.
- **Half-read frames stored on the Pipe instance.** State carries across ticks: `headerBuf`, `bodyBuf`, `bodyLen`, `readState ∈ {READ_HEADER, READ_BODY}`.
- **Single send path.** `Pipe:sendFrame(table)` is the only way a frame leaves. JSON-encode → length-prefix → write. Failure → FAILED.
- **Hello is mandatory and one-shot per connection.** Each side sends exactly one `hello` immediately after `TRANSPORT_READY` (or `JOINED` for relay). Receiving a second `hello` mid-session is a protocol error, except after a `partner-reconnected` notification (which explicitly resets the hello state).
- **Reconnect preserves connection params and peer_id.** No re-dialog after first connect.

## 5. Testing strategy

Three layers:

### Lua unit tests (run with stock `lua` outside FCEUX)

Mock `emu`, `gui`, `socket`, and the wall-clock via `tests/mock_socket.lua` and a clock injection on the Pipe. Cover:

- Framing roundtrip, partial reads, oversized frames, malformed JSON.
- Hello state machine: v-match, v-mismatch, abort.
- Heartbeat: ping cadence, silence detection.
- Reconnect: simulated drop mid-session → FAILED → RECONNECTING → backoff → CONNECTING → ESTABLISHED → resync called.
- DirectPipe with paired mock sockets: full session including reconnect.
- RelayPipe with mock relay: join → joined → hello → data → drop → reconnect with partner-reconnected.

### Python relay tests (pytest)

- Pair flow.
- Code-too-short, code-collision, oversized join, malformed join, missing peer_id.
- TTL timeout (no partner shows up).
- Idle timeout (peer goes silent).
- HALF_BROKEN state: peer drops → grace timer → matching rejoin restores.
- HALF_BROKEN: grace timer expires → surviving peer gets abort.
- Concurrent pairs (two pairs with different codes don't interfere).

### Integration tests (`tests/integration/run.sh`)

Bash script spawning real subprocesses:
- 1× `python -m relay` (real asyncio server on localhost)
- 2× `lua tests/integration/peer.lua` (real Pipe classes against real sockets)

Asserts roundtrip exchange of N frames. Catches real-socket and real-asyncio behavior the mocks don't.

## 6. Build sequence

Eight phases, each ending at a verifiable checkpoint.

### Phase 1: Foundation
1. Drop `vendor/json.lua` (rxi/json.lua) into the repo.
2. Write `tests/mock_socket.lua` — paired in-memory sockets implementing the LuaSocket subset we use.
3. Add framing helpers to `Pipe` base: 4-byte big-endian length prefix encode/decode, JSON ser/de, max-size enforcement. Unit tests in `tests/test_frame.lua`.

**Checkpoint:** `lua tests/run.lua` passes framing roundtrip tests.

### Phase 2: Pipe base refactor
4. Lift framing + hello state machine onto `Pipe` base. `IrcPipe` continues to work — it now consumes `Pipe`'s framing primitives but still uses IRC PRIVMSG underneath.
5. Add unit tests for the hello state machine.

**Checkpoint:** existing `IrcPipe` still functions (manual: two FCEUX via libera). New base class tested.

### Phase 3: Direct mode
6. Implement `pipe_direct.lua`. Unit tests with paired mock sockets.
7. Update `dialog.lua` — add a transport selector. Direct gathers host-or-client + IP/port.
8. Update `coop.lua` to instantiate the chosen Pipe class.

**Checkpoint:** manual smoke test, two FCEUX on LAN, short Z1 co-op session, items sync correctly.

### Phase 4: Heartbeat + auto-reconnect
9. Add heartbeat (`ping`/`pong`, 5s/15s) to Pipe base. Unit tests with mock sockets simulating silence.
10. Add reconnect state machine (`FAILED` → `RECONNECTING` → backoff → `CONNECTING`) to Pipe base. Unit tests with mock sockets simulating drops mid-session.
11. Add `Driver:resync()` (no-op base, `GameDriver` resets `didCache + forceSend`). Tests assert that post-reconnect tick re-dumps tracked addresses.

**Checkpoint:** manual smoke test — two FCEUX on LAN, briefly disable one peer's network adapter mid-session, verify auto-reconnect with state resync. No emulator restart.

### Phase 5: Relay daemon (local)
12. Initialize `relay/` Python project (`pyproject.toml`, package layout, `pytest` config).
13. Implement `relay/relay/server.py` v1: asyncio TCP server, `WAITING` ↔ `PAIRED` flow, byte forwarding, per-connection 30s idle timeout, oversized-frame rejection.
14. pytest tests: pair flow, code-too-short, code-collision, oversized join, idle timeout.
15. Implement `pipe_relay.lua` (no reconnect-resume yet — basic join/joined/hello). Unit tests against a mock relay.
16. Update `dialog.lua` — Relay mode collects relay address + session code.

**Checkpoint:** end-to-end test — two FCEUX through `python -m relay` running on localhost.

### Phase 6: Reconnect through relay
17. Add `peer_id` (random UUID per launch) to `RelayPipe.join`.
18. Add `HALF_BROKEN` state + 60s grace timer to relay; reconnect-with-matching-peer_id swaps sockets. pytest tests.
19. Add `partner-reconnected` frame handling on the Pipe (transitions back to `HELLO_SENT`, triggers `Driver:resync()` after fresh hello). Unit tests.

**Checkpoint:** manual smoke test — two FCEUX through local relay, drop one peer's network, observe seamless reconnect on both sides without emulator restart.

### Phase 7: Integration tests + OCI deployment
20. Loopback integration tests: `tests/integration/run.sh` spawns 2× `lua` subprocesses and 1× python relay subprocess, exchanges real frames, asserts roundtrip.
21. Write `relay/deploy/relay.service` (systemd unit) and `relay/README.md` (OCI Always Free setup: instance creation, firewall/security-list rules, systemd install).
22. Deploy relay to OCI, smoke test from two real internet-connected machines.

**Checkpoint:** real-world end-to-end through OCI. Document the relay's public address.

### Phase 8: Cleanup
23. Delete `IrcPipe`, IRC-specific dialog fields, IRC version constant in `version.lua`.
24. Update top-level `README.md`: new connection options, relay address (or how to point at your own relay), brief "what changed" section.
25. Final manual smoke test on the cleaned-up build.

**Checkpoint:** `git grep -i irc` returns no functional code (only historical README mentions if kept).

### Notable ordering choices

- **Reconnect before relay** so we test the reconnect logic against Direct first, then layer relay-specific reconnect (HALF_BROKEN, partner-reconnected) on top. Lower risk.
- **IrcPipe deleted last** so we always have a working fallback during development.
- **OCI deployment as a discrete phase** — that's a real one-time human-loop task.

## 7. Risks and edge cases

- **Reconnect state machine has many edge cases.** What if a `pong` arrives during `RECONNECTING`? What if the partner's hello arrives before our reconnect-resync triggers? The implementation plan must enumerate these and assign tests.
- **OCI Always Free firewall is two-layer:** OCI security list + the VM's iptables/firewalld. Easy to get the security list right and forget the VM-level one. README must call this out.
- **Heartbeat uses wall-clock time, not tick counts.** FCEUX paused or slow shouldn't cause spurious disconnects.
- **`partner-reconnected` race.** If both peers reconnect simultaneously, the relay sees two fresh joins for the same code in either order. The state machine handles this: first join finds PAIRED-with-old-A and triggers a swap; second join finds PAIRED-with-old-B and triggers another swap. End state: both peers paired with each other on fresh sockets, both in HELLO_SENT, both will resync after handshake.
- **Relay restart loses pairs.** Surviving peers see "Connection lost," auto-reconnect, and re-pair when relay comes back. Acceptable.
- **Heavy mode never auto-gives-up.** A truly orphaned peer (partner has quit for good) will retry forever. Documented: user can quit the emulator if they want to abandon. Could add a configurable timeout later if it becomes a problem.

## 8. Out-of-scope work captured for later

- Bridge process (FCEUX ⇄ local Python bridge ⇄ peer over same wire) — architecture supports it; no work in this design.
- Multi-emulator (Bizhawk, Mesen) — pure-Lua choices keep the door open.
- Encryption — `stunnel` in front of the relay if needed.
- More than two players — Pipe base assumes one peer.
- Sequence-numbered replay reconnect — current bulk-resync is sufficient.
- Reconnect timeout / give-up UI — currently retries forever.
