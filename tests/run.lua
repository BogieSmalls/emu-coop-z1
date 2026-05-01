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
