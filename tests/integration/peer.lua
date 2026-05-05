-- tests/integration/peer.lua
-- Lua harness for loopback integration tests.
-- Usage: luajit tests/integration/peer.lua <role> <host> <port> <code>
--   role = "sender" or "recv"
package.path = package.path .. ";./?.lua;./vendor/?.lua;./tests/?.lua"

-- Stub FCEUX globals so pipe.lua + pipe_relay.lua can load outside the emulator
class   = require("pl.class")
pretty  = require("pl.pretty")
stringx = require("pl.stringx")
List    = require("pl.List")
tablex  = require("pl.tablex")
errorMessage  = function(s) io.stderr:write("ERR: " .. tostring(s) .. "\n") end
statusMessage = function(s) io.stderr:write("STATUS: " .. tostring(s) .. "\n") end
message       = function(s) io.stderr:write("MSG: " .. tostring(s) .. "\n") end
version = { protocolVersion = 1 }
emu = { registerexit = function() end }
gui = { register = function() end, text = function() end }

require "pipe"
require "pipe_relay"

local socket = require("socket")
local role, host, port, code = arg[1], arg[2], tonumber(arg[3]), arg[4]
assert(role == "sender" or role == "recv", "role must be 'sender' or 'recv'")

local recvCount = 0
local pipe = RelayPipe({host_addr=host, port=port, code=code})
pipe.driver = {
  wake = function() io.stderr:write("WAKE\n") end,
  childExit = function() end,
  tick = function() end,
  resync = function() end,
  handleTable = function(self, t)
    recvCount = recvCount + 1
    print("RECV " .. tostring(t.addr) .. " " .. tostring(t.value))
    io.stdout:flush()
  end,
}

-- Manual connection sequence (no FCEUX gui callback, drive ticks ourselves)
local client = socket.tcp()
client:settimeout(5)
local ok, err = client:connect(host, port)
if not ok then io.stderr:write("CONNECT FAIL: " .. tostring(err) .. "\n") os.exit(1) end
client:settimeout(0)
pipe.server = client
pipe:_initFraming()
pipe:_initHeartbeat()
pipe:_initReconnect()
pipe:_sendJoin()

local sent = false
local startTime = os.time()

while true do
  pipe:_pumpFrames()
  pipe:_heartbeatTick()

  if pipe.state == "FAILED" or pipe.state == "CLOSED" then
    io.stderr:write("STATE " .. pipe.state .. "\n")
    os.exit(1)
  end

  if pipe.state == "ESTABLISHED" then
    if role == "sender" and not sent then
      -- Send 3 frames
      pipe:sendTable({addr=10, value=1})
      pipe:sendTable({addr=20, value=2})
      pipe:sendTable({addr=30, value=3})
      sent = true
      io.stderr:write("SENT_ALL\n")
    end
    if role == "sender" and sent then
      -- Give a tick for the data to flush, then exit
      socket.sleep(0.5)
      pipe:exit()
      print("DONE")
      io.stdout:flush()
      os.exit(0)
    end
    if role == "recv" and recvCount >= 3 then
      print("DONE")
      io.stdout:flush()
      pipe:exit()
      os.exit(0)
    end
  end

  -- Timeout safety
  if os.time() - startTime > 10 then
    io.stderr:write("TIMEOUT (state=" .. tostring(pipe.state) .. ", recvCount=" .. recvCount .. ")\n")
    os.exit(2)
  end

  socket.sleep(0.05)
end
