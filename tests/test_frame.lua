require "pipe"  -- exposes Frame module
local mock = require("mock_socket")

describe("encode_uint32_be roundtrip", function()
  for _, n in ipairs({0, 1, 255, 256, 65535, 65536, 0xFFFFFFFF}) do
    local s = Frame.encode_uint32_be(n)
    assertEq(#s, 4)
    assertEq(Frame.decode_uint32_be(s), n)
  end
end)

describe("writeFrame writes length+payload", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  Frame.writeFrame(a, '{"kind":"hello","v":1}')
  -- Read 4-byte header from b
  local header = b:receive(4)
  assertEq(#header, 4)
  assertEq(Frame.decode_uint32_be(header), 22)
  local body = b:receive(22)
  assertEq(body, '{"kind":"hello","v":1}')
end)

describe("readFrame returns parsed table", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  Frame.writeFrame(a, '{"kind":"ping"}')
  local reader = Frame.newReader(b)
  local frame = nil
  for _ = 1, 10 do
    frame = reader:tick()
    if frame then break end
  end
  assertTrue(frame ~= nil, "expected a frame")
  assertEq(frame.kind, "ping")
end)

describe("readFrame handles partial reads", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  -- send the frame in two halves (chop in middle of body)
  local payload = '{"kind":"hello","v":1}'
  local full = Frame.encode_uint32_be(#payload) .. payload
  a:send(full:sub(1, 10))
  local reader = Frame.newReader(b)
  assertEq(reader:tick(), nil)  -- partial; not yet
  a:send(full:sub(11))
  local frame = nil
  for _ = 1, 10 do
    frame = reader:tick()
    if frame then break end
  end
  assertTrue(frame ~= nil)
  assertEq(frame.kind, "hello")
  assertEq(frame.v, 1)
end)

describe("readFrame rejects oversized frames", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  -- Length prefix says 5000 (above 4 KiB cap)
  a:send(Frame.encode_uint32_be(5000))
  local reader = Frame.newReader(b)
  local ok, err = pcall(function() reader:tick() end)
  assertTrue(not ok, "expected error on oversized frame")
  assertContains(tostring(err), "frame too large")
end)

describe("readFrame errors on malformed JSON", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  local payload = "not valid json"
  a:send(Frame.encode_uint32_be(#payload) .. payload)
  local reader = Frame.newReader(b)
  local ok, err = pcall(function()
    for _ = 1, 5 do reader:tick() end
  end)
  assertTrue(not ok, "expected error on malformed JSON")
  assertContains(tostring(err), "JSON")
end)
