require "iuplua"

-- Bizarre kludge: For reasons I do not understand at all, radio buttons do not work in FCEUX. Switch to menus there only
local optionLetter = "o"
if FCEU then optionLetter = "l" end

function connectionDialog()
  local res, transport, host_addr, port, code, isHost, forceSend = iup.GetParam(
    "Connection settings", nil,
    "Transport: %" .. optionLetter .. "|Direct (LAN/Tailscale)|Relay (via OCI server)|\n" ..
    "Host address (Direct: peer's IP, or relay address): %s\n" ..
    "Port: %i\n" ..
    "Session code (Relay only, 6+ chars): %s\n" ..
    "Are you the host? (Direct only) %" .. optionLetter .. "|No|Yes|\n" ..
    "%t\n" ..
    "Are you restarting\rafter a crash? %" .. optionLetter .. "|No|Yes|\n",
    0, "127.0.0.1", 9999, "", 0, 0)

  if 0 == res then return nil end

  local kind = (transport == 0) and "direct" or "relay"
  return {
    kind = kind,
    host_addr = host_addr,
    port = port,
    code = code,
    isHost = (isHost == 1),
    forceSend = (forceSend == 1),
  }
end

-- Backwards-compatible alias for any code still calling the old name.
ircDialog = connectionDialog

function selectDialog(specs, reason)
	local names = ""
	for i, v in ipairs(specs) do
		names = names .. v.name .. "|"
	end

	local res, selection = iup.GetParam("Select game", nil,
	    "Can't figure out\rwhich game to load\r(" .. reason .. ")\r" ..
	    "Which game is this? " ..
		"%l|" .. names .. "\n",
		0)

	if 0 == res or nil == selection then return nil end

	return specs[selection + 1]
end

function refuseDialog(options)
	iup.Message("Cannot run", "No ROM is running.")
end
