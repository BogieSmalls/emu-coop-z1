require "pipe"
local mock = require("mock_socket")

-- Minimal harness: instantiate two Pipes connected via paired mocks.
-- We test the hello state machine without any subclass-specific transport.

local function makePair()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  -- Pipe assumes self.server is the socket; we'll set it manually.
  local pipeA = Pipe()
  pipeA.server = a
  pipeA.driver = {wake=function() end, tick=function() end, handleTable=function() end}
  local pipeB = Pipe()
  pipeB.server = b
  pipeB.driver = {wake=function() end, tick=function() end, handleTable=function() end}
  pipeA:_initFraming()
  pipeB:_initFraming()
  return pipeA, pipeB
end

describe("hello exchange transitions both peers to ESTABLISHED", function()
  local a, b = makePair()
  a:_sendHello()
  b:_sendHello()
  for _ = 1, 5 do a:_pumpFrames(); b:_pumpFrames() end
  assertEq(a.state, "ESTABLISHED")
  assertEq(b.state, "ESTABLISHED")
end)

describe("version mismatch causes abort", function()
  local a, b = makePair()
  a:_sendHelloRaw({kind="hello", v=999})  -- bogus version
  b:_sendHello()
  for _ = 1, 5 do a:_pumpFrames(); b:_pumpFrames() end
  assertEq(b.state, "FAILED")
end)
