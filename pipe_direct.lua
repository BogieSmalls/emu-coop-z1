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
        self._connectFn = nil
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
  end
  self:_initHeartbeat()
  self:_initReconnect()
  self._reconnectEnabled = true
  emu.registerexit(function() self:exit() end)
  gui.register(function()
    if self.state ~= "FAILED" and self.state ~= "CLOSED" then self:tick() end
    printMessage()
  end)
end

function DirectPipe:tick()
  if self._connectFn then
    self._connectFn()
    return
  end
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

function DirectPipe:exit()
  if self.state == "CLOSED" then return end
  self.state = "CLOSED"
  if self.server then pcall(function() self.server:close() end) end
  if self._listener then pcall(function() self._listener:close() end) end
  if self.driver and self.driver.childExit then self.driver:childExit() end
end

function DirectPipe:_reconnect_transport()
  local socket = require("socket")
  if self.data.host then
    -- Close any leftover listener from a prior failed accept-poll cycle
    -- so we don't hit "address already in use" on bind.
    if self._listener then
      pcall(function() self._listener:close() end)
      self._listener = nil
    end
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
