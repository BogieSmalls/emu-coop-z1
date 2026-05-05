require "pipe"
require "pipe_relay"
local mock = require("mock_socket")

describe("RelayPipe sends join frame on connect and waits for joined", function()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)
  local pipe = RelayPipe({host_addr="127.0.0.1", port=9999, code="abcdef"})
  pipe.driver = {wake=function() end, handleTable=function() end, tick=function() end}
  pipe.server = sa
  pipe:_initFraming()
  pipe:_sendJoin()
  -- Read join frame from sb
  local reader = Frame.newReader(sb)
  local frame = nil
  for _ = 1, 5 do frame = reader:tick(); if frame then break end end
  assertEq(frame.kind, "join")
  assertEq(frame.code, "abcdef")
  assertTrue(type(frame.peer_id) == "string" and #frame.peer_id > 0, "peer_id present")
end)

describe("RelayPipe handles joined frame and proceeds to send hello", function()
  local sa, sb = mock.makePair()
  sa:settimeout(0); sb:settimeout(0)
  local pipe = RelayPipe({host_addr="127.0.0.1", port=9999, code="abcdef"})
  pipe.driver = {wake=function() end, handleTable=function() end, tick=function() end}
  pipe.server = sa
  pipe:_initFraming()
  pipe:_sendJoin()
  -- Drain join frame from sb
  Frame.newReader(sb):tick()  -- consume join
  -- Send "joined" back from relay (sb)
  Frame.writeFrame(sb, '{"kind":"joined"}')
  for _ = 1, 5 do pipe:_pumpFrames() end
  -- Pipe should now have sent hello; verify by reading from sb
  local reader = Frame.newReader(sb)
  local got = nil
  for _ = 1, 5 do got = reader:tick(); if got then break end end
  assertEq(got.kind, "hello")
end)
