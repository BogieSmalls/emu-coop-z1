# emu-coop bridge

Connect a real NES + Everdrive Pro N8 to emu-coop sessions, alongside FCEUX peers.

## What this is

A Windows app (with macOS support best-effort) that:
- Patches a Z1 ROM with the CC USB protocol
- Uploads it to your EDN8 (or you can copy manually)
- Talks to the cart over USB serial to read/write game memory
- Connects to the emu-coop relay on the internet
- Pairs with a partner running FCEUX (or another bridge)
- Syncs items, dungeon progress, and other game state in real time

## Quick start

1. **Download `bridge.exe`** (single file, ~11 MB).
2. **Plug in your EDN8** to a USB port.
3. **Run `bridge.exe`** — it walks you through:
   - Picking your Z1 ROM (vanilla or Z1R seed; both work)
   - Auto-detecting your EDN8's COM port
   - Choosing a session code (any 6+ char string you and your partner agree on)
   - Connecting to the relay
4. **Launch the patched ROM** on your NES via the EDN8 menu.
5. **Play co-op.**

## Modes

The bridge currently supports `tloz_all` (Zelda 1, syncs items + map progress).
Both peers must select the same mode. Future modes will be added by porting from
the FCEUX-side `modes/*.lua` files.

## CLI usage (advanced)

If you don't want the GUI:

```powershell
# Patch a ROM
python -m bridge_cli patch zelda.nes -o zelda_CC.nes

# Run a session
python -m bridge_cli run --mode tloz_all --port COM3 --code mycode
```

## Troubleshooting

### "Could not open COM port"

EDN8 isn't plugged in, or another program is holding the port. Close any other
program using the cart and click Connect again.

### "Partner has incompatible mode (guid mismatch)"

You and your partner picked different modes. Both peers must use the same mode
(e.g., both `tloz_all`).

### "Connection lost (heartbeat timeout)"

Network drop. Bridge auto-reconnects with exponential backoff. Should recover
within ~30 seconds when the network is back.

### My inventory shows a phantom Heart Container or bomb upgrade

This is a known emu-coop quirk (not specific to the bridge). When you and your
partner connect on the title screen and then start a new game, the cache snapshot
can race ahead of the game's initial inventory writes. Workaround: load a save
state of an already-running game on both peers before connecting.

## Development

See the architectural design at
`docs/superpowers/specs/2026-05-06-edn8-bridge-design.md`.

To set up for development:

```powershell
cd bridge
uv sync --extra test --extra dist
uv run python -m pytest tests/ -v
uv run python -m bridge_gui  # run the GUI
uv run python -m bridge_cli --help  # CLI options
```

To build a Windows distributable:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
# Output: dist/bridge.exe
```
