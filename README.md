This is the source code repo for emu-coop. **[Probably you would rather be looking at the project webpage](https://mcclure.github.io/emu-coop/), which has more detail and a downloadable SNES emulator for Windows.**

# emu-coop

This directory contains some Lua scripts that, when loaded by a compliant emulator such as snes9x-rr or FCEUX, can synchronize emulator state over the internet (allowing "cooperative" playthroughs of single-player games).

Each game you want to use this with requires a "mode" file in the modes/ directory. Currently included are modes for Link to the Past, the Link to the Past "Randomizer", Zelda 1 and Super Metroid. **WARNING: Modes are PROGRAMS, like a .exe file. Do not install a mode file unless it came from someone you know and trust.** 

To run, run coop.lua. To run with additional debug messages (more verbose errors, and visibility for every message sent) run debug.lua instead.

## Connection modes

emu-coop supports two transports:

- **Direct** — peer-to-peer TCP. One player hosts (listens on a port), the other connects to their address. Best for LAN co-op or players using Tailscale / ZeroTier / Hamachi (which give a routable virtual IP without router setup).
- **Relay** — both players connect outbound to a small Python relay daemon. No port forwarding required. Self-hosters can run their own (see [relay/README.md](relay/README.md)) on a $5/mo VPS or an Oracle Cloud Always Free VM.

When you launch `coop.lua`, the connection dialog asks which transport to use.

### Quick start (Relay, easiest)

1. Both players agree on a session code (any string >= 6 chars, e.g. `pancakes123`). Share via Discord/etc.
2. Both players launch FCEUX -> load ROM -> load `coop.lua`.
3. In the connection dialog: Transport=Relay, Host address=`<relay public IP>`, Port=`9999`, Session code=your shared code. Click OK.
4. Both screens display "Connected to partner" within ~1 second.

### Quick start (Direct, LAN)

1. The host player runs `ipconfig` (Windows) or `ifconfig` (mac/linux) to find their LAN IP.
2. Host: launch `coop.lua`, Transport=Direct, Host address=`0.0.0.0`, Port=`9999`, Are you the host?=Yes.
3. Other player: launch `coop.lua`, Transport=Direct, Host address=`<host's LAN IP>`, Port=`9999`, Are you the host?=No.

## EDN8 hardware bridge

If you want to play emu-coop on a real NES with an [Everdrive Pro N8](https://krikzz.com/store/home/55-everdrive-n8-pro-nes.html)
instead of an emulator, see [bridge/README.md](bridge/README.md). Same shared
cloud relay, same session-code workflow, same Z1 modes — just with a USB cable
to the cart instead of FCEUX.

## What's new in v2.0 beta 3

- PRG1 (Rev A) Z1 ROM support. Both PRG0 and PRG1 vanilla ROMs are now supported by a single IPS — the title-screen rename has been shortened to `EMU-COOP` and repositioned into a region that is blank padding in both revisions.
- Patch-time validator. The bridge now refuses to apply the patch if the input ROM has been modified at any of the regions the patch needs to write into, and reports the conflicting offsets. Vanilla and clean Z1R seeds apply as before.

## What's new in v2.0 beta 2

- ROM patch is now compatible with more Z1R seeds. Some Z1R flagsets fill bank 6 with seed-specific data, which conflicted with where the previous patch placed its USB protocol code; the patch is now relocated to safe ROM regions clean across every Z1R flagset audited.
- Build/release tooling unified — single `build-all.ps1` at the repo root, per-endpoint output under `dist/<endpoint>/` for cleaner organization as more endpoints get added.

## What changed (v2.0 beta 1)

First beta of the **emu-coop-plus** stack — a real NES playing co-op over the internet alongside FCEUX peers. Snapshot for community testing.

- **EDN8 hardware bridge** — three Z1 modes (`tloz_basic`, `tloz_progress`, `tloz_all`) work end-to-end on real hardware. GUI auto-detects the EDN8's COM port, patches your ROM, and uploads it to the cart's SD card in one click.
- **Reconnect machinery hardened.** Both Lua and bridge survive a partner disconnect/reconnect at any point; the relay correctly handles dropped peers and accepts fresh per-launch peer-ids.
- **Bumped to 2.0 beta1**. The Lua compat-version checker treats `beta` as a variant — beta clients only pair with beta clients, protecting stable users from talking to a pre-release build.

**Held back to v2.1:** the DIBS! competitive modes (`tloz_dibs_easy`, `tloz_dibs_medium`, `tloz_dibs_medium_entrances_on`) — they need a few bridge-side sync-engine extensions to ship cleanly on both FCEUX and EDN8 simultaneously, so we hold all three until the bridge can host them too.

## What changed (v1.5)

- EDN8 hardware bridge end-to-end working — a real NES + Everdrive Pro N8 can play emu-coop with an FCEUX peer over the shared cloud relay.
- Bridge polling uses ArrayRead over a small set of contiguous ranges, which is light enough on the cart that Z1's title→overworld transitions complete cleanly while the bridge is connected.
- Bridge GUI auto-detects the EDN8 (USB Serial Device, VID 0483) and lists it first in the COM port dropdown.

## What changed (v1.4)

- New optional EDN8 hardware bridge (`bridge/`) — Python + CustomTkinter app that lets a real NES join emu-coop sessions as a peer alongside FCEUX clients.
- Bundled as a single ~11 MB `bridge.exe` for Windows; macOS support is best-effort.

## What changed (v1.3)

- IRC is no longer used. Replaced by Direct + Relay transports.
- Connection drops auto-recover within ~30 seconds without restarting either emulator (heartbeat-driven detection + automatic reconnect with exponential backoff).
- "Restarting after a crash?" still works for full save-and-reload recovery in case the auto-recovery doesn't catch all desyncs.
- Wire format is now length-prefixed JSON frames (capped at 4 KiB), designed so a future PC-side bridge process can speak the same protocol — opening the door to non-Lua peers (Bizhawk via memory-poll bridge, real NES via Everdrive Pro N8 USB bridge, etc.).
- The relay daemon is a separate, stateless asyncio TCP server in `relay/` — see `relay/README.md` for deployment.

## Author / License

These files were written by <<andi.m.mcclure@gmail.com>>. The "tloz_" modes (Zelda 1) were written by megmacAttack.

Big thanks to:
* The LTTP Randomizer team, esp. Mike Trethewey, Zarby89 and Karkat, for information
* Alex Zandra, Maya Shinohara, and Andypro1 from github for help testing

Unless otherwise noted, the license is:

	Copyright (C) 2017 Andi McClure

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF
	ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
	TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
	PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT
	SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
	ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
	ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
	OR OTHER DEALINGS IN THE SOFTWARE.

Included in this directory is Penlight. Here is its license:

	Copyright (C) 2009-2016 Steve Donovan, David Manura.

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF
	ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
	TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
	PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT
	SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
	ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
	ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
	OR OTHER DEALINGS IN THE SOFTWARE.

Included in this directory is Luasocket. Here is its license:

	LuaSocket 3.0 license
	Copyright © 2004-2013 Diego Nehab

	Permission is hereby granted, free of charge, to any person obtaining a
	copy of this software and associated documentation files (the "Software"),
	to deal in the Software without restriction, including without limitation
	the rights to use, copy, modify, merge, publish, distribute, sublicense,
	and/or sell copies of the Software, and to permit persons to whom the
	Software is furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
	FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
	DEALINGS IN THE SOFTWARE.

Included in this directory is IUP. Here is its license:

	Copyright (c) 1994-2017 Tecgraf/PUC-Rio.

	Permission is hereby granted, free of charge, to any person obtaining a
	copy of this software and associated documentation files (the "Software"),
	to deal in the Software without restriction, including without limitation
	the rights to use, copy, modify, merge, publish, distribute, sublicense,
	and/or sell copies of the Software, and to permit persons to whom the
	Software is furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
	FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
	DEALINGS IN THE SOFTWARE.
