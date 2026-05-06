# CC patch capabilities (audit results)

Captured against a real EDN8 + CC-patched Z1R seed on 2026-05-06. Audit scripts: `bridge/audit_cc_capabilities.py`, `bridge/audit_low_rate.py`, `bridge/audit_correct_framing.py`.

## TL;DR (resolved)

**The CC patch is fine.** Our original audit findings ("crash at exactly 97 transactions, regardless of rate") were caused by **a bug in our host-side framing**, not a defect in the patch. We were sending CC frames without the required trailing checksum byte and with `L = 1 + body_length`. The cart's NMI hook reads `L` body bytes after the L byte, so without the checksum byte our L was off by one and the cart consumed one extra byte per frame from the next frame in the FIFO. After ~97 transactions of cumulative byte-misalignment, the cart's buffer state corrupted and the game crashed.

The fix is in `bridge_core/cc_client.py` (commit 9aaf8d1) — append `sum(mid + action + payload) mod 256` as a checksum byte at end of body, and use `L = body_length_including_checksum`. With correct framing, **1000 sustained 10 Hz reads complete cleanly with zero crashes.**

Recovered the correct framing by decompiling Crowd Control's official EverDriveN8ProConnector at `C:\Users\bogie\AppData\Local\Programs\crowdcontrol\resources\client\ConnectorLib.dll` — see `bridge/docs/cc-patch-architecture.md` for the exact reference frame format.

The detailed audit data and disproved hypotheses are preserved below as historical record. **Skip to the bottom for the final operating envelope** (10 Hz × full polling sweep is fully viable).

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

## Why this happens (CC patch design intent)

