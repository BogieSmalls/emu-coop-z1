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

-- Override _handleFrame to intercept relay-only kinds (joined).
-- partner-reconnected handling is Task 17.
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
  -- Symmetric with DirectPipe: just dial. The base _reconnectTick will
  -- _initFraming and call _postReconnectHandshake (overridden below).
  local socket = require("socket")
  local client = socket.tcp()
  client:settimeout(2)
  local ok, err = client:connect(self.data.host_addr, self.data.port)
  if not ok then return false end
  client:settimeout(0)
  self.server = client
  return true
end

-- Override the post-reconnect handshake: relay needs join -> joined -> hello,
-- not hello directly. The joined frame handler in _handleFrame triggers hello.
function RelayPipe:_postReconnectHandshake()
  self.joined = false
  self:_sendJoin()
end

function RelayPipe:exit()
  if self.state == "CLOSED" then return end
  self.state = "CLOSED"
  if self.server then pcall(function() self.server:close() end) end
  if self.driver and self.driver.childExit then self.driver:childExit() end
end
