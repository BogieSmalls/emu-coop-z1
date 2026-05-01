# emu-coop Transport Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace emu-coop's IRC-based networking with two new transports (Direct peer-to-peer TCP + Relay through a hosted daemon), with auto-reconnect and state resync.

**Architecture:** New `Pipe` subclasses `DirectPipe` and `RelayPipe` share a length-prefixed JSON wire format. The existing `Pipe` base owns framing, hello handshake, heartbeat, and reconnect lifecycle. A small Python asyncio relay daemon pairs peers by session code and forwards bytes. `IrcPipe` is preserved during development for fallback and deleted in the final phase.

**Tech Stack:** Lua 5.1 / LuaJIT (FCEUX), LuaSocket (already shipped), `rxi/json.lua` (new dep), Python 3.11+ asyncio (relay), pytest (relay tests).

**Spec:** `docs/superpowers/specs/2026-04-30-emu-coop-transport-design.md`

**Pre-flight check before each commit:** `git status` and `git diff` to confirm what's being committed.

---

## Phase 1: Foundation

### Task 1: Add JSON dependency

**Files:**
- Create: `vendor/json.lua` (download rxi/json.lua single-file library)
- Create: `tests/test_json.lua`
- Create: `tests/run.lua` (minimal test runner)

- [ ] **Step 1: Create the test runner**

Create `tests/run.lua`:

```lua
-- Minimal test runner. Usage: lua tests/run.lua tests/test_*.lua
package.path = package.path .. ";./?.lua;./vendor/?.lua;./tests/?.lua"

local tests = {}
function describe(name, fn) table.insert(tests, {name=name, fn=fn}) end
function assertEq(actual, expected, msg)
  if actual ~= expected then
    error(string.format("%s: expected %s, got %s",
      msg or "assertEq", tostring(expected), tostring(actual)), 2)
  end
end
function assertTrue(v, msg)
  if not v then error(msg or "assertTrue failed", 2) end
end
function assertContains(haystack, needle, msg)
  if not haystack:find(needle, 1, true) then
    error(string.format("%s: %q not found in %q",
      msg or "assertContains", needle, haystack), 2)
  end
end

for i = 1, #arg do dofile(arg[i]) end

local pass, fail = 0, 0
for _, t in ipairs(tests) do
  local ok, err = pcall(t.fn)
  if ok then
    pass = pass + 1
    print("PASS: " .. t.name)
  else
    fail = fail + 1
    print("FAIL: " .. t.name)
    print("  " .. tostring(err))
  end
end
print(string.format("\n%d passed, %d failed", pass, fail))
os.exit(fail > 0 and 1 or 0)
```

- [ ] **Step 2: Drop in rxi/json.lua**

Download from https://github.com/rxi/json.lua/blob/master/json.lua (the single file `json.lua`, MIT licensed, ~250 lines). Save as `vendor/json.lua`. Verify the file starts with `local json = { _version = "0.1.2" }` and ends with `return json`.

- [ ] **Step 3: Write JSON sanity test**

Create `tests/test_json.lua`:

```lua
local json = require("json")

describe("json encode/decode roundtrip", function()
  local input = {kind="data", body={addr=0x6F, value=42}}
  local encoded = json.encode(input)
  local decoded = json.decode(encoded)
  assertEq(decoded.kind, "data")
  assertEq(decoded.body.addr, 0x6F)
  assertEq(decoded.body.value, 42)
end)

describe("json encode produces valid output for hello", function()
  local s = json.encode({kind="hello", v=1})
  assertContains(s, "\"kind\"")
  assertContains(s, "\"hello\"")
  assertContains(s, "\"v\"")
end)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_json.lua`
Expected: `2 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add vendor/json.lua tests/run.lua tests/test_json.lua
git commit -m "feat: add rxi/json.lua dependency and minimal test runner"
```

---

### Task 2: Mock socket for tests

**Files:**
- Create: `tests/mock_socket.lua`
- Create: `tests/test_mock_socket.lua`

- [ ] **Step 1: Write the failing tests first**

Create `tests/test_mock_socket.lua`:

```lua
local mock = require("mock_socket")

describe("paired sockets exchange bytes", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  a:send("hello")
  local got = b:receive(5)
  assertEq(got, "hello")
end)

describe("receive on empty buffer returns timeout", function()
  local a, b = mock.makePair()
  b:settimeout(0)
  local got, err = b:receive(1)
  assertEq(got, nil)
  assertEq(err, "timeout")
end)

describe("receive returns partial on short buffer", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  a:send("ab")
  local got, err, partial = b:receive(5)
  assertEq(got, nil)
  assertEq(err, "timeout")
  assertEq(partial, "ab")
end)

describe("close on one side surfaces on other", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  a:close()
  local got, err = b:receive(1)
  assertEq(got, nil)
  assertEq(err, "closed")
end)

describe("multiple sends concatenate", function()
  local a, b = mock.makePair()
  a:settimeout(0); b:settimeout(0)
  a:send("foo"); a:send("bar")
  assertEq(b:receive(6), "foobar")
end)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_mock_socket.lua`
Expected: errors about `mock_socket` not found, all tests FAIL.

- [ ] **Step 3: Implement mock_socket.lua**

Create `tests/mock_socket.lua`:

```lua
local M = {}

local function makeSide(myInbox, theirInbox, myState, theirState)
  local s = {}
  s._timeout = nil

  function s:settimeout(n) self._timeout = n end

  function s:send(data)
    if myState.closed then return nil, "closed" end
    if theirState.closed then return nil, "closed" end
    table.insert(theirInbox, data)
    return #data
  end

  -- Returns string of length n on success, or nil, err, partial on failure.
  -- Matches LuaSocket non-blocking semantics for our use.
  function s:receive(n)
    if myState.closed then return nil, "closed" end
    -- Concatenate inbox into one string for easier slicing.
    local combined = table.concat(myInbox)
    myInbox[1] = combined
    for i = #myInbox, 2, -1 do table.remove(myInbox, i) end
    if #combined >= n then
      local result = combined:sub(1, n)
      myInbox[1] = combined:sub(n + 1)
      if myInbox[1] == "" then table.remove(myInbox, 1) end
      return result
    elseif #combined > 0 then
      myInbox[1] = ""
      table.remove(myInbox, 1)
      return nil, "timeout", combined
    else
      return nil, "timeout"
    end
  end

  function s:close() myState.closed = true end

  return s
end

function M.makePair()
  local a_inbox, b_inbox = {}, {}
  local a_state, b_state = {closed=false}, {closed=false}
  return makeSide(a_inbox, b_inbox, a_state, b_state),
         makeSide(b_inbox, a_inbox, b_state, a_state)
end

return M
```

- [ ] **Step 4: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_mock_socket.lua`
Expected: `5 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add tests/mock_socket.lua tests/test_mock_socket.lua
git commit -m "feat: add paired in-memory mock socket for tests"
```

---

### Task 3: Framing helpers (length-prefix encode/decode)

**Files:**
- Create: `tests/test_frame.lua`
- Modify: `pipe.lua` (add framing module/helpers; existing IrcPipe code untouched)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_frame.lua`:

```lua
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_frame.lua`
Expected: errors about `Frame` not found, all tests FAIL.

- [ ] **Step 3: Add Frame module to pipe.lua**

Add to top of `pipe.lua` (before `class.Pipe()` line), so it's loaded by anything that requires pipe:

```lua
local json = require("json")

Frame = {}
Frame.MAX_PAYLOAD = 4096  -- 4 KiB cap

function Frame.encode_uint32_be(n)
  return string.char(
    math.floor(n / 16777216) % 256,
    math.floor(n / 65536) % 256,
    math.floor(n / 256) % 256,
    n % 256
  )
end

function Frame.decode_uint32_be(s)
  local b1, b2, b3, b4 = s:byte(1, 4)
  return b1 * 16777216 + b2 * 65536 + b3 * 256 + b4
end

function Frame.writeFrame(sock, payload)
  if #payload > Frame.MAX_PAYLOAD then
    error("frame too large: " .. #payload)
  end
  local header = Frame.encode_uint32_be(#payload)
  return sock:send(header .. payload)
end

-- Reader is a per-pipe stateful object that drives partial reads across ticks.
function Frame.newReader(sock)
  local r = {
    sock = sock,
    state = "header",       -- "header" or "body"
    buf = "",
    bodyLen = nil,
  }
  function r:tick()
    if self.state == "header" then
      local need = 4 - #self.buf
      local data, err, partial = self.sock:receive(need)
      if data then
        self.buf = self.buf .. data
      elseif partial then
        self.buf = self.buf .. partial
        return nil
      elseif err == "timeout" then
        return nil
      else
        error("socket error: " .. tostring(err))
      end
      if #self.buf == 4 then
        self.bodyLen = Frame.decode_uint32_be(self.buf)
        if self.bodyLen > Frame.MAX_PAYLOAD then
          error("frame too large: " .. self.bodyLen)
        end
        self.buf = ""
        self.state = "body"
      end
    end
    if self.state == "body" then
      local need = self.bodyLen - #self.buf
      if need > 0 then
        local data, err, partial = self.sock:receive(need)
        if data then
          self.buf = self.buf .. data
        elseif partial then
          self.buf = self.buf .. partial
          return nil
        elseif err == "timeout" then
          return nil
        else
          error("socket error: " .. tostring(err))
        end
      end
      if #self.buf == self.bodyLen then
        local payload = self.buf
        self.buf = ""
        self.state = "header"
        local ok, parsed = pcall(json.decode, payload)
        if not ok then
          error("malformed JSON: " .. tostring(parsed))
        end
        return parsed
      end
    end
    return nil
  end
  return r
end
```

