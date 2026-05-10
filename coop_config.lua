-- FCEUX connection fallback.
--
-- The normal connection dialog uses IUP. Some 64-bit FCEUX builds run Lua on a
-- thread where IUP cannot open a dialog. If that happens, set enabled = true
-- here, enter the shared session code, save the file, and reload coop.lua.

return {
	enabled = false,

	-- "relay" is the normal internet play path. "direct" is for LAN/Tailscale.
	kind = "relay",
	host_addr = "129.158.62.225",
	port = 9999,
	code = "",

	-- Direct mode only.
	isHost = false,

	-- Set true when intentionally restoring state after a crash.
	forceSend = false,

	-- Optional: used only if coop.lua cannot auto-detect exactly one mode.
	-- Accepts a mode GUID or full mode name.
	-- mode = "The Legend of Zelda (sync most things)",
}
