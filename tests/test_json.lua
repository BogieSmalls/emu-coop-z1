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
