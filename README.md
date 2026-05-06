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
instead of an emulator, see [bridge/README.md](bridge/README.md). Same OCI relay,
same session-code workflow, same Z1 modes — just with a USB cable to the cart
instead of FCEUX.

## What changed (v1.4)

- New optional EDN8 hardware bridge (`bridge/`) — Python + CustomTkinter app that lets a real NES with a CC-patched cart join emu-coop sessions as a peer alongside FCEUX clients.
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
