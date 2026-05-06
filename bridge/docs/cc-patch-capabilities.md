# CC patch capabilities (audit results)

Captured against a real EDN8 + CC-patched Z1R seed on 2026-05-06. Audit script: `bridge/audit_cc_capabilities.py`.

## Summary

**The CC patch tolerates only intermittent USB reads, not sustained polling.** Sustained USB activity at any rate above ~0 Hz crashes the game (Z1) within ~10-15 seconds, regardless of read size. This invalidates the bridge's original architecture (10 Hz polling of all SYNC addresses) and forces a redesign.

The smoking gun: with the USB cable unplugged from the EDN8, the same ROM remains stable indefinitely on the overworld. The crash is an interaction between the CC patch's NMI hook and sustained USB request servicing — not a bug in the patch itself, and not a defect in the game ROM.

## Test environment

- **Cart:** Everdrive Pro N8 (firmware version not recorded — to capture next run)
- **ROM:** Z1R seed with `Legend of Zelda, The (USA)_CC.ips` patch applied
- **Game state during audit:** Overworld, Link stationary
- **Host:** Windows 11, Python 3.13, `pyserial` over USB CDC (COM5, VID_0483 STMicro)
- **Baud:** 115200

## Run 1 (aggressive — original spec)

Tested 100/400-byte reads at 14 Hz pacing.

### Memory regions (16-byte isolated reads)

| Region | Range | OK? | Latency |
|---|---|---|---|
| RAM low | 0x0000+16 | OK | 11.5 ms |
| RAM mid | 0x0400+16 | OK | 50.2 ms |
| RAM high | 0x0700+16 | OK | 50.5 ms |
| RAM end | 0x07F0+16 | OK | 48.7 ms |
| Cart SRAM | 0x6000-0x7FFF | OK | ~50 ms |
| Cart ROM | 0x8000+16 | OK | 50.5 ms |

Note the latency degradation across the 7 reads (11 → 50 ms). The cart was already starting to fall behind.

### Read-array latency (200 ms timeout, 100 samples each)

| Bytes | Mean | p95 | p99 | Timeouts |
|---|---|---|---|---|
| 10 | 11.8 ms | 32.8 ms | 50.4 ms | 50/100 |
| 100 | — | — | — | 100/100 |
| 400 | — | — | — | 100/100 |

### Sustained polling — all 0 Hz actual

| Target | Bytes/poll | Successes | Timeouts |
|---|---|---|---|
| 1 Hz | 400 | 0 | 60 |
| 10 Hz | 400 | 0 | 599 |
| 30 Hz | 400 | 0 | 1784 |
| 60 Hz | 400 | 0 | 3057 |

Stability over 5 min @ 10 Hz × 400 bytes: 0 successes / 2991 timeouts.

**Interpretation:** The game crashed early in the latency phase (visible video glitches → black screen reported by user). All subsequent measurements were against a dead game.

## Run 2 (gentle — small reads only)

Test sizes restricted to 5/10/16 bytes; 50 samples each at 50 ms pacing; 60 s stability.

### Memory regions

All 7 regions reachable in 11-17 ms. Unchanged.

### Read-array latency

| Bytes | Mean | p95 | p99 | Successes/Samples |
|---|---|---|---|---|
| 5 | 16.2 ms | 17.7 ms | 17.9 ms | 50/50 |
| 10 | 16.2 ms | 17.5 ms | 17.7 ms | 47/50 |
| 16 | — | — | — | 0/10 (aborted) |

The mean of 16.2 ms = exactly **one NES frame** (16.67 ms NTSC). This means each USB read response monopolizes a full frame's NMI budget. 16-byte reads aborted after 10 consecutive timeouts → game had crashed.

Sustained + stability skipped due to abort.

## Run 3 (production-shaped)

Tested the bridge's actual intended polling tiers.

### Memory regions

All 7 regions OK, 8-17 ms. Unchanged.

### Sustained workloads

| Tier | Target | Bytes/poll | Successes | Timeouts | Outcome |
|---|---|---|---|---|---|
| Tier 1 (running flag) | 10 Hz × 1 byte | 1 | 97 | 10 | **Aborted at ~11 s** |
| Tier 2 (small chunk) | 5 Hz × 8 bytes | — | — | — | Skipped (Tier 1 aborted) |
| Tier 3 (inventory) | 2 Hz × 32 bytes | — | — | — | Skipped |
| Tier 4 (map chunk) | 0.5 Hz × 128 bytes | — | — | — | Skipped |

