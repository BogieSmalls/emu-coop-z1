-- Make vendored libraries (json.lua) findable on FCEUX's Lua
package.path = package.path .. ";.\\vendor\\?.lua;./vendor/?.lua"

class   = require "pl.class"
pretty  = require "pl.pretty"
List    = require "pl.List"
stringx = require "pl.stringx"
tablex  = require "pl.tablex"

require "version"
require "util"

require "modes.index"
require "dialog"
require "pipe"
require "driver"

-- PROGRAM

if emu.emulating() then
	local spec = nil -- Mode specification
	
	local usableModes = {} -- Mode files that can be loaded in this version of coop.lua
	for i,v in ipairs(modes) do
		if versionMatches(version.modeFormat, v.format) then
			table.insert(usableModes, v)
		else
			print("Could not load a game mode because it is not compatible with this version of the emulator. The game's name was: " .. tostring(v.name))
		end
	end

	local specOptions = {} -- Mode files that match the currently running ROM
	for i,v in ipairs(usableModes) do
		if performTest(v.match) then
			table.insert(specOptions, v)
		end
	end

	if #specOptions == 1 then -- The current game's mode file has been found
		spec = specOptions[1]
	elseif #specOptions > 1 then -- More than one mode file was found that could be this game
		spec = selectDialog(specOptions, "multiple matches")
	else                         -- No matches
		spec = selectDialog(usableModes, "no matches")
	end

	if spec then -- If user did not hit cancel
		print("Playing " .. spec.name)

		local data = ircDialog()

		if data then -- If user did not hit cancel
			local failed = false

			function scrub(invalid) errorMessage(invalid .. " not valid") failed = true end

			-- Strip out stray whitespace
			for _, v in ipairs({"server", "host_addr", "code", "nick", "partner"}) do
				if data[v] then data[v] = data[v]:gsub("%s+", "") end
			end

			-- Validate based on transport
			if data.kind == "direct" then
				if not nonempty(data.host_addr) then scrub("Host address")
				elseif not nonzero(data.port) then scrub("Port")
				end
			elseif data.kind == "relay" then
				if not nonempty(data.host_addr) then scrub("Relay address")
				elseif not nonzero(data.port) then scrub("Port")
				elseif not nonempty(data.code) or #data.code < 6 then scrub("Session code (must be 6+ chars)")
				end
			elseif data.server then
				-- Legacy IRC validation (kept until Phase 8 cleanup)
				if not nonempty(data.server) then scrub("Server")
				elseif not nonzero(data.port) then scrub("Port")
				elseif not nonempty(data.nick) then scrub("Nick")
				elseif not nonempty(data.partner) then scrub("Partner nick")
				end
			end

			function connect()
				mainDriver = GameDriver(spec, data.forceSend) -- Notice: This is a global, specs can use it

				if data.kind == "direct" then
					require "pipe_direct"
					DirectPipe({
						host = data.isHost,
						host_addr = data.host_addr,
						port = data.port,
					}, mainDriver):wake()
				elseif data.kind == "relay" then
					require "pipe_relay"
					RelayPipe({
						host_addr = data.host_addr,
						port = data.port,
						code = data.code,
					}, mainDriver):wake()
				elseif data.server then
					-- Legacy IRC fallback (kept until Phase 8 cleanup)
					local socket = require "socket"
					local server = socket.tcp()
					local result, err = server:connect(data.server, data.port)
					if not result then errorMessage("Could not connect to IRC: " .. err) failed = true return end
					statusMessage("Connecting to server...")
					IrcPipe(data, mainDriver):wake(server)
				else
					errorMessage("Unknown transport in dialog result")
					failed = true
				end
			end

			if not failed then connect() end

			if failed then gui.register(printMessage) end
		end
	end
else
	refuseDialog()
end
