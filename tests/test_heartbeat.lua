require "pipe"
local mock = require("mock_socket")

local function makeFakeClock()
  local t = 0
  return function() return t end, function(d) t = t + d end
end

local function makePipePair()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)
  local now, advance = makeFakeClock()
  local a = Pipe(); a.server = sa; a:_initFraming(); a:_initHeartbeat(now)
  local b = Pipe(); b.server = sb; b:_initFraming(); b:_initHeartbeat(now)
  a.driver = {wake=function() end, handleTable=function() end, tick=function() end}
  b.driver = a.driver
  a:_sendHello(); b:_sendHello()
  for _ = 1, 5 do a:_pumpFrames(); b:_pumpFrames() end
  return a, b, advance
end

describe("heartbeat: ping is sent after interval", function()
  local a, b, advance = makePipePair()
  advance(5.1)
  a:_heartbeatTick()
  for _ = 1, 3 do b:_pumpFrames() end
  assertEq(b._lastFrameKind, "ping")
end)

describe("heartbeat: silence > timeout transitions to FAILED", function()
  local a, b, advance = makePipePair()
  advance(15.1)
  a:_heartbeatTick()
  assertEq(a.state, "FAILED")
end)

describe("heartbeat: any received byte resets liveness timer", function()
  local a, b, advance = makePipePair()
  advance(10)
  b:sendTable({addr=1, value=2})
  for _ = 1, 3 do a:_pumpFrames() end
  advance(10)  -- 10s after partner's send; total elapsed is 20 but 10s ago we got a byte
  a:_heartbeatTick()
  assertTrue(a.state ~= "FAILED", "expected still alive")
end)