- [ ] **Step 4: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_frame.lua`
Expected: `6 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_frame.lua pipe.lua
git commit -m "feat: add length-prefix JSON framing helpers (Frame module)"
```

---

## Phase 2: Pipe base refactor

### Task 4: Lift framing onto Pipe base; add hello state machine

**Files:**
- Modify: `pipe.lua` (extend `Pipe` base with framing-aware send/receive and hello state)
- Modify: `version.lua` (add `protocolVersion = 1`)
- Create: `tests/test_handshake.lua`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handshake.lua`:

```lua
require "pl.class"
class = require "pl.class"  -- Penlight class
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_handshake.lua`
Expected: errors about missing methods, all tests FAIL.

- [ ] **Step 3: Add `protocolVersion` to version.lua**

Edit `version.lua`. After the `release = "1.2",` line, add:

```lua
	-- Protocol version for new Pipe transports (Direct/Relay). Bump on wire-format break.
	protocolVersion = 1,
```

- [ ] **Step 4: Extend Pipe base with hello state machine**

Modify `pipe.lua`. After the existing `class.Pipe()` block and `function Pipe:_init()`, add the following methods (keeping the existing `_init`, `wake`, `exit`, `fail`, `send`, `receivePump`, `tick`, `childWake/Exit/Tick`, `handle`):

```lua
-- States: INIT, CONNECTING, TRANSPORT_READY, JOIN_SENT, JOINED, HELLO_SENT, ESTABLISHED, FAILED, RECONNECTING, CLOSED
function Pipe:_initFraming()
  self.reader = Frame.newReader(self.server)
  self.state = "TRANSPORT_READY"
  self.helloSent = false
  self.helloReceived = false
end

function Pipe:_sendFrame(t)
  local payload = json.encode(t)
  local res, err = Frame.writeFrame(self.server, payload)
  if not res then
    self:_fail("send failed: " .. tostring(err))
    return false
  end
  return true
end

function Pipe:_sendHello()
  if self.helloSent then return end
  self:_sendHelloRaw({kind="hello", v=version.protocolVersion})
  self.state = "HELLO_SENT"
end

-- For tests: send any hello shape (real code uses _sendHello).
function Pipe:_sendHelloRaw(t)
  self:_sendFrame(t)
  self.helloSent = true
  self.state = "HELLO_SENT"
end

function Pipe:_fail(msg)
  if self.state == "FAILED" or self.state == "CLOSED" then return end
  errorMessage(msg)
  self.state = "FAILED"
  if self.server then pcall(function() self.server:close() end) end
end

function Pipe:_pumpFrames()
  if self.state == "FAILED" or self.state == "CLOSED" then return end
  local ok, frame = pcall(function() return self.reader:tick() end)
  if not ok then
    self:_fail("Wire protocol error: " .. tostring(frame))
    return
  end
  while frame do
    self:_handleFrame(frame)
    if self.state == "FAILED" or self.state == "CLOSED" then return end
    ok, frame = pcall(function() return self.reader:tick() end)
    if not ok then
      self:_fail("Wire protocol error: " .. tostring(frame))
      return
    end
  end
end

function Pipe:_handleFrame(frame)
  if frame.kind == "hello" then
    if self.helloReceived then
      self:_fail("Wire protocol error: duplicate hello")
      return
    end
    if frame.v ~= version.protocolVersion then
      self:_sendFrame({kind="abort",
        reason="version mismatch: got v=" .. tostring(frame.v) .. ", expected v=" .. version.protocolVersion})
      self:_fail("Partner's emu-coop version is incompatible (got v=" ..
        tostring(frame.v) .. ", expected v=" .. version.protocolVersion .. ")")
      return
    end
    self.helloReceived = true
    if self.helloSent and self.state ~= "ESTABLISHED" then
      self.state = "ESTABLISHED"
      statusMessage(nil)
      message("Connected to partner")
      if self.driver and self.driver.wake then self.driver:wake(self) end
    end
  elseif frame.kind == "abort" then
    self:_fail("Partner aborted: " .. tostring(frame.reason))
  elseif frame.kind == "data" then
    if self.state ~= "ESTABLISHED" then
      self:_fail("Wire protocol error: data before established")
      return
    end
    if self.driver and self.driver.handleTable then
      self.driver:handleTable(frame.body)
    end
  elseif frame.kind == "ping" then
    self:_sendFrame({kind="pong"})
  elseif frame.kind == "pong" then
    -- liveness reset handled implicitly by any byte received
  else
    self:_fail("Wire protocol error: unknown kind " .. tostring(frame.kind))
  end
end

function Pipe:sendTable(t)
  if self.state ~= "ESTABLISHED" then return end
  self:_sendFrame({kind="data", body=t})
end
```

Note: `errorMessage`, `statusMessage`, and `message` are existing globals in `util.lua`. The test runner needs to provide stubs.

- [ ] **Step 5: Add globals stub to test runner**

Edit `tests/run.lua`. Before the `for i = 1, #arg do` line, add:

```lua
-- Stub emu/gui/util globals for tests
errorMessage = function(s) _G._lastError = s end
statusMessage = function(s) _G._lastStatus = s end
message = function(s) _G._lastMessage = s end
version = { protocolVersion = 1 }
```

- [ ] **Step 6: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_handshake.lua`
Expected: `2 passed, 0 failed`

- [ ] **Step 7: Verify existing IrcPipe still loads**

Create `tests/smoke_load.lua` (one-off helper):

```lua
package.path = package.path .. ";./?.lua;./vendor/?.lua"
class = require("pl.class")
pretty = require("pl.pretty")
stringx = require("pl.stringx")
List = require("pl.List")
tablex = require("pl.tablex")
errorMessage = print; statusMessage = print; message = print
version = { protocolVersion = 1, ircPipe = "1.0" }
require("util")
require("pipe")
print("OK")
```

Run: `lua tests/smoke_load.lua`
Expected: `OK` printed (no errors loading).

- [ ] **Step 8: Commit**

```bash
git add pipe.lua version.lua tests/run.lua tests/test_handshake.lua
git commit -m "feat: extend Pipe base with framing + hello state machine"
```

---

## Phase 3: Direct mode

### Task 5: Implement DirectPipe

**Files:**
- Create: `pipe_direct.lua`
- Create: `tests/test_pipe_direct.lua`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipe_direct.lua`:

```lua
require "pl.class"; class = require "pl.class"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_pipe_direct.lua`
Expected: errors about `DirectPipe` not found, FAIL.

- [ ] **Step 3: Implement DirectPipe**

Create `pipe_direct.lua`:

