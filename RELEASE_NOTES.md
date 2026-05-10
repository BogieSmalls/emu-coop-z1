# emu-coop-plus v2.0 beta 5 - release notes

Fifth community-testing build of the emu-coop-plus bridge. Beta5 focuses on EDN8 `tloz_all` safety, FCEUX package bitness, hardware bridge version reporting, and smoother MiSTer setup.

This is a pre-release. Keep bridge logs handy while validating hardware sessions, especially EDN8 `tloz_all`.

## Which file do I download?

| You play on... | Download | Size |
|---|---|---|
| **Hardware bridge: EDN8 or MiSTer** | `emu-coop-plus-2.0-beta5-hardware.exe` | ~19 MB |
| **32-bit FCEUX** | `emu-coop-plus-2.0-beta5-fceux-win32.zip` | ~540 KB |
| **64-bit FCEUX** | `emu-coop-plus-2.0-beta5-fceux-win64.zip` | ~1.3 MB |

Any two endpoints can be paired together: FCEUX, EDN8, or MiSTer. FCEUX <-> FCEUX, FCEUX <-> EDN8, FCEUX <-> MiSTer, EDN8 <-> MiSTer, EDN8 <-> EDN8, and MiSTer <-> MiSTer all use the same shared cloud relay and pair by an agreed-on session code.

## What's new in v2.0 beta 5

- **EDN8 `tloz_all` write safety.** Hardware-side map writes are now gated and rate-limited so a large incoming map burst does not hammer the EDN8 USB path.
- **Stronger snapshot validation.** The hardware bridge rejects implausible local snapshots, implausible incoming partner values, and masked map values with impossible bits before they can be broadcast or written.
- **Better EDN8 transition handling.** Running-state transients during Zelda 1 screen transitions no longer immediately flush map diffs or stop sync work.
- **Startup noise cleanup.** Initial bomb-capacity deltas are suppressed so starting a seed does not announce misleading "got rid of bombs" / "bomb upgrade" messages.
- **Separate FCEUX packages.** 32-bit and 64-bit FCEUX now have separate zips with matching native IUP/IUPLua/LuaSocket modules.
- **64-bit FCEUX config fallback.** If a 64-bit FCEUX build cannot open the IUP dialog from Lua, `coop_config.lua` can provide relay/session settings directly. The fallback config ships disabled, with the Zelda 1 "sync most things" mode line ready to edit.
- **Hardware version reporting.** Hardware app hellos now report the release version (`2.0 beta5`) instead of the internal package version.
- **MiSTer setup polish.** The hardware setup window opens taller and the MiSTer flow is scrollable so the Continue button remains reachable.
- **Hardware app icon.** The Windows hardware bridge now uses the Gannon "shyboi" icon.
- **Relay diagnostics.** Relay payload tracing remains available for beta validation and makes sender/receiver behavior visible in `journalctl`.

## What's new in v2.0 beta 4

- **MiSTer hardware bridge support.** The bridge added a device choice screen, MiSTer SSH setup, ROM staging under `/media/fat/games/NES/emu-coop-plus/`, and helper/core deployment.
- **Two-way MiSTer sync.** The MiSTer path uses the bundled `NES_emu-coop.rbf` core plus `mister-helper.py` to read/write game memory through the same sync engine and relay protocol used by FCEUX and EDN8.
- **Generic release layout.** Emulator builds now land in `dist/emu/` and the bridge app lands in `dist/hardware/`.

## What's new in v2.0 beta 3

- **PRG1 (Rev A) ROM support.** Both PRG0 and PRG1 vanilla Z1 ROMs are supported by the same patch. The title-screen rename is shortened to `EMU-COOP` and placed in blank padding shared by both revisions.
- **Patch-time validator.** The bridge checks every ROM region the patch needs and refuses to apply if the input has been modified there. Vanilla and clean Z1R seeds apply as before.

## What's new in v2.0 beta 2

- **ROM patch is compatible with more Z1R seeds.** The patch moved to ROM regions that are clean across every Z1R flagset audited.
- **Build/release tooling unified.** `build-all.ps1` builds every endpoint, with artifacts landing in per-endpoint folders under `dist/`.

## Full feature set

### Hardware bridge

A standalone Windows app that lets hardware endpoints play emu-coop through the shared relay. EDN8 and MiSTer are supported in beta5, and either can pair with FCEUX or another hardware bridge endpoint. Works with vanilla Z1, Z1R seeds, or any Z1-derived ROM.