Even the lightest possible sustained workload (1 byte at 10 Hz) crashed the game within 11 seconds.

## Key findings

1. **Single-frame budget.** Each USB read response takes one NES frame (~16 ms), so the CC patch monopolizes nearly 100 % of vblank during a request. The game's own NMI handler runs with reduced PPU time, dropping sprite/scroll updates.

2. **Cumulative state corruption.** Crashes correlate with total reads done over time, not raw rate or size. ~100 reads in active gameplay seems to be a ceiling regardless of bytes/read or Hz.

3. **Patch is fine when idle.** The CC-patched ROM runs the overworld stably for minutes with no USB cable attached. The crash is purely a USB-polling-induced cumulative interaction.

4. **Memory access is universal.** RAM (0x0000-0x07FF), cart SRAM (0x6000-0x7FFF), and cart ROM (0x8000+) are all reachable when the cart is responsive. No address-space limitations to worry about.

5. **Read latency is one frame.** 16 ms per response, regardless of read size up to ~10 bytes. Provides a hard upper bound: maximum theoretical sustained rate is 60 Hz, but practical ceiling is much lower due to game-state corruption.

## Recommendations for bridge architecture

The originally planned architecture (10 Hz × full SYNC sweep) is **not viable**. Rough redesign options, in order of preference:

### Option 1: Pause-triggered sync (recommended)

Sync only when the player pauses the game. Z1's pause menu has minimal NMI work (no enemy AI, no scrolling), so the CC patch should service USB requests with much less impact on game state. Workflow:

1. Bridge polls `RUNNING_ADDR` (1 byte) at very low rate (e.g., 0.2 Hz / once per 5 s).
2. When state transitions to "paused" (Z1 state == 0x10), bridge does a full burst-read of all SYNC addresses.
3. Bridge applies any incoming changes from partner during pause.
4. When state transitions back to "running", bridge stops polling.

Tradeoffs: changes only sync at pause boundaries (5-30 s typical). Players accustomed to 60 Hz emu-coop will notice. But this is the only model that respects the CC patch's tolerance.

### Option 2: Burst-and-rest pattern

Burst-read all needed state every 30-60 seconds, sleep in between. ~30-60 sec sync latency.

```
loop:
  read RUNNING_ADDR + tier 1 inventory (~10 reads, ~160 ms)
  sleep 30 s
```

Open question: does the game survive infinite repetition of this? Audits suggest yes if rest is long enough; no firm number. Would need confirmation with another audit cycle.

### Option 3: On-demand sync via in-game flag

Use a designated unused RAM byte as a "send now" trigger. Player presses a button combo; CC patch flag flips; bridge polls that byte at 0.2 Hz; on flag, do burst sync.

Adds complexity but allows infrequent polling with player-driven sync moments.

### Option 4: Don't use this CC patch

If the patch is fundamentally incompatible with continuous sync, an alternative would be to author a new CC patch (or use a different one — e.g., directly probe the patch source for a less invasive NMI hook) that doesn't monopolize vblank. Out of scope for current bridge work.

## Implementation impact on bridge code

- `bridge_cli/__main__.py` `cmd_run`: needs to be rewritten to follow the chosen pattern (Option 1/2/3). Current single-shot scatter-read of all SYNC addresses every 100 ms must go.
- `bridge_gui/session_worker.py`: same rewrite.
- `bridge_core/sync_engine.py`: `is_game_running` / `check_first_running` / `diff` API likely still applies, but called less often and with state from a single burst rather than continuous polling.

## Open questions for follow-up

- Burst-and-rest viability: can the CC patch handle 1 burst of ~10 reads every 30 s indefinitely?
- Pause-mode sustained polling: does the game survive 10 Hz × small reads while paused?
- Write operation behavior: writes are needed when the partner sends updates; we haven't audited write throughput or stability.
- Different CC patch versions: is there a known-better implementation in the krikzz CC ecosystem?
- EDN8 firmware version: not recorded; capture for next run.

These should be addressed before the bridge architecture is finalized.