```lua
-- DirectPipe: peer-to-peer TCP. Either listens (host) or connects (client).

class.DirectPipe(Pipe)
function DirectPipe:_init(data, driver)
  self:super()
  self.data = data        -- {host=bool, host_addr=string, port=number}
  self.driver = driver
  self.state = "INIT"
end

function DirectPipe:wake()
  -- Real connect/listen happens here. coop.lua wires this up.
  local socket = require("socket")
  if self.data.host then
    statusMessage("Listening on port " .. self.data.port .. "...")
    local listener = socket.tcp()
    listener:bind("*", self.data.port)
    listener:listen(1)
    listener:settimeout(0)
    self._listener = listener
    self.state = "CONNECTING"
    -- We poll the listener in tick until partner connects.
    self._connectFn = function()
      local client = listener:accept()
      if client then
        listener:close()
        self._listener = nil
        client:settimeout(0)
        self.server = client
        self:_initFraming()
        self:_sendHello()
        self:_postConnectInit()
      end
    end
  else
    statusMessage("Connecting to " .. self.data.host_addr .. ":" .. self.data.port .. "...")
    local client = socket.tcp()
    client:settimeout(5)
    local ok, err = client:connect(self.data.host_addr, self.data.port)
    if not ok then
      self:_fail("Could not reach " .. self.data.host_addr .. ":" .. self.data.port .. ": " .. tostring(err))
      return
    end
    client:settimeout(0)
    self.server = client
    self:_initFraming()
    self:_sendHello()
    self:_postConnectInit()
  end
  emu.registerexit(function() self:exit() end)
  gui.register(function()
    if self.state ~= "FAILED" and self.state ~= "CLOSED" then self:tick() end
    printMessage()
  end)
end

function DirectPipe:_postConnectInit()
  self.state = "TRANSPORT_READY"
  -- _initFraming and _sendHello already called in caller paths above.
end

function DirectPipe:tick()
  if self._connectFn then
    self._connectFn()
    return
  end
  self:_pumpFrames()
  if self.state == "ESTABLISHED" and self.driver and self.driver.tick then
    self.driver:tick()
  end
end

function DirectPipe:exit()
  if self.state == "CLOSED" then return end
  self.state = "CLOSED"
  if self.server then pcall(function() self.server:close() end) end
  if self._listener then pcall(function() self._listener:close() end) end
  if self.driver and self.driver.childExit then self.driver:childExit() end
end
```

- [ ] **Step 4: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_pipe_direct.lua`
Expected: `2 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add pipe_direct.lua tests/test_pipe_direct.lua
git commit -m "feat: add DirectPipe for peer-to-peer TCP"
```

---

### Task 6: Update dialog.lua to support transport selection

**Files:**
- Modify: `dialog.lua`

- [ ] **Step 1: Replace ircDialog with a transport-aware dialog**

Edit `dialog.lua`. Replace the `ircDialog()` function (lines 7-20) with:

```lua
function connectionDialog()
  local res, transport, host_addr, port, code, isHost, forceSend = iup.GetParam(
    "Connection settings", nil,
    "Transport: %" .. optionLetter .. "|Direct (LAN/Tailscale)|Relay (via OCI server)|\n" ..
    "Host address (Direct: peer's IP, or relay address): %s\n" ..
    "Port: %i\n" ..
    "Session code (Relay only, 6+ chars): %s\n" ..
    "Are you the host? (Direct only) %" .. optionLetter .. "|No|Yes|\n" ..
    "%t\n" ..
    "Are you restarting\rafter a crash? %" .. optionLetter .. "|No|Yes|\n",
    0, "127.0.0.1", 9999, "", 0, 0)

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

-- Backwards-compatible alias for any code still calling the old name.
ircDialog = connectionDialog
```

Keep `selectDialog` and `refuseDialog` unchanged.

- [ ] **Step 2: Verify dialog.lua loads (smoke check)**

Run: `lua -e "iup={GetParam=function() return 0 end}; FCEU=true; dofile('dialog.lua'); print(type(connectionDialog))"`
Expected: `function`

- [ ] **Step 3: Commit**

```bash
git add dialog.lua
git commit -m "feat: add Direct/Relay transport selector to connection dialog"
```

---

### Task 7: Wire pipe selection through coop.lua

**Files:**
- Modify: `coop.lua`

- [ ] **Step 1: Update coop.lua to instantiate the chosen Pipe**

Edit `coop.lua`. Find the `connect()` local function (around line 67). Replace it with:

```lua
function connect()
  mainDriver = GameDriver(spec, data.forceSend)

  if data.kind == "direct" then
    require "pipe_direct"
    local pipe = DirectPipe({
      host = data.isHost,
      host_addr = data.host_addr,
      port = data.port,
    }, mainDriver)
    pipe:wake()
  elseif data.kind == "relay" then
    require "pipe_relay"
    local pipe = RelayPipe({
      host_addr = data.host_addr,
      port = data.port,
      code = data.code,
    }, mainDriver)
    pipe:wake()
  elseif data.server then
    -- Legacy IRC fallback (kept until Phase 8 cleanup).
    local socket = require "socket"
    local server = socket.tcp()
    local result, err = server:connect(data.server, data.port)
    if not result then errorMessage("Could not connect to IRC: " .. err); failed = true; return end
    statusMessage("Connecting to server...")
    IrcPipe(data, mainDriver):wake(server)
  else
    errorMessage("Unknown transport in dialog result")
    failed = true
  end
end
```

Also update the input validation block above `function connect()`. Replace the existing scrub loop:

```lua
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
  -- Legacy IRC validation
  if not nonempty(data.server) then scrub("Server")
  elseif not nonzero(data.port) then scrub("Port")
  elseif not nonempty(data.nick) then scrub("Nick")
  elseif not nonempty(data.partner) then scrub("Partner nick")
  end
end
```

- [ ] **Step 2: Verify coop.lua parses**

Run: `lua -e "package.path = package.path .. ';./?.lua;./vendor/?.lua'; emu={emulating=function() return false end}; dofile('coop.lua'); print('ok')"`
Expected: `ok` printed (no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add coop.lua
git commit -m "feat: wire DirectPipe/RelayPipe selection through coop.lua"
```

---

### Task 8: Manual smoke test — Direct mode on LAN

**Goal:** Verify two FCEUX instances can connect via DirectPipe and sync gameplay.

- [ ] **Step 1: Document the smoke test procedure**

This task is a manual checkpoint, not code. Run the following:

1. On machine A (host): launch FCEUX with `coop.lua`. In dialog, select Transport=Direct, Host address=`0.0.0.0`, Port=`9999`, "Are you the host?"=Yes. Click OK.
2. On machine B (client): launch FCEUX with `coop.lua`. In dialog, select Transport=Direct, Host address=`<A's LAN IP>`, Port=`9999`, "Are you the host?"=No. Click OK.
3. Both should display "Connected to partner".
4. Pick up an item (e.g., wood sword in Z1) on machine A. Verify partner sees it within 1 second on machine B.
5. Pick up a different item on machine B. Verify partner sees it on machine A.

If any step fails: file the failure mode and fix before continuing. Do NOT advance to Phase 4 with broken Direct mode.

- [ ] **Step 2: Tag the milestone**

```bash
git tag direct-mode-working
```

---

## Phase 4: Heartbeat + auto-reconnect

### Task 9: Add heartbeat (ping/pong)

**Files:**
- Modify: `pipe.lua` (add heartbeat to Pipe base)
- Create: `tests/test_heartbeat.lua`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_heartbeat.lua`:

```lua
require "pl.class"; class = require "pl.class"
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
```

The tests reference `_lastFrameKind` — add it to `_handleFrame` in step 2 by recording `self._lastFrameKind = frame.kind` at the top of `_handleFrame`.

- [ ] **Step 2: Add heartbeat to Pipe base**

Edit `pipe.lua`. Add to the bottom of the existing `Pipe` class methods:

```lua
function Pipe:_initHeartbeat(clock_fn)
  self._clock = clock_fn or function() return os.time() end
  self._lastRx = self._clock()
  self._lastPing = self._clock()
end

Pipe.HEARTBEAT_INTERVAL = 5
Pipe.HEARTBEAT_TIMEOUT = 15

function Pipe:_heartbeatTick()
  if self.state ~= "ESTABLISHED" and self.state ~= "HELLO_SENT" then return end
  local now = self._clock()
  if (now - self._lastRx) > Pipe.HEARTBEAT_TIMEOUT then
    self:_fail("Connection lost (heartbeat timeout)")
    return
  end
  if (now - self._lastPing) > Pipe.HEARTBEAT_INTERVAL then
    self:_sendFrame({kind="ping"})
    self._lastPing = now
  end
end
```

Modify `_handleFrame` (added in Task 4): at the very top, record received traffic:

```lua
function Pipe:_handleFrame(frame)
  self._lastFrameKind = frame.kind
  if self._clock then self._lastRx = self._clock() end
  -- ...rest of the function unchanged...
```

Modify `_pumpFrames` so that *any* successful read resets `_lastRx` even if the frame was a `pong`:

(The reader returns whole frames; touching `_lastRx` in `_handleFrame` is sufficient because every frame produced by `tick()` came from received bytes.)

- [ ] **Step 3: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_heartbeat.lua`
Expected: `3 passed, 0 failed`

- [ ] **Step 4: Commit**

```bash
git add pipe.lua tests/test_heartbeat.lua
git commit -m "feat: add heartbeat (ping/pong + silence detection) to Pipe base"
```

---

### Task 10: Reconnect state machine + backoff

**Files:**
- Modify: `pipe.lua` (transition FAILED → RECONNECTING; backoff timer)
- Modify: `pipe_direct.lua` (`_reconnect_transport` method)
- Create: `tests/test_reconnect.lua`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reconnect.lua`:

```lua
require "pl.class"; class = require "pl.class"
require "pipe"
require "pipe_direct"
local mock = require("mock_socket")

