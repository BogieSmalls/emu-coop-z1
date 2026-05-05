-- NETWORKING

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

-- A Pipe class is responsible for, somehow or other, connecting to the internet and funnelling data between driver objects on different machines.

class.Pipe()
function Pipe:_init()
	self.buffer = ""
end

function Pipe:wake(server)
	if pipeDebug then print("Connected") end
	statusMessage("Logging in to server...") -- This creates an unfortunate implicit contract where the driver needs to statusMessage(nil)
	self.server = server
	self.server:settimeout(0)

	emu.registerexit(function()
		self:exit()
	end)

	self:childWake()

	gui.register(function()
		if not self.dead then self:tick() end
		printMessage()
	end)
end

function Pipe:exit()
	if pipeDebug then print("Disconnecting") end
	self.dead = true
	self.server:close()
	self:childExit()
end

function Pipe:fail(err)
	self:exit()
end

function Pipe:send(s)
	if pipeDebug then print("SEND: " .. s) end

	local res, err = self.server:send(s .. "\r\n")
	if not res then
		errorMessage("Connection died: " .. s)
		self:exit()
		return false
	end
	return true
end

function Pipe:receivePump()
	while not self.dead do -- Loop until no data left
		local result, err = self.server:receive(1) -- Pull one byte
		if not result then
			if err ~= "timeout" then
				errorMessage("Connection died: " .. err)
				self:exit()
			end
			return
		end

		-- Got useful data
		self.buffer = self.buffer .. result
		if result == "\n" then -- Only 
			self:handle(self.buffer)
			self.buffer = ""
		end
	end
end

function Pipe:tick()
	self:receivePump()
	self:childTick()
end

function Pipe:childWake() end
function Pipe:childExit() end
function Pipe:childTick() end
function Pipe:handle() end

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
end

-- For tests: send any hello shape (real code uses _sendHello).
function Pipe:_sendHelloRaw(t)
  -- Set state before _sendFrame so a send failure (which calls _fail → FAILED)
  -- isn't overwritten when control returns here.
  self.helloSent = true
  self.state = "HELLO_SENT"
  self:_sendFrame(t)
end

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
  self._lastFrameKind = frame.kind
  if self._clock then self._lastRx = self._clock() end
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
      if self._postReconnect then
        -- Reconnect: don't re-wake the driver (would re-register memory.registerwrite
        -- callbacks). Just trigger a state re-sync.
        self._postReconnect = false
        if self.driver and self.driver.resync then self.driver:resync() end
        message("Reconnected — re-syncing state")
      else
        if self.driver and self.driver.wake then self.driver:wake(self) end
      end
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

function Pipe:abort(reason)
  self:_sendFrame({kind="abort", reason=reason})
  self:_fail("Aborted: " .. tostring(reason))
end

function Pipe:_initHeartbeat(clock_fn)
  self._clock = clock_fn or function() return os.time() end
  self._lastRx = self._clock()
  self._lastPing = self._clock()
end

Pipe.HEARTBEAT_INTERVAL = 5
Pipe.HEARTBEAT_TIMEOUT = 15

function Pipe:_heartbeatTick()
  if not self._clock then return end  -- _initHeartbeat hasn't been called
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

-- Default post-reconnect handshake: send hello immediately. RelayPipe
-- overrides this to send join first (and let the joined frame trigger hello).
function Pipe:_postReconnectHandshake()
  self:_sendHello()
end

function Pipe:_reconnectTick()
  if self.state ~= "RECONNECTING" then return end
  local now = self._clock and self._clock() or os.time()
  if not self._nextRetryAt or now < self._nextRetryAt then return end
  statusMessage("Reconnecting (attempt " .. ((self._reconnectAttempt or 0) + 1) .. ")...")
  local ok = self:_reconnect_transport()
  if ok then
    self.helloSent = false
    self.helloReceived = false
    self.state = "TRANSPORT_READY"
    self:_initFraming()
    -- Reset heartbeat timestamps so an old _lastRx (from before the drop)
    -- doesn't immediately re-trigger the silence timeout on the fresh socket.
    self._lastRx = now
    self._lastPing = now
    -- Reset attempt counter so a future drop starts the backoff schedule fresh.
    self._reconnectAttempt = 0
    self:_postReconnectHandshake()
    -- After successful reconnect handshake, trigger Driver:resync.
    self._postReconnect = true
  else
    self._nextRetryAt = now + self:_nextBackoff()
  end
end

-- Driver base class-- knows how to convert to/from tables

class.Driver()
function Driver:_init() end

function Driver:wake(pipe)
	self.pipe = pipe
	self:childWake()
end

function Driver:sendTable(t)
	self.pipe:sendTable(t)
end

-- Text-frame parse path (new pipes call handleTable directly with the already-decoded body).
function Driver:handle(s)
	local t, err = pretty.read(s)
	if driverDebug then print("Driver got table " .. tostring(t)) end
	if t then
		self:handleTable(t)
	else
		self.handleFailure(s, err)
	end
end

function Driver:tick()
	self:childTick()
end

function Driver:childWake() end
function Driver:childTick() end
function Driver:resync() end  -- no-op; subclasses override
function Driver:handleTable(t) end
function Driver:handleFailure(s, err) end
