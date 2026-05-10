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

	-- Required when 64-bit FCEUX cannot open the IUP mode selection dialog and
	-- multiple modes match the loaded ROM. Accepts a mode GUID or full mode name.
	--
	-- Zelda 1 mode choices:
	--   The Legend of Zelda (sync items only)
	--   The Legend of Zelda (sync normal and progress items)
	--   The Legend of Zelda (sync most things)
	-- mode = "The Legend of Zelda (sync most things)",
}