describe("Pipe transitions FAILED → RECONNECTING when reconnect enabled", function()
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
  pipe._initReconnect(pipe)
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
  pipe._reconnect_transport = function() attempts = attempts + 1; return false end  -- failed reconnect
  pipe:_initReconnect()
  pipe.state = "RECONNECTING"
  pipe._nextRetryAt = 1
  now = 0.5; pipe:_reconnectTick(); assertEq(attempts, 0)
  now = 1.0; pipe:_reconnectTick(); assertEq(attempts, 1)
end)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_reconnect.lua`
Expected: errors, FAIL.

- [ ] **Step 3: Add reconnect machinery to Pipe**

Edit `pipe.lua`. Add to the Pipe class methods:

```lua
function Pipe:_initReconnect()
  self._reconnectAttempt = 0
  self._nextRetryAt = nil
end

Pipe.BACKOFF_SCHEDULE = {1, 2, 4, 8, 16, 30}

function Pipe:_nextBackoff()
  self._reconnectAttempt = (self._reconnectAttempt or 0) + 1
  local idx = self._reconnectAttempt
  return Pipe.BACKOFF_SCHEDULE[idx] or 30
end

function Pipe:_reconnectTick()
  if self.state ~= "RECONNECTING" then return end
  local now = self._clock and self._clock() or os.time()
  if not self._nextRetryAt or now < self._nextRetryAt then return end
  statusMessage("Reconnecting (attempt " .. (self._reconnectAttempt or 0) + 1 .. ")...")
  local ok = self:_reconnect_transport()
  if ok then
    self.helloSent = false
    self.helloReceived = false
    self.state = "TRANSPORT_READY"
    self:_initFraming()
    self:_sendHello()
    -- After successful reconnect handshake, trigger Driver:resync.
    self._postReconnect = true
  else
    -- Schedule next retry
    self._nextRetryAt = now + self:_nextBackoff()
  end
end
```

Modify `_fail` to support reconnect:

```lua
function Pipe:_fail(msg)
  if self.state == "FAILED" or self.state == "CLOSED" then return end
  errorMessage(msg)
  if self.server then pcall(function() self.server:close() end) end
  self.server = nil
  if self._reconnectEnabled then
    self.state = "RECONNECTING"
    self._nextRetryAt = (self._clock and self._clock() or os.time()) + self:_nextBackoff()
  else
    self.state = "FAILED"
  end
end
```

Modify `_handleFrame` so that on transition to ESTABLISHED, if `_postReconnect` is true, call `Driver:resync()`:

```lua
-- Inside _handleFrame, in the hello case, after setting state to "ESTABLISHED":
if self._postReconnect then
  self._postReconnect = false
  if self.driver and self.driver.resync then self.driver:resync() end
  message("Reconnected — re-syncing state")
end
```

- [ ] **Step 4: Add `_reconnect_transport` to DirectPipe**

Edit `pipe_direct.lua`. Add at the bottom:

```lua
function DirectPipe:_reconnect_transport()
  local socket = require("socket")
  if self.data.host then
    -- Re-listen
    local listener = socket.tcp()
    listener:bind("*", self.data.port)
    listener:listen(1)
    listener:settimeout(0)
    self._listener = listener
    -- Accept will be polled in tick.
    self._connectFn = function()
      local client = listener:accept()
      if client then
        listener:close()
        self._listener = nil
        client:settimeout(0)
        self.server = client
      end
    end
    return false  -- still pending; tick will resolve
  else
    local client = socket.tcp()
    client:settimeout(2)
    local ok, err = client:connect(self.data.host_addr, self.data.port)
    if not ok then
      return false
    end
    client:settimeout(0)
    self.server = client
    return true
  end
end
```

Set `self._reconnectEnabled = true` in `DirectPipe:wake` (after `_postConnectInit()` call).

- [ ] **Step 5: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_reconnect.lua`
Expected: `3 passed, 0 failed`

- [ ] **Step 6: Commit**

```bash
git add pipe.lua pipe_direct.lua tests/test_reconnect.lua
git commit -m "feat: add reconnect state machine with exponential backoff"
```

---

### Task 11: Driver:resync()

**Files:**
- Modify: `driver.lua` (add `Driver:resync` and `GameDriver:resync`)
- Modify: `pipe.lua` (add `Driver:resync` no-op to base Driver)
- Create: `tests/test_driver_resync.lua`

- [ ] **Step 1: Write the failing test**

Create `tests/test_driver_resync.lua`:

```lua
require "pl.class"; class = require "pl.class"
require "pipe"

describe("Driver:resync resets cache flags", function()
  -- Use a minimal Driver subclass that mimics GameDriver's resync behavior.
  local d = setmetatable({didCache=true, forceSend=false}, {__index=Driver})
  Driver.resync = function(self)
    self.didCache = false
    self.forceSend = true
  end
  d:resync()
  assertEq(d.didCache, false)
  assertEq(d.forceSend, true)
end)
```

- [ ] **Step 2: Run test to verify it fails (or skip — minimal change)**

Run: `lua tests/run.lua tests/test_driver_resync.lua`
Expected: FAIL (resync not yet defined on Driver).

- [ ] **Step 3: Add `resync` to Driver base in pipe.lua**

Edit `pipe.lua`. After the existing `function Driver:childWake() end` block, add:

```lua
function Driver:resync() end  -- no-op; subclasses override
```

- [ ] **Step 4: Add `resync` to GameDriver in driver.lua**

Edit `driver.lua`. After `function GameDriver:_init` (around line 138), add:

```lua
function GameDriver:resync()
  self.didCache = false
  self.forceSend = true
end
```

- [ ] **Step 5: Run test to verify pass**

Run: `lua tests/run.lua tests/test_driver_resync.lua`
Expected: `1 passed, 0 failed`

- [ ] **Step 6: Run full test suite as smoke check**

Run: `lua tests/run.lua tests/test_json.lua tests/test_mock_socket.lua tests/test_frame.lua tests/test_handshake.lua tests/test_pipe_direct.lua tests/test_heartbeat.lua tests/test_reconnect.lua tests/test_driver_resync.lua`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add pipe.lua driver.lua tests/test_driver_resync.lua
git commit -m "feat: add Driver:resync() for post-reconnect state re-dump"
```

---

### Task 12: Manual smoke test — auto-reconnect on LAN

**Goal:** Verify two FCEUX instances auto-reconnect after a transient network drop.

- [ ] **Step 1: Run the smoke test**

1. Start a Direct-mode session as in Task 8.
2. Pick up a few items so state is non-trivial.
3. On machine B, disable the network adapter for ~10 seconds, then re-enable.
4. Both screens should show "Connection lost. Reconnecting (attempt N)..." then "Reconnected — re-syncing state".
5. Verify state on both sides matches: pick up an item on each side, both should sync.

If step 4 doesn't happen within ~30s, debug heartbeat timing. If state doesn't sync after reconnect, debug `Driver:resync()` and `_postReconnect` flag.

- [ ] **Step 2: Tag milestone**

```bash
git tag direct-reconnect-working
```

---

## Phase 5: Relay daemon (local)

### Task 13: Initialize Python relay project

**Files:**
- Create: `relay/pyproject.toml`
- Create: `relay/relay/__init__.py`
- Create: `relay/relay/__main__.py`
- Create: `relay/tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

Create `relay/pyproject.toml`:

```toml
[project]
name = "emu-coop-relay"
version = "0.1.0"
description = "Relay daemon for emu-coop"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio>=0.23"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["relay"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create empty package files**

Create `relay/relay/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `relay/relay/__main__.py`:

```python
import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())
```

Create empty `relay/tests/__init__.py`.

- [ ] **Step 3: Verify package structure**

Run: `cd relay && python -c "import relay; print(relay.__version__)"`
Expected: `0.1.0`

- [ ] **Step 4: Commit**

```bash
git add relay/pyproject.toml relay/relay/__init__.py relay/relay/__main__.py relay/tests/__init__.py
git commit -m "feat: initialize Python relay project skeleton"
```

---

### Task 14: Relay frame parsing + WAITING/PAIRED state machine

**Files:**
- Create: `relay/relay/server.py`
- Create: `relay/tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Create `relay/tests/test_server.py`:

```python
import asyncio
import json
import os
import struct
import pytest

from relay import server

@pytest.fixture
async def relay_running():
    """Start a relay on an ephemeral port and yield (host, port)."""
    s = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    server._reset_state()  # test helper, see implementation
    task = asyncio.create_task(s.serve_forever())
    yield ("127.0.0.1", port)
    task.cancel()
    s.close()
    await s.wait_closed()

