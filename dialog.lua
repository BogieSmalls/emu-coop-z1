local iupOk, iupLoadError = pcall(require, "iuplua")
local iupUnavailableShown = false
local connectionConfigLoaded = false
local connectionConfig = nil
local connectionConfigError = nil

local function loadConnectionConfig()
	if connectionConfigLoaded then return connectionConfig end
	connectionConfigLoaded = true

	package.loaded["coop_config"] = nil
	local ok, result = pcall(require, "coop_config")
	if not ok then
		connectionConfigError = result
		return nil
	end

	if type(result) == "table" then
		connectionConfig = result
	elseif type(coopConfig) == "table" then
		connectionConfig = coopConfig
	else
		connectionConfigError = "coop_config.lua did not return a table"
	end

	return connectionConfig
end

local function normalizeConnectionConfig(config)
	if type(config) ~= "table" or config.enabled == false then return nil end

	local normalized = {
		kind = config.kind or "relay",
		host_addr = config.host_addr,
		port = tonumber(config.port),
		code = config.code or "",
		isHost = config.isHost == true,
		forceSend = config.forceSend == true,
	}

	return normalized
end

local function showIupUnavailable()
	if iupUnavailableShown then return end
	iupUnavailableShown = true

	local details = tostring(iupLoadError)
	print("Cannot load FCEUX connection dialog DLL: " .. details)
	if details:find("not a valid Win32 application", 1, true) then
		print("This usually means 64-bit FCEUX is loading the 32-bit FCEUX package.")
	elseif details:find("Must call iup.Open in main thread", 1, true) then
		print("This means FCEUX is running Lua on a thread where IUP cannot open the dialog.")
		print("Edit coop_config.lua next to coop.lua, set enabled = true and enter the session code, then reload coop.lua.")
	else
		print("This usually means the FCEUX package does not match your emulator bitness.")
	end
	print("Use 32-bit FCEUX with the fceux-win32 package, or 64-bit FCEUX with the fceux-win64 package.")
	if connectionConfigError then
		print("Could not load coop_config.lua: " .. tostring(connectionConfigError))
	end
	errorMessage("Dialog DLL unavailable; edit coop_config.lua or use a FCEUX package matching your emulator bitness.")
end

-- Bizarre kludge: For reasons I do not understand at all, radio buttons do not work in FCEUX. Switch to menus there only
local optionLetter = "o"
if FCEU then optionLetter = "l" end

function connectionDialog()
	if not iupOk then
		local normalized = normalizeConnectionConfig(loadConnectionConfig())
		if normalized then
			print("Using connection settings from coop_config.lua")
			return normalized
		end
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
		local config = loadConnectionConfig()
		local mode = config and config.mode
		if mode then
			for i, spec in ipairs(specs) do
				if spec.guid == mode or spec.name == mode then
					print("Using mode from coop_config.lua: " .. spec.name)
					return spec
				end
			end
			errorMessage("Mode from coop_config.lua not available: " .. tostring(mode))
			return nil
		end
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
