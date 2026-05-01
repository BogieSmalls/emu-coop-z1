require "pipe"
require "pipe_direct"
local mock = require("mock_socket")

describe("DirectPipe pair completes hello and reaches ESTABLISHED", function()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)

  local data_a = {host=true, port=12345}
  local data_b = {host=false, host_addr="127.0.0.1", port=12345}

  local a = DirectPipe(data_a)
  local b = DirectPipe(data_b)
  -- Inject sockets directly (bypassing the real listen/connect for the test).
  a.server = sa; b.server = sb
  a:_initFraming(); b:_initFraming()
  a:_sendHello(); b:_sendHello()
  for _ = 1, 5 do a:_pumpFrames(); b:_pumpFrames() end
  assertEq(a.state, "ESTABLISHED")
  assertEq(b.state, "ESTABLISHED")
end)

describe("DirectPipe forwards data tables to driver", function()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)

  local received = nil
  local driver_b = {wake=function() end, handleTable=function(self, t) received = t end}

  local a = DirectPipe({host=true, port=12345})
  local b = DirectPipe({host=false, host_addr="127.0.0.1", port=12345})
  a.server = sa; b.server = sb
  a.driver = {wake=function() end, handleTable=function() end}
  b.driver = driver_b
  a:_initFraming(); b:_initFraming()
  a:_sendHello(); b:_sendHello()
  for _ = 1, 5 do a:_pumpFrames(); b:_pumpFrames() end
  a:sendTable({addr=0x6F, value=42})
  for _ = 1, 5 do b:_pumpFrames() end
  assertEq(received.addr, 0x6F)
  assertEq(received.value, 42)
end)
