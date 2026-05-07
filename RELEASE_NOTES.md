# emu-coop-plus v2.0 beta 2 — release notes

Second community-testing build of the EDN8 hardware bridge for emu-coop. Re-rolls v2.0 beta 1 with a compatibility fix for additional Z1R seed flagsets that the first beta couldn't apply cleanly. This is a **pre-release**; expect rough edges around reconnect timing and rare error paths. Stable v2.0 follows after community testing.

## Which file do I download?

| You play on… | Download | Size |
|---|---|---|
| **A real NES with an Everdrive Pro N8 cart** | `emu-coop-plus-2.0-beta2-edn8.exe` | ~11 MB |
| **FCEUX (or anything Lua-compatible)** | `emu-coop-plus-2.0-beta2-fceux.zip` | ~few hundred KB |

You can also play **EDN8 against FCEUX** — that's the headline feature of this release. Both ends use the same shared cloud relay; they pair by an agreed-on session code.

## What's new in v2.0 beta 2

- **ROM patch is now compatible with more Z1R seeds.** Some Z1R flagsets fill bank 6 with seed-specific data, which conflicted with where the previous patch placed its USB protocol code. The patch is now relocated to bank 4's free space (clean across every Z1R flagset audited) and a small piece moved to safe bank-7 free space behind the NMI vectors. If you tried v2.0 beta 1 against a seed and saw a corrupted overworld, beta 2 should fix it.
- **Build/release tooling unified.** The repo now has a single `build-all.ps1` at the root that builds every endpoint, with each artifact landing in its own `dist/<endpoint>/` folder for cleaner organization as more endpoints (MiSTer, etc.) are added in the future.

## Full feature set

### EDN8 hardware bridge (new)

A standalone Windows app (no Python install required) that lets a real NES with an Everdrive Pro N8 cart play emu-coop alongside FCEUX peers. Works with vanilla Z1, Z1R seeds, or any Z1-derived ROM.

- Three-screen GUI: pick your ROM → configure session → play
- Auto-detects the EDN8's COM port at the top of the dropdown
- Patches your ROM with the emu-coop-plus IPS in one click
- Uploads the patched ROM straight to your EDN8's SD card via USB (auto-creates `sd:\emu-coop-plus\`); reset returns to the EDN8 menu, no re-uploading on reset
- Talks to the same OCI relay as FCEUX peers; pairs by session code
- Auto-reconnects on network drops on both sides

### Three Z1 modes ported to the bridge

| Mode | Syncs |
|---|---|
| `tloz_basic` | Inventory only (sword, bow, candle, rings, etc.) |
| `tloz_progress` | Inventory + level compasses/maps + triforce pieces |
| `tloz_all` | Inventory + progress + full overworld map + full dungeon map |

Pick the mode that matches the workload you want; both peers must use the same mode.

### Reconnect machinery hardened

Both Lua and bridge sides now correctly handle a partner disconnect at any point in a session. The relay distinguishes a survivor reconnecting from a dropped peer returning, and accepts fresh peer-ids on each launch (Lua and the bridge generate new ones each time, so strict matching used to break restart-and-reconnect).

## Held back to v2.1

- **Bogie's DIBS! competitive modes** (`tloz_dibs_easy`, `tloz_dibs_medium`, `tloz_dibs_medium_entrances_on`). DIBS! needs a few sync-engine extensions — handler-driven writes to addresses other than the synced one, and structured (non-scalar) wire values. Rather than ship FCEUX-only DIBS! and confuse testers when their EDN8 partner can't pair on those modes, we hold all three until the bridge can host them too.
- **MiSTer NES core bridge.** Read-side is feasible today (the [odelot/NES_MiSTer](https://github.com/odelot/NES_MiSTer) fork mirrors NES RAM into MiSTer's DDRAM for RetroAchievements); write-back requires an FPGA HDL change. Future work.

## Quick start

### EDN8 / real NES players

1. Download `emu-coop-plus-2.0-beta1-edn8.exe`
2. Plug your EDN8 into your PC over USB and into your NES, then power on the NES
3. Run the .exe — three-screen flow walks you through ROM patching, USB upload, relay connection, and pairing
4. On the EDN8's on-screen menu, navigate into the new `emu-coop-plus` folder and pick the patched ROM to launch the game
5. Agree on a session code with your partner (any 6+ char string), enter it in both clients, and play

### FCEUX players

1. Download `emu-coop-plus-2.0-beta1-fceux.zip` and extract anywhere
2. Launch FCEUX, load your Z1 ROM
3. From the FCEUX Lua menu, load `coop.lua` from the extracted folder
4. In the connection dialog: Transport=Relay, Host=`129.158.62.225`, Port=`9999`, Session code=your shared code, Mode=`tloz_basic` / `tloz_progress` / `tloz_all`
5. Click OK and play

The FCEUX side has additional modes (`lttp`, `lttp_randomizer`, `super_metroid`, plus `tloz_basic_alt`, `tloz_all_alt_hdn`, etc.) that the bridge doesn't host yet. Those still work for FCEUX-to-FCEUX play.

## Known issues

- If both peers drop simultaneously and the relay's slot times out (60-second grace window), reconnects will report `Partner aborted: no partner` until you change the session code or wait for the cleanup. Workaround: pick a fresh code or restart both sides.
- The bridge's heartbeat fires every 5 seconds. During Z1 cave/screen transitions the cart is too busy to service USB for ~1.5 seconds; you may see brief timeouts in the bridge's Log tab during transitions. They self-recover and aren't a sync failure.
- The patched ROM uploaded to your EDN8 is your own copyrighted property — don't redistribute it. Patch your own seed; share the IPS, not the ROM.

## Reporting issues

GitHub issues: <https://github.com/BogieSmalls/emu-coop-z1/issues>

When reporting, please include: which artifact you used (.exe / .zip), what mode you were running, what the bridge's Log tab and FCEUX's message console showed, and what you were doing when the issue happened.

## Credits

- **Andi McClure** — original emu-coop framework
- **megmacAttack** — the `tloz_*` Z1 mode files
- **Bogie** — emu-coop-plus EDN8 bridge, relay deployment, DIBS! competitive modes (held for v2.1)
- **Warp World** — Crowd Control project (related upstream work in the NES hardware space)
- **odelot** — NES_MiSTer fork that opens the door to a future MiSTer bridge