- Choose EDN8 or MiSTer from the first screen.
- EDN8 flow patches the ROM and uploads it to `sd:\emu-coop-plus\`.
- MiSTer flow deploys `NES_emu-coop.rbf` and `mister-helper.py` over SSH/SCP, then stages ROMs under `/media/fat/games/NES/emu-coop-plus/`.
- Talks to the same OCI relay as FCEUX and pairs by session code, so endpoint combinations are interchangeable as long as both clients choose the same mode.
- Auto-reconnects on network drops on both sides.

### Three Z1 modes ported to the bridge

| Mode | Syncs |
|---|---|
| `tloz_basic` | Inventory only: sword, bow, candle, rings, etc. |
| `tloz_progress` | Inventory plus level compasses/maps and triforce pieces |
| `tloz_all` | Inventory, progress, full overworld map, and full dungeon map |

Pick the mode that matches the workload you want; both peers must use the same mode.

## Held back to v2.1

- **Bogie's DIBS! competitive modes** (`tloz_dibs_easy`, `tloz_dibs_medium`, `tloz_dibs_medium_entrances_on`). DIBS! needs a few sync-engine extensions: handler-driven writes to addresses other than the synced one, and structured non-scalar wire values.

## Quick start

### Hardware bridge players

1. Download `emu-coop-plus-2.0-beta5-hardware.exe`.
2. For EDN8, plug your EDN8 into your PC over USB and into your NES, then power on the NES. For MiSTer, make sure SSH is enabled and the MiSTer is reachable on your network.
3. Run the .exe. The flow walks you through hardware choice, ROM setup, relay connection, and pairing.
4. For EDN8, launch the patched ROM from the `emu-coop-plus` folder on the cart menu. For MiSTer, launch the deployed `NES_emu-coop` core and staged ROM.
5. Agree on a session code with your partner, enter it in both clients, and play.

### FCEUX players

1. Download the FCEUX zip that matches your emulator bitness: `emu-coop-plus-2.0-beta5-fceux-win32.zip` for 32-bit FCEUX, or `emu-coop-plus-2.0-beta5-fceux-win64.zip` for 64-bit FCEUX.
2. Extract the zip anywhere.
3. Launch FCEUX and load your Z1 ROM.
4. From the FCEUX Lua menu, load `coop.lua` from the extracted folder.
5. In the connection dialog: Transport=Relay, Host=`129.158.62.225`, Port=`9999`, Session code=your shared code, Mode=`tloz_basic` / `tloz_progress` / `tloz_all`.
6. Click OK and play.

If your FCEUX build cannot open the dialog and reports `Must call iup.Open in main thread`, edit `coop_config.lua` next to `coop.lua`, set `enabled = true`, enter the shared session code, confirm the `mode` line, save, and reload `coop.lua`.

The FCEUX side has additional modes (`lttp`, `lttp_randomizer`, `super_metroid`, plus `tloz_basic_alt`, `tloz_all_alt_hdn`, etc.) that the bridge does not host yet. Those still work for FCEUX-to-FCEUX play.

## Known issues

- If both peers drop simultaneously and the relay's slot times out, reconnects may report `Partner aborted: no partner` until you change the session code or wait for cleanup.
- EDN8 USB servicing can briefly stall during some Z1 transitions; bridge log timeouts during those windows usually self-recover.
- EDN8 `tloz_all` is still the highest-load hardware mode. If you see repeated "Game stopped running" or implausible snapshot warnings, capture the hardware log and relay payload lines.
- Some FCEUX builds cannot show IUP dialogs from Lua. Use the matching win32/win64 package first, then use the `coop_config.lua` fallback if the dialog still cannot open.
- The patched ROM uploaded to your EDN8 is your own copyrighted property. Do not redistribute it. Patch your own seed; share the IPS, not the ROM.

## Reporting issues

GitHub issues: <https://github.com/BogieSmalls/emu-coop-z1/issues>

When reporting, include which artifact you used, what mode you were running, what the bridge log and FCEUX console showed, and what you were doing when the issue happened.

## Credits

- **Andi McClure** - original emu-coop framework
- **megmacAttack** - the `tloz_*` Z1 mode files
- **Bogie** - emu-coop-plus EDN8/MiSTer bridge, relay deployment, DIBS! competitive modes
- **Warp World** - Crowd Control project, related upstream work in the NES hardware space
- **odelot** - NES_MiSTer fork that opened the path for MiSTer support
