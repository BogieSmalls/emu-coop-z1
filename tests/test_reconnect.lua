require "pipe"
require "pipe_direct"
local mock = require("mock_socket")

describe("Pipe transitions FAILED -> RECONNECTING when reconnect enabled", function()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)
  local pipe = Pipe()
  pipe.server = sa
  pipe._reconnectEnabled = true
  -- Stub _reconnect_transport to count calls
  local reconnectCalls = 0
  pipe._reconnect_transport = function(self) reconnectCalls = reconnectCalls + 1 end
  pipe:_initFraming()
  pipe:_initHeartbeat(function() return 0 end)
  pipe:_initReconnect()
  pipe:_fail("test failure")
  assertEq(pipe.state, "RECONNECTING")
end)

describe("backoff sequence is 1, 2, 4, 8, 16, 30, 30...", function()
  local pipe = Pipe()
  pipe:_initReconnect()
  local expected = {1, 2, 4, 8, 16, 30, 30, 30}
  for i, want in ipairs(expected) do
    assertEq(pipe:_nextBackoff(), want, "attempt " .. i)
  end
end)

describe("reconnect attempt fires after backoff elapses", function()
  local now = 0
  local pipe = Pipe()
  pipe._clock = function() return now end
  pipe._reconnectEnabled = true
  local attempts = 0
  pipe._reconnect_transport = function() attempts = attempts + 1; return false end
  pipe:_initReconnect()
  pipe.state = "RECONNECTING"
  pipe._nextRetryAt = 1
  now = 0.5; pipe:_reconnectTick(); assertEq(attempts, 0)
  now = 1.0; pipe:_reconnectTick(); assertEq(attempts, 1)
end)