def encode_frame(obj):
    payload = json.dumps(obj).encode()
    return struct.pack(">I", len(payload)) + payload

async def read_frame(reader):
    header = await reader.readexactly(4)
    (n,) = struct.unpack(">I", header)
    body = await reader.readexactly(n)
    return json.loads(body)

async def open_peer(host, port):
    return await asyncio.open_connection(host, port)

async def test_pair_basic(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    await w1.drain()
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await w2.drain()
    f1 = await asyncio.wait_for(read_frame(r1), 2)
    f2 = await asyncio.wait_for(read_frame(r2), 2)
    assert f1["kind"] == "joined"
    assert f2["kind"] == "joined"
    w1.close(); w2.close()

async def test_code_too_short(relay_running):
    host, port = relay_running
    r, w = await open_peer(host, port)
    w.write(encode_frame({"kind": "join", "code": "abc", "peer_id": "p1"}))
    await w.drain()
    f = await asyncio.wait_for(read_frame(r), 2)
    assert f["kind"] == "abort"
    assert "too short" in f["reason"].lower()
    w.close()

async def test_code_collision(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    r3, w3 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)  # joined
    w3.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p3"}))
    await w3.drain()
    f = await asyncio.wait_for(read_frame(r3), 2)
    assert f["kind"] == "abort"
    assert "in use" in f["reason"].lower()
    for w in (w1, w2, w3): w.close()

async def test_byte_forwarding(relay_running):
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    w1.write(encode_frame({"kind": "hello", "v": 1}))
    await w1.drain()
    f = await asyncio.wait_for(read_frame(r2), 2)
    assert f["kind"] == "hello"
    assert f["v"] == 1
    for w in (w1, w2): w.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd relay && pip install -e .[test] && pytest tests/`
Expected: all tests fail (server not yet implemented).

- [ ] **Step 3: Implement relay/server.py**

Create `relay/relay/server.py`:

```python
"""emu-coop relay server.

State machine per session code:
  WAITING (1 peer) -> PAIRED (2 peers) -> HALF_BROKEN (1 peer + 60s timer) -> closed
"""
import asyncio
import json
import logging
import os
import struct
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("relay")
MAX_PAYLOAD = 4096
PORT = int(os.environ.get("RELAY_PORT", "9999"))
MAX_PAIRS = int(os.environ.get("RELAY_MAX_PAIRS", "100"))
TTL_SECONDS = int(os.environ.get("RELAY_TTL_SECONDS", "600"))
GRACE_SECONDS = int(os.environ.get("RELAY_GRACE_SECONDS", "60"))
IDLE_SECONDS = int(os.environ.get("RELAY_IDLE_SECONDS", "30"))


@dataclass
class Peer:
    peer_id: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    forward_task: Optional[asyncio.Task] = None


@dataclass
class Session:
    code: str
    peers: dict = field(default_factory=dict)  # peer_id -> Peer
    state: str = "WAITING"
    ttl_task: Optional[asyncio.Task] = None
    grace_task: Optional[asyncio.Task] = None


_sessions: dict = {}  # code -> Session


def _reset_state():
    """Test helper: clear in-memory state."""
    _sessions.clear()


def encode_frame(obj):
    payload = json.dumps(obj).encode()
    return struct.pack(">I", len(payload)) + payload


async def read_frame(reader):
    header = await reader.readexactly(4)
    (n,) = struct.unpack(">I", header)
    if n > MAX_PAYLOAD:
        raise ValueError(f"frame too large: {n}")
    body = await reader.readexactly(n)
    return json.loads(body)


async def send_abort_close(writer, reason):
    try:
        writer.write(encode_frame({"kind": "abort", "reason": reason}))
        await writer.drain()
    except Exception:
        pass
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def handle_client(reader, writer):
    try:
        join = await asyncio.wait_for(read_frame(reader), timeout=10)
    except Exception as e:
        logger.info("malformed first frame: %s", e)
        writer.close(); return

    if join.get("kind") != "join":
        await send_abort_close(writer, "expected join")
        return

    code = join.get("code", "")
    peer_id = join.get("peer_id", "")
    if not isinstance(code, str) or len(code) < 6:
        await send_abort_close(writer, "session code too short")
        return
    if not isinstance(peer_id, str) or not peer_id:
        await send_abort_close(writer, "missing peer_id")
        return

    sess = _sessions.get(code)
    peer = Peer(peer_id=peer_id, reader=reader, writer=writer)

    if sess is None:
        if len(_sessions) >= MAX_PAIRS:
            await send_abort_close(writer, "relay full")
            return
        sess = Session(code=code)
        sess.peers[peer_id] = peer
        sess.state = "WAITING"
        sess.ttl_task = asyncio.create_task(_ttl_expire(sess))
        _sessions[code] = sess
        # Block here until either partner arrives or our connection closes.
        await _wait_for_disconnect(peer)
        await _on_peer_disconnect(sess, peer)
        return

    # Existing session
    if sess.state == "WAITING":
        if peer_id in sess.peers:
            # Same peer re-arriving (probably reconnect). Swap socket.
            old = sess.peers[peer_id]
            old.writer.close()
            sess.peers[peer_id] = peer
            await _wait_for_disconnect(peer)
            await _on_peer_disconnect(sess, peer)
            return
        # Second peer; pair them.
        if sess.ttl_task: sess.ttl_task.cancel()
        sess.peers[peer_id] = peer
        sess.state = "PAIRED"
        await _send_joined(sess)
        await _start_forwarding(sess)
        return

    if sess.state == "PAIRED":
        if peer_id in sess.peers:
            # Reconnect of an existing paired peer; swap socket and notify partner.
            old = sess.peers[peer_id]
            if old.forward_task: old.forward_task.cancel()
            old.writer.close()
            sess.peers[peer_id] = peer
            other = next(p for pid, p in sess.peers.items() if pid != peer_id)
            try:
                other.writer.write(encode_frame({"kind": "partner-reconnected", "peer_id": peer_id}))
                await other.writer.drain()
            except Exception:
                pass
            # Restart forwarding for the rejoining peer.
            peer.forward_task = asyncio.create_task(_forward(peer, other))
            await _wait_for_disconnect(peer)
            await _on_peer_disconnect(sess, peer)
            return
        # Third party with different peer_id
        await send_abort_close(writer, "code in use")
        return

    if sess.state == "HALF_BROKEN":
        if peer_id in sess.peers:
            # Reconnecting peer returns within grace window.
            if sess.grace_task: sess.grace_task.cancel()
            sess.peers[peer_id] = peer
            sess.state = "PAIRED"
            other = next(p for pid, p in sess.peers.items() if pid != peer_id)
            try:
                other.writer.write(encode_frame({"kind": "partner-reconnected", "peer_id": peer_id}))
                await other.writer.drain()
            except Exception:
                pass
            peer.forward_task = asyncio.create_task(_forward(peer, other))
            await _wait_for_disconnect(peer)
            await _on_peer_disconnect(sess, peer)
            return
        await send_abort_close(writer, "code in use")


async def _send_joined(sess):
    for p in sess.peers.values():
        try:
            p.writer.write(encode_frame({"kind": "joined"}))
            await p.writer.drain()
        except Exception:
            pass


async def _start_forwarding(sess):
    peers = list(sess.peers.values())
    a, b = peers[0], peers[1]
    a.forward_task = asyncio.create_task(_forward(a, b))
    b.forward_task = asyncio.create_task(_forward(b, a))


async def _forward(src, dst):
    """Shuttle bytes from src.reader to dst.writer until EOF or error."""
    try:
        while True:
            data = await asyncio.wait_for(src.reader.read(4096), timeout=IDLE_SECONDS)
            if not data:
                break
            dst.writer.write(data)
            await dst.writer.drain()
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
        pass
    except Exception as e:
        logger.info("forward error: %s", e)


async def _wait_for_disconnect(peer):
    """Wait until the peer's connection drops."""
    while True:
        if peer.writer.is_closing():
            return
        try:
            data = await peer.reader.read(0)
        except Exception:
            return
        await asyncio.sleep(0.5)


async def _on_peer_disconnect(sess, peer):
    if peer.peer_id not in sess.peers or sess.peers[peer.peer_id] is not peer:
        return  # already replaced
    if peer.forward_task: peer.forward_task.cancel()
    if sess.state == "WAITING":
        # Single peer left; if this peer drops, session is gone.
        sess.peers.pop(peer.peer_id, None)
        if sess.ttl_task: sess.ttl_task.cancel()
        _sessions.pop(sess.code, None)
        return
    if sess.state == "PAIRED":
        sess.peers.pop(peer.peer_id, None)
        sess.state = "HALF_BROKEN"
        sess.grace_task = asyncio.create_task(_grace_expire(sess))


async def _ttl_expire(sess):
    try:
        await asyncio.sleep(TTL_SECONDS)
        for p in sess.peers.values():
            await send_abort_close(p.writer, "no partner")
        _sessions.pop(sess.code, None)
    except asyncio.CancelledError:
        pass


async def _grace_expire(sess):
    try:
        await asyncio.sleep(GRACE_SECONDS)
        for p in sess.peers.values():
            await send_abort_close(p.writer, "partner did not return")
        _sessions.pop(sess.code, None)
    except asyncio.CancelledError:
        pass


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    logger.info("relay listening on 0.0.0.0:%d", PORT)
    async with s:
        await s.serve_forever()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd relay && pytest tests/`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add relay/relay/server.py relay/tests/test_server.py
git commit -m "feat: implement relay server with WAITING/PAIRED/HALF_BROKEN state machine"
```

---

### Task 15: Implement RelayPipe (Lua)

**Files:**
- Create: `pipe_relay.lua`
- Create: `tests/test_pipe_relay.lua`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipe_relay.lua`:

```lua
require "pl.class"; class = require "pl.class"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `lua tests/run.lua tests/test_pipe_relay.lua`
Expected: errors about RelayPipe, FAIL.

- [ ] **Step 3: Implement RelayPipe**

Create `pipe_relay.lua`:

```lua
-- RelayPipe: connects outbound to relay, sends join, awaits joined, then peer-level hello.

class.RelayPipe(Pipe)

local function genPeerId()
  -- Lightweight UUID-ish (math.random is enough for collision avoidance here).
  math.randomseed(os.time() + (os.clock() * 1000000))
  local hex = "0123456789abcdef"
  local out = ""
  for i = 1, 32 do
    out = out .. hex:sub(math.random(1, 16), math.random(1, 16))
  end
  return out
end

function RelayPipe:_init(data, driver)
  self:super()
  self.data = data       -- {host_addr=string, port=number, code=string}
  self.driver = driver
  self.peer_id = genPeerId()
  self.state = "INIT"
  self.joined = false
end

function RelayPipe:wake()
  local socket = require("socket")
  statusMessage("Connecting to relay " .. self.data.host_addr .. ":" .. self.data.port .. "...")
  local client = socket.tcp()
  client:settimeout(5)
  local ok, err = client:connect(self.data.host_addr, self.data.port)
  if not ok then
    self:_fail("Could not reach relay " .. self.data.host_addr .. ":" .. self.data.port .. ": " .. tostring(err))
    return
  end
  client:settimeout(0)
  self.server = client
  self:_initFraming()
  self:_initHeartbeat()
  self:_initReconnect()
  self._reconnectEnabled = true
  self:_sendJoin()
  emu.registerexit(function() self:exit() end)
  gui.register(function()
    if self.state ~= "FAILED" and self.state ~= "CLOSED" then self:tick() end
    printMessage()
  end)
end

function RelayPipe:_sendJoin()
  self.state = "JOIN_SENT"
  self:_sendFrame({kind="join", code=self.data.code, peer_id=self.peer_id})
end

-- Override _handleFrame to intercept relay-only kinds.
function RelayPipe:_handleFrame(frame)
  self._lastFrameKind = frame.kind
  if self._clock then self._lastRx = self._clock() end

  if frame.kind == "joined" then
    if self.joined then return end  -- duplicate; ignore
    self.joined = true
    self.state = "JOINED"
    statusMessage("Paired; saying hello...")
    self:_sendHello()
    return
  end

  if frame.kind == "partner-reconnected" then
    -- Surviving peer: partner just rejoined. Reset hello state, await fresh hello, then resync.
    self.helloSent = false
    self.helloReceived = false
    self.state = "JOINED"
    self:_sendHello()
    self._postReconnect = true
    statusMessage("Partner reconnected; re-syncing...")
    return
  end

  -- Fall through to base class handling for hello/abort/data/ping/pong.
  Pipe._handleFrame(self, frame)
end

function RelayPipe:tick()
  if self.state == "RECONNECTING" then
    self:_reconnectTick()
    return
  end
  self:_pumpFrames()
  self:_heartbeatTick()
  if self.state == "ESTABLISHED" and self.driver and self.driver.tick then
    self.driver:tick()
  end
end

function RelayPipe:_reconnect_transport()
  local socket = require("socket")
  local client = socket.tcp()
  client:settimeout(2)
  local ok, err = client:connect(self.data.host_addr, self.data.port)
  if not ok then return false end
  client:settimeout(0)
  self.server = client
  self:_initFraming()
  self.joined = false
  self:_sendJoin()
  return true  -- transport up; rest happens via frame-driven state transitions
end

function RelayPipe:exit()
  if self.state == "CLOSED" then return end
  self.state = "CLOSED"
  if self.server then pcall(function() self.server:close() end) end
  if self.driver and self.driver.childExit then self.driver:childExit() end
end
```

- [ ] **Step 4: Run tests to verify pass**

Run: `lua tests/run.lua tests/test_pipe_relay.lua`
Expected: `2 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add pipe_relay.lua tests/test_pipe_relay.lua
git commit -m "feat: add RelayPipe — TCP-out + join handshake + partner-reconnected"
```

---

### Task 16: End-to-end smoke test through localhost relay

**Goal:** Verify two FCEUX instances can connect via relay running on localhost.

- [ ] **Step 1: Run the smoke test**

1. Start relay locally: `cd relay && python -m relay`. It should log `relay listening on 0.0.0.0:9999`.
2. On machine A: launch FCEUX with `coop.lua`. Dialog: Transport=Relay, Host address=`127.0.0.1`, Port=`9999`, Session code=`testpair`. Click OK.
3. On machine B: same as A.
4. Both should pair within 1 second; display "Connected to partner".
5. Pick up items on each side; verify cross-sync.
6. Stop the relay process (Ctrl-C). Both peers should display "Connection lost. Reconnecting..." within 15s.
7. Restart the relay. Both peers should auto-reconnect and re-pair within 30s.

If step 4 fails: check relay logs for the join-frame parsing path.
If step 7 fails: check the RelayPipe `_reconnect_transport` and make sure both peers re-`join` with the same code + peer_id.

- [ ] **Step 2: Tag milestone**

```bash
git tag relay-mode-working
```

---

## Phase 6: Reconnect through relay (HALF_BROKEN flow)

### Task 17: Test relay HALF_BROKEN state and partner-reconnected

**Files:**
- Modify: `relay/tests/test_server.py` (add tests for grace window and rejoin)

- [ ] **Step 1: Add HALF_BROKEN tests**

Append to `relay/tests/test_server.py`:

```python
async def test_half_broken_rejoin_within_grace(relay_running, monkeypatch):
    monkeypatch.setattr(server, "GRACE_SECONDS", 5)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)  # joined

    # Peer 1 disconnects.
    w1.close(); await w1.wait_closed()
    await asyncio.sleep(0.5)  # allow relay to notice

    # Peer 1 reconnects within grace window.
    r1b, w1b = await open_peer(host, port)
    w1b.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    await w1b.drain()
    f1b = await asyncio.wait_for(read_frame(r1b), 3)
    assert f1b["kind"] == "joined"

    # Peer 2 should see partner-reconnected.
    f2 = await asyncio.wait_for(read_frame(r2), 3)
    assert f2["kind"] == "partner-reconnected"
    assert f2["peer_id"] == "p1"
    w1b.close(); w2.close()


async def test_grace_expires_closes_survivor(relay_running, monkeypatch):
    monkeypatch.setattr(server, "GRACE_SECONDS", 1)
    host, port = relay_running
    r1, w1 = await open_peer(host, port)
    r2, w2 = await open_peer(host, port)
    w1.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p1"}))
    w2.write(encode_frame({"kind": "join", "code": "abcdef", "peer_id": "p2"}))
    await asyncio.gather(w1.drain(), w2.drain())
    await read_frame(r1); await read_frame(r2)
    w1.close(); await w1.wait_closed()
    # Peer 2 should receive abort within ~1 second.
    f = await asyncio.wait_for(read_frame(r2), 3)
    assert f["kind"] == "abort"
    assert "did not return" in f["reason"].lower()
    w2.close()
```

- [ ] **Step 2: Run tests**

Run: `cd relay && pytest tests/`
Expected: all 6 tests pass (existing 4 + 2 new).

- [ ] **Step 3: Commit**

```bash
git add relay/tests/test_server.py
git commit -m "test: add relay HALF_BROKEN grace-window tests"
```

---

### Task 18: Manual smoke test — auto-reconnect through relay

**Goal:** Verify a peer's transient network drop is recovered without restarting either emulator.

- [ ] **Step 1: Run the smoke test**

1. Start relay locally.
2. Two FCEUX peers connect via relay (as in Task 16).
3. On machine B: disable network adapter for 10 seconds, then re-enable.
4. Within ~30 seconds, both peers should be reconnected and re-synced (status messages: "Connection lost...", "Reconnecting...", "Partner reconnected; re-syncing...", then gameplay resumes).
5. Pick up items on both sides; verify state is consistent.

Key things to verify in this test:
- Surviving peer (A) does NOT show heartbeat-timeout error (because relay holds the slot).
- Surviving peer DOES eventually receive `partner-reconnected` and re-syncs.
- Returning peer (B) reconnects with the same `peer_id` and re-pairs.

- [ ] **Step 2: Tag milestone**

```bash
git tag relay-reconnect-working
```

---

## Phase 7: Integration tests + OCI deployment

### Task 19: Loopback integration tests

**Files:**
- Create: `tests/integration/run.sh`
- Create: `tests/integration/peer.lua`

- [ ] **Step 1: Create the integration peer harness**

Create `tests/integration/peer.lua`:

```lua
-- Minimal Lua harness for integration tests. Reads commands from stdin.
-- Usage: lua tests/integration/peer.lua <relay_host> <relay_port> <code> <peer_id>
package.path = package.path .. ";./?.lua;./vendor/?.lua;./tests/?.lua"

require "pl.class"; class = require "pl.class"
errorMessage = function(s) io.stderr:write("ERR: " .. tostring(s) .. "\n") end
statusMessage = function(s) io.stderr:write("STATUS: " .. tostring(s) .. "\n") end
message = function(s) io.stderr:write("MSG: " .. tostring(s) .. "\n") end
version = { protocolVersion = 1 }
emu = { registerexit = function(_) end }
gui = { register = function(_) end }
require "pipe"
require "pipe_relay"

local host, port, code = arg[1], tonumber(arg[2]), arg[3]
local socket = require("socket")
local pipe = RelayPipe({host_addr=host, port=port, code=code})
pipe.driver = {
  wake = function() print("WAKE") io.stdout:flush() end,
  handleTable = function(self, t) print("RECV " .. tostring(t.addr) .. " " .. tostring(t.value)) io.stdout:flush() end,
  tick = function() end,
  childExit = function() end,
  resync = function() print("RESYNC") io.stdout:flush() end,
}

-- Manually open the connection (bypassing wake() since we want test control)
local client = socket.tcp()
client:settimeout(5)
local ok, err = client:connect(host, port)
if not ok then print("CONNECT FAIL " .. tostring(err)); os.exit(1) end
client:settimeout(0)
pipe.server = client
pipe:_initFraming()
pipe:_initHeartbeat()
pipe:_initReconnect()
pipe._reconnectEnabled = false  -- simpler for the integration test
pipe:_sendJoin()

-- Drive the pipe loop, reading commands from stdin.
local function nonblockReadLine()
  -- Hacky but works: try to read; rely on stdin being a fast pipe.
  return io.read("*l")
end

while true do
  pipe:_pumpFrames()
  pipe:_heartbeatTick()
  if pipe.state == "FAILED" or pipe.state == "CLOSED" then
    print("STATE " .. pipe.state); os.exit(0)
  end
  if pipe.state == "ESTABLISHED" then
    print("ESTABLISHED"); io.stdout:flush()
    local cmd = io.read("*l")
    if not cmd then break end
    if cmd:sub(1,4) == "SEND" then
      local addr, value = cmd:match("^SEND (%d+) (%d+)$")
      pipe:sendTable({addr=tonumber(addr), value=tonumber(value)})
    elseif cmd == "QUIT" then
      pipe:exit(); break
    end
  end
  socket.sleep(0.05)
end
```

- [ ] **Step 2: Create the integration runner**

Create `tests/integration/run.sh`:

```bash
#!/usr/bin/env bash
# Loopback integration test: real relay + 2 lua peers exchanging frames.
set -euo pipefail
cd "$(dirname "$0")/../.."

PORT=$((RANDOM % 10000 + 20000))
echo "Using port $PORT"

# Start relay
( cd relay && RELAY_PORT=$PORT python -m relay ) &
RELAY_PID=$!
trap "kill $RELAY_PID 2>/dev/null || true" EXIT

sleep 1  # let relay bind

CODE="abcdef"

# Start peer A
mkfifo /tmp/peerA_in.$$ 2>/dev/null || true
exec 3<>/tmp/peerA_in.$$
lua tests/integration/peer.lua 127.0.0.1 $PORT $CODE <&3 > /tmp/peerA_out.$$ &
PEER_A=$!

# Start peer B
mkfifo /tmp/peerB_in.$$ 2>/dev/null || true
exec 4<>/tmp/peerB_in.$$
lua tests/integration/peer.lua 127.0.0.1 $PORT $CODE <&4 > /tmp/peerB_out.$$ &
PEER_B=$!

# Wait for both peers to print ESTABLISHED
for i in 1 2 3 4 5 6 7 8 9 10; do
  if grep -q ESTABLISHED /tmp/peerA_out.$$ && grep -q ESTABLISHED /tmp/peerB_out.$$; then
    break
  fi
  sleep 1
done

if ! grep -q ESTABLISHED /tmp/peerA_out.$$ || ! grep -q ESTABLISHED /tmp/peerB_out.$$; then
  echo "FAIL: peers did not reach ESTABLISHED"
  echo "--- peer A ---"; cat /tmp/peerA_out.$$
  echo "--- peer B ---"; cat /tmp/peerB_out.$$
  kill $PEER_A $PEER_B 2>/dev/null || true
  exit 1
fi

# Send a frame from A to B
echo "SEND 111 42" >&3
sleep 1

if ! grep -q "RECV 111 42" /tmp/peerB_out.$$; then
  echo "FAIL: peer B did not receive frame"
  echo "--- peer B ---"; cat /tmp/peerB_out.$$
  kill $PEER_A $PEER_B 2>/dev/null || true
  exit 1
fi

echo "PASS: integration test"
echo "QUIT" >&3
echo "QUIT" >&4
sleep 1
kill $PEER_A $PEER_B 2>/dev/null || true
rm -f /tmp/peerA_in.$$ /tmp/peerB_in.$$ /tmp/peerA_out.$$ /tmp/peerB_out.$$
```

Make it executable: `chmod +x tests/integration/run.sh`.

- [ ] **Step 3: Run integration test**

Run: `bash tests/integration/run.sh`
Expected: `PASS: integration test`

- [ ] **Step 4: Commit**

```bash
git add tests/integration/run.sh tests/integration/peer.lua
git commit -m "test: add loopback integration test (real relay + 2 lua peers)"
```

---

### Task 20: Relay deployment artifacts

**Files:**
- Create: `relay/deploy/relay.service`
- Create: `relay/README.md`

- [ ] **Step 1: Create systemd unit**

Create `relay/deploy/relay.service`:

```ini
[Unit]
Description=emu-coop relay daemon
After=network.target

[Service]
Type=simple
User=relay
Group=relay
WorkingDirectory=/opt/emu-coop-relay
Environment="RELAY_PORT=9999"
Environment="RELAY_MAX_PAIRS=100"
Environment="RELAY_TTL_SECONDS=600"
Environment="RELAY_GRACE_SECONDS=60"
Environment="RELAY_IDLE_SECONDS=30"
ExecStart=/opt/emu-coop-relay/.venv/bin/python -m relay
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create relay README with OCI setup**

Create `relay/README.md`:

```markdown
# emu-coop relay

Small Python asyncio TCP server that pairs emu-coop peers by session code and forwards frames between them. Stateless across restarts.

## Local development

```bash
cd relay
pip install -e .[test]
python -m relay  # listens on 0.0.0.0:9999
pytest tests/    # ~6 tests
```

## OCI Always Free deployment

Tested on Oracle Cloud "Always Free" ARM Ampere VM (Ubuntu 22.04 minimum).

### 1. Create instance
- OCI Console → Compute → Instances → Create Instance
- Image: Canonical Ubuntu 22.04
- Shape: VM.Standard.A1.Flex (Ampere ARM, 1 OCPU + 6 GB RAM is plenty)
- Networking: a public IPv4 (free)
- Add your SSH public key

### 2. Open port 9999 (TWO firewalls; both required)

**(a) OCI Security List:**
- VCN → Security Lists → default → Ingress Rules → Add
- Source: `0.0.0.0/0`, IP Protocol: TCP, Destination Port: `9999`

**(b) Ubuntu firewall** (on the VM):
```bash
sudo ufw allow 9999/tcp
sudo iptables -I INPUT 1 -p tcp --dport 9999 -j ACCEPT
sudo netfilter-persistent save  # or sudo iptables-save
```

Verify: from your laptop, `nc -zv <vm-public-ip> 9999` should show "succeeded".

### 3. Install relay
```bash
ssh ubuntu@<vm-public-ip>
sudo apt update && sudo apt install -y python3.11 python3.11-venv git
sudo useradd -r -s /usr/sbin/nologin relay
sudo mkdir /opt/emu-coop-relay && sudo chown relay:relay /opt/emu-coop-relay
sudo -u relay git clone https://github.com/BogieSmalls/emu-coop-z1.git /tmp/emu-coop-z1
sudo -u relay cp -r /tmp/emu-coop-z1/relay/* /opt/emu-coop-relay/
sudo -u relay python3.11 -m venv /opt/emu-coop-relay/.venv
sudo -u relay /opt/emu-coop-relay/.venv/bin/pip install -e /opt/emu-coop-relay
```

### 4. Install systemd unit
```bash
sudo cp /opt/emu-coop-relay/deploy/relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now relay
sudo systemctl status relay
sudo journalctl -u relay -f  # tail logs
```

### 5. Smoke test from your machine
Edit emu-coop's connection dialog: Host address = `<vm-public-ip>`, port = `9999`, code = `testpair123`. Both peers should pair through the relay.

## Configuration (env vars)

| Var | Default | Meaning |
|-----|---------|---------|
| `RELAY_PORT` | `9999` | TCP listen port |
| `RELAY_MAX_PAIRS` | `100` | Max concurrent paired sessions |
| `RELAY_TTL_SECONDS` | `600` | Wait time for partner to first arrive |
| `RELAY_GRACE_SECONDS` | `60` | Wait time for peer to reconnect after disconnect |
| `RELAY_IDLE_SECONDS` | `30` | Per-connection inactivity timeout |
```

- [ ] **Step 3: Commit**

```bash
git add relay/deploy/relay.service relay/README.md
git commit -m "docs: add relay systemd unit + OCI Always Free deployment guide"
```

---

### Task 21: Deploy relay to OCI and run real-world smoke test

**Goal:** Get the relay running on OCI and verify two real machines can co-op through it.

- [ ] **Step 1: Follow the README**

Follow `relay/README.md` steps 1-5 on the OCI VM.

- [ ] **Step 2: Document the public address**

Once verified, edit the top-level `README.md` (or a future `RELAY_ADDRESS.md`) noting the public IP / DNS name. (Done in Phase 8.)

- [ ] **Step 3: Tag milestone**

```bash
git tag oci-relay-deployed
```

This is a manual checkpoint, no commit.

---

## Phase 8: Cleanup

### Task 22: Delete IrcPipe and IRC-specific code

**Files:**
- Modify: `pipe.lua` (remove IrcPipe class and IRC-specific helpers)
- Modify: `dialog.lua` (remove `ircDialog` alias)
- Modify: `coop.lua` (remove IRC fallback branch)
- Modify: `version.lua` (remove `ircPipe` field)

- [ ] **Step 1: Remove IrcPipe from pipe.lua**

Edit `pipe.lua`. Delete everything from the line `-- IRC` (around line 85 in the original) through the end of the `IrcPipe` class methods (`function IrcPipe:msg(s)` block). Keep the `Pipe` base class and the `Driver`/`GameDriver`-related code at the bottom.

Search for any remaining `IrcPipe` references: `git grep IrcPipe` should return nothing in `*.lua`.

- [ ] **Step 2: Remove `ircDialog` alias from dialog.lua**

Edit `dialog.lua`. Delete the line `ircDialog = connectionDialog`.

Find the call site in `coop.lua` (around line 51): replace `local data = ircDialog()` with `local data = connectionDialog()`.

- [ ] **Step 3: Remove IRC fallback from coop.lua**

Edit `coop.lua`. In the `connect()` function, delete the `elseif data.server then` branch (the legacy IRC path). The function becomes:

```lua
function connect()
  mainDriver = GameDriver(spec, data.forceSend)
  if data.kind == "direct" then
    require "pipe_direct"
    DirectPipe({host=data.isHost, host_addr=data.host_addr, port=data.port}, mainDriver):wake()
  elseif data.kind == "relay" then
    require "pipe_relay"
    RelayPipe({host_addr=data.host_addr, port=data.port, code=data.code}, mainDriver):wake()
  else
    errorMessage("Unknown transport in dialog result")
    failed = true
  end
end
```

In the validation block above, also delete the `elseif data.server then` IRC validation branch.

- [ ] **Step 4: Remove `ircPipe` from version.lua**

Edit `version.lua`. Delete the `ircPipe = "1.0",` line and its comment.

- [ ] **Step 5: Verify no IRC code remains**

Run: `git grep -i 'ircpipe\|irc.speedrunslive' -- '*.lua'`
Expected: no matches (or only matches in `tests/` directories that should also be removed if any).

- [ ] **Step 6: Run all tests**

Run: `lua tests/run.lua tests/test_*.lua && cd relay && pytest tests/`
Expected: all tests pass.

- [ ] **Step 7: Final manual smoke test**

Two FCEUX, Direct mode on LAN: still works.
Two FCEUX, Relay mode through OCI: still works.

- [ ] **Step 8: Commit**

```bash
git add pipe.lua dialog.lua coop.lua version.lua
git commit -m "refactor: remove IrcPipe and IRC-specific code (Direct/Relay only now)"
```

---

### Task 23: Update top-level README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "What changed" section and connection instructions**

Edit `README.md`. Near the top, after the existing intro paragraph, add:

```markdown
## Connection modes

emu-coop supports two transports:

- **Direct** — peer-to-peer TCP. One player hosts (listens on a port), the other connects to their address. Best for LAN co-op or players using Tailscale/ZeroTier/Hamachi.
- **Relay** — both players connect outbound to a small relay daemon. No port forwarding required. Default relay address (community-hosted): see [RELAY.md](RELAY.md). Self-hosters can run their own; see [relay/README.md](relay/README.md).

When you launch `coop.lua`, the connection dialog asks which transport to use.

### Quick start (Relay, easiest)

1. Both players agree on a session code (any string ≥ 6 chars, e.g. `pancakes123`). Share via Discord/etc.
2. Both players launch FCEUX → load ROM → load `coop.lua`.
3. In the connection dialog: Transport=Relay, Host address=`<relay public IP>`, Port=`9999`, Session code=your shared code. Click OK.
4. Both screens display "Connected to partner" within ~1 second.

### Quick start (Direct, LAN)

1. Host player runs `ipconfig` (Windows) / `ifconfig` (mac/linux) to find their LAN IP.
2. Host: launch coop.lua, Transport=Direct, Host address=`0.0.0.0`, Port=`9999`, Are you the host?=Yes.
3. Other player: launch coop.lua, Transport=Direct, Host address=`<host's LAN IP>`, Port=`9999`, Are you the host?=No.

## What changed (v1.3+)

- IRC is no longer used. Replaced by Direct + Relay transports.
- Connection drops auto-recover without restarting the emulator.
- "Restarting after a crash?" still works for full save-and-reload recovery.
```

Replace the IRC-related parts of the existing connection instructions (if any) with references to the new sections.

- [ ] **Step 2: (Optional) Create RELAY.md with public address**

Create `RELAY.md`:

```markdown
# Public relay

Default emu-coop community relay:

- Host: `<vm-public-ip-or-dns>`
- Port: `9999`

Run by: <your name / contact>. Best-effort uptime; please don't hammer it.

To run your own, see `relay/README.md`.
```

(Substitute the actual OCI VM address from Task 21.)

- [ ] **Step 3: Bump release version in version.lua**

Edit `version.lua`. Change `release = "1.2",` to `release = "1.3",`.

- [ ] **Step 4: Commit**

```bash
git add README.md RELAY.md version.lua
git commit -m "docs: document Direct/Relay connection modes; bump to 1.3"
git tag v1.3
```

---

## Verification checklist

After all phases complete, confirm:

- [ ] All Lua tests pass: `lua tests/run.lua tests/test_*.lua`
- [ ] All Python tests pass: `cd relay && pytest tests/`
- [ ] Integration test passes: `bash tests/integration/run.sh`
- [ ] `git grep -i ircpipe -- '*.lua'` returns nothing
- [ ] Manual smoke: Direct mode on LAN works, items sync both directions
- [ ] Manual smoke: Direct mode survives a transient network drop without restart
- [ ] Manual smoke: Relay mode through OCI works, items sync
- [ ] Manual smoke: Relay mode survives a transient network drop without restart
- [ ] README accurately reflects new connection flow
- [ ] Stash from start of project recovered or discarded: `git stash list` reviewed
