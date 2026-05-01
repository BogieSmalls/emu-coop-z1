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
    -- If peer closed and our buffer is empty, surface as "closed".
    if #combined == 0 and theirState.closed then
      return nil, "closed"
    end
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
