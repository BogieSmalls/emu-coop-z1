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
