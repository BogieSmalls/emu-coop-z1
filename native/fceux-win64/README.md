# FCEUX Win64 Native Modules

These 64-bit Lua 5.1 native modules are staged into the `fceux-win64` zip by `build-fceux.ps1`:

- `iup.dll`: IUP 3.32 Win64 dynamic library.
- `iuplua.dll`: IUP 3.32 Lua 5.1 Win64 module, renamed from `iuplua51.dll` so `require("iuplua")` works.
- `socket/core.dll`: LuaSocket 3.1.0 `socket.core`, built as x64 against FCEUX 2.6.6's `lua5.1.dll` ABI.

FCEUX 2.6.6 x64 ships `lua5.1.dll` and a `lua51.dll` compatibility forwarder; these DLLs intentionally are not bundled here.