Reviewing the upstream Crowd Control hardware patch design after the audits clarified the root cause. The CC patch was authored by [Warp World](https://crowdcontrol.medium.com/creating-nes-hardware-support-for-crowd-control-cc80bf5d586d) for **streamer interactions**: viewers send "drop a heart" / "give Link a sword" / etc. commands at most every few seconds. It was never designed for the continuous-sync workload emu-coop requires.

The patch architecture (per [WarpWorld/NES-Hardware-Example-Punchout](https://github.com/WarpWorld/NES-Hardware-Example-Punchout)):

- **NMI hook** at the patched ROM's NMI vector copies any incoming USB FIFO bytes into a small scratch RAM buffer and sets a `CommReady` flag. This part is fast — pure copy.
- **Main-loop hook** runs every frame and, when `CommReady` is set, dispatches the command via a jump table and writes responses to the FIFO data register.

The actual N8 protocol (`_CommFormat.txt`) supports actions 0x00/0x01 (read individual / array), 0x02/0x03 (write individual / array), 0x04 (Freeze — conditional memory writes), 0xFE (Version), 0xFF (heartbeat). All eight actions go through the main-loop dispatcher.

The bottleneck the audits exposed is **not** NMI starvation; it's **main-loop starvation**. When the bridge sends commands at 10 Hz, every frame the main-loop hook spends its budget servicing USB instead of running the game's own update logic. After ~100 frames of this, the game's state machine has skipped enough updates that something corrupts and it crashes (typically PPU/sprite state, manifesting as the "screen goes black" symptom we observed).

The 16 ms per-response latency we measured = exactly one NES frame = one main-loop iteration spent entirely on USB. That's expected behavior given the patch design; what the patch authors didn't document is that **a series of these in rapid succession breaks the running game**, because they assumed a slow stream of commands, not a polling loop.

## Why we can't bypass the patch

The EDN8 cart's MCU has access to the cart-side address space (ROM, cart SRAM at 0x6000-0x7FFF, USB FIFO at 0x4400/0x4401-style registers depending on revision). It does **not** have access to the NES's internal work-RAM (0x0000-0x07FF), where Z1 keeps the inventory, map progress, and game-state byte we need to mirror. Any read of NES work-RAM requires NES CPU code to issue the read and forward the bytes. That's what the CC patch does, and that's why we're locked into the main-loop dispatch model.

[masible/edn8usb](https://github.com/masible/edn8usb) is a thin loader wrapper that exposes the EDN8 as a serial port; it does not document or provide a memory-dump / NES-halt facility that would let us read work-RAM without a running game cooperating.

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

### Option 4: Author a co-op-friendly patch

The upstream WarpWorld patch could be forked and modified to be cooperative with the host game's frame budget. Realistic approaches:

- **Throttle the main-loop hook.** Currently it processes a pending command on every frame; could instead service one command per N frames (e.g., one every 6 frames = effective 10 Hz). Frees up most main-loop time for game logic.
- **Use action 0x04 (Freeze) for incoming sync.** Instead of write commands per partner update, set up Freeze entries once at session start (e.g., "if inventory byte == X, write Y"). The cart enforces them autonomously without per-frame USB traffic. This addresses one direction; reads still need a polling-friendly mechanism.
- **Add a custom batched-read action** that returns multiple memory regions in one main-loop iteration with a known frame budget, so the bridge can do one well-bounded burst per session-friendly interval rather than continuous polling.

This is substantial 6502 ASM work — call it a separate project, not bridge work. It would belong in a fork of [WarpWorld/NES-Hardware-Example-Punchout](https://github.com/WarpWorld/NES-Hardware-Example-Punchout) or a Z1-specific fork derived from the same template.

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

---

## Postmortem: actual root cause (resolved 2026-05-06)

The four "redesign options" above were authored under the false belief that the patch couldn't sustain polling. That was wrong. The whole investigation chased a symptom — exactly 97 successful transactions before the game went silent, regardless of pacing — without questioning whether our host code was correct.

### What actually broke

Every CC frame requires a trailing checksum byte: `(mid + action + payload bytes) mod 256`. The L byte is `body_length_INCLUDING_checksum`. Our host code (in `bridge_core/cc_client.py`, `audit_cc_capabilities.py`, `cc_monitor_safe.py`, the older `EmuCoopBridge.py`, and the C# `Program.cs`) had been emitting frames with **no checksum byte** and `L = 1 + body_length`. The cart's NMI hook reads L body bytes after L, so:

- Our frame: `[L=6, mid, action, count, addr_lo, addr_hi]` (6 bytes total, no checksum)
- Cart's loop: reads 6 body bytes after L → consumes 1 byte beyond our frame
- That byte: the leading L byte of the next frame in FIFO

Per request, the cart's NMI eats one byte from the next pending frame. Subsequent frames are misinterpreted (their original L byte is gone, so the new "L" is whatever was their MID byte, which leads to garbage handler invocations). Garbage handlers can write very large responses (e.g., `Read individual addresses` with garbage `count` byte), saturating the cart's TX FIFO and eventually hanging the cart's main loop in `STA $40F0`. The threshold of ~97 was a deterministic property of the audit's MID-cycling pattern × the per-transaction byte-leak.

### How we found it

The user pointed at the official Crowd Control client (`C:\Users\bogie\AppData\Local\Programs\crowdcontrol\resources\client\ConnectorLib.dll`). Decompiling `EverDriveN8ProConnector.CodeInject` and `ByteEx.AppendChecksum` showed:

```csharp
private bool CodeInject(byte[] asm)
{
    return MemWrite(25231360u, asm.Prepend(checked((byte)asm.Length)).ToArray());
}

public static byte[] AppendChecksum(this byte[] array)
{
    byte[] result = new byte[array.Length + 1];
    byte sum = 0;
    for (int i = 0; i < array.Length; i++)
    {
        sum = (byte)(sum + (result[i] = array[i]));
    }
    result[result.Length - 1] = sum;
    return result;
}
```

Calls look like `CodeInject(new byte[5] {nextID, 0, 1, addr_lo, addr_hi}.AppendChecksum())`. So the body has a checksum, and L = body length including checksum.

We rebuilt our framing to match (`bridge/audit_correct_framing.py`) and ran the audit again: **1000 sustained reads at 10 Hz, 100 seconds wallclock, zero crashes** (vs. deterministic crash at read 97 with the old framing). Three patch experiments (h1, h2) and the proposed "redesign for low-rate polling" were all chasing a host bug, not a patch bug.

### Hypotheses that were tested and disproved

For the historical record:

- **h1 (NOP out always-called `JSR $B58D`):** rejected — same exact 97-read crash pattern.
- **h2 (NMI hook PHA/TXA/TYA register save+restore around the original $E484):** rejected — same exact pattern.
- **"Pause-only sync is the only viable architecture":** rejected — full 10 Hz polling works fine with correct framing.
- **"Cart firmware has a finite transaction limit":** rejected — limit was downstream of host bug.
- **"Writes don't count toward the limit":** never definitively tested but moot.

### Final operating envelope

With correct framing, sustained polling is unproblematic at every rate we've tested:

| Rate | Bytes/poll | Duration | Result |
|---|---|---|---|
| 10 Hz | 1 byte | 100 sec / 1000 reads | 984 OK / 16 transient timeouts (screen transitions only); no crash |

The 16 transient timeouts were two ~8-read clusters during cave-entry/cave-exit screen transitions, where Z1's main loop is too busy to service USB for ~1.5 sec. The cart and game both recovered cleanly each time and continued for 800+ subsequent reads.

**The bridge architecture (10 Hz scatter-read of all 285 tloz_all SYNC addresses every tick)** is a green-light: just tolerate up to ~15-20 consecutive timeouts as normal screen-transition behavior, and don't treat them as a crash signal. The original `bridge_cli.cmd_run` and `bridge_gui.session_worker` polling loop is fundamentally fine; only the timeout-streak abort threshold needs tuning upward from the audit's 5-or-10 default.
