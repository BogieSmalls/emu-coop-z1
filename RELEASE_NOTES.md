# emu-coop-plus v2.0 beta 4 - release notes

Fourth community-testing build of the emu-coop-plus bridge. Beta4 adds MiSTer hardware support alongside the EDN8 flow, with the bridge able to deploy the MiSTer helper/core payload and run two-way sync against FCEUX. This is a pre-release; expect rough edges around reconnect timing and rare error paths. Stable v2.0 follows after community testing.

## Which file do I download?

| You play on... | Download | Size |
|---|---|---|
| **Hardware bridge: EDN8 or MiSTer** | `emu-coop-plus-2.0-beta4-hardware.exe` | ~19 MB |
| **FCEUX or another Lua-compatible emulator** | `emu-coop-plus-2.0-beta4-fceux.zip` | ~few hundred KB |

You can play EDN8 or MiSTer against FCEUX. Both ends use the same shared cloud relay and pair by an agreed-on session code.

## What's new in v2.0 beta 4

- **MiSTer hardware bridge support.** The bridge now has a device choice screen, MiSTer SSH setup, ROM staging under `/media/fat/games/NES/emu-coop-plus/`, and helper/core deployment.
- **Two-way MiSTer sync.** The beta4 MiSTer path uses the bundled `NES_emu-coop.rbf` core plus `mister-helper.py` to read/write game memory through the same sync engine used by FCEUX and EDN8.
- **Generic release layout.** Emulator builds now land in `dist/emu/` and the bridge app lands in `dist/hardware/`.

## What's new in v2.0 beta 3

- **PRG1 (Rev A) ROM support.** Both PRG0 and PRG1 vanilla Z1 ROMs are supported by the same patch. The title-screen rename is shortened to `EMU-COOP` and placed in blank padding shared by both revisions.
- **Patch-time validator.** The bridge checks every ROM region the patch needs and refuses to apply if the input has been modified there. Vanilla and clean Z1R seeds apply as before.

## What's new in v2.0 beta 2

- **ROM patch is compatible with more Z1R seeds.** The patch moved to ROM regions that are clean across every Z1R flagset audited.
- **Build/release tooling unified.** `build-all.ps1` builds every endpoint, with artifacts landing in per-endpoint folders under `dist/`.

## Full feature set

### Hardware bridge

A standalone Windows app that lets hardware endpoints play emu-coop alongside FCEUX peers. EDN8 and MiSTer are supported in beta4. Works with vanilla Z1, Z1R seeds, or any Z1-derived ROM.

- Choose EDN8 or MiSTer from the first screen.
- EDN8 flow patches the ROM and uploads it to `sd:\emu-coop-plus\`.
- MiSTer flow deploys `NES_emu-coop.rbf` and `mister-helper.py` over SSH/SCP, then stages ROMs under `/media/fat/games/NES/emu-coop-plus/`.
- Talks to the same OCI relay as FCEUX peers and pairs by session code.
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

1. Download `emu-coop-plus-2.0-beta4-hardware.exe`.
2. For EDN8, plug your EDN8 into your PC over USB and into your NES, then power on the NES. For MiSTer, make sure SSH is enabled and the MiSTer is reachable on your network.
3. Run the .exe. The flow walks you through hardware choice, ROM setup, relay connection, and pairing.
4. For EDN8, launch the patched ROM from the `emu-coop-plus` folder on the cart menu. For MiSTer, launch the deployed `NES_emu-coop` core and staged ROM.
5. Agree on a session code with your partner, enter it in both clients, and play.

### FCEUX players

1. Download `emu-coop-plus-2.0-beta4-fceux.zip` and extract anywhere.
2. Launch FCEUX, load your Z1 ROM.
3. From the FCEUX Lua menu, load `coop.lua` from the extracted folder.
4. In the connection dialog: Transport=Relay, Host=`129.158.62.225`, Port=`9999`, Session code=your shared code, Mode=`tloz_basic` / `tloz_progress` / `tloz_all`.
5. Click OK and play.

The FCEUX side has additional modes (`lttp`, `lttp_randomizer`, `super_metroid`, plus `tloz_basic_alt`, `tloz_all_alt_hdn`, etc.) that the bridge does not host yet. Those still work for FCEUX-to-FCEUX play.

## Known issues

- If both peers drop simultaneously and the relay's slot times out, reconnects may report `Partner aborted: no partner` until you change the session code or wait for cleanup.
- EDN8 USB servicing can briefly stall during some Z1 transitions; bridge log timeouts during those windows usually self-recover.
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
