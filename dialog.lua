local iupOk, iupLoadError = pcall(require, "iuplua")
local iupUnavailableShown = false

local function showIupUnavailable()
	if iupUnavailableShown then return end
	iupUnavailableShown = true

	local details = tostring(iupLoadError)
	print("Cannot load FCEUX connection dialog DLL: " .. details)
	if details:find("not a valid Win32 application", 1, true) then
		print("This usually means 64-bit FCEUX is loading the 32-bit FCEUX package.")
	else
		print("This usually means the FCEUX package does not match your emulator bitness.")
	end
	print("Use 32-bit FCEUX with the fceux-win32 package, or 64-bit FCEUX with the fceux-win64 package.")
	errorMessage("Dialog DLL unavailable; use a FCEUX package matching your emulator bitness.")
end

-- Bizarre kludge: For reasons I do not understand at all, radio buttons do not work in FCEUX. Switch to menus there only
local optionLetter = "o"
if FCEU then optionLetter = "l" end

function connectionDialog()
	if not iupOk then
		showIupUnavailable()
		return nil
	end

	local res, transport, host_addr, port, code, isHost, forceSend = iup.GetParam(
	    "Connection settings", nil,
	    "Transport: %" .. optionLetter .. "|Direct (LAN/Tailscale)|Relay (via OCI server)|\n" ..
		"Host address (Direct: peer's IP, or relay address): %s\n" ..
		"Port: %i\n" ..
		"Session code (Relay only, 6+ chars): %s\n" ..
		"Are you the host? (Direct only) %" .. optionLetter .. "|No|Yes|\n" ..
		"%t\n" ..
		"Are you restarting\rafter a crash? %" .. optionLetter .. "|No|Yes|\n",
	    1, "129.158.62.225", 9999, "", 0, 0)

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

function selectDialog(specs, reason)
	if not iupOk then
		showIupUnavailable()
		return nil
	end

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
	if not iupOk then
		showIupUnavailable()
		return
	end

	iup.Message("Cannot run", "No ROM is running.")
end
