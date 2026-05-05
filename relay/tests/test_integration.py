"""End-to-end integration test: real Lua peers exchanging frames through real relay."""
import asyncio
import os
import pytest

from relay import server

LUAJIT = r"C:\Users\bogie\AppData\Local\Programs\LuaJIT\bin\luajit.exe"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PEER_SCRIPT = os.path.join(REPO_ROOT, "tests", "integration", "peer.lua")


@pytest.fixture
async def relay_running():
    """Start a relay on an ephemeral port and yield (host, port)."""
    s = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    server._reset_state()
    task = asyncio.create_task(s.serve_forever())
    yield ("127.0.0.1", port)
    task.cancel()
    s.close()
    await s.wait_closed()


@pytest.mark.skipif(
    not os.environ.get("EMU_COOP_INTEGRATION"),
    reason=(
        "Integration test is opt-in. Set EMU_COOP_INTEGRATION=1 to run. "
        "Requires standalone LuaJIT with a compatible LuaSocket on its package.cpath. "
        "On Windows the repo's socket/core.dll is bundled with FCEUX (32-bit/different ABI) "
        "and can't be loaded by standalone 64-bit LuaJIT — install LuaSocket via luarocks "
        "or run on a system where standalone LuaJIT can find LuaSocket."
    ),
)
@pytest.mark.skipif(not os.path.exists(LUAJIT), reason="LuaJIT not installed at expected path")
async def test_loopback_lua_peers_via_relay(relay_running):
    """Two real Lua peers exchange 3 frames through the real relay."""
    host, port = relay_running
    code = "loopint"

    # Spawn both peers concurrently so they can find each other through the relay
    sender = await asyncio.create_subprocess_exec(
        LUAJIT, PEER_SCRIPT, "sender", host, str(port), code,
        cwd=REPO_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    recv = await asyncio.create_subprocess_exec(
        LUAJIT, PEER_SCRIPT, "recv", host, str(port), code,
        cwd=REPO_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait for both to finish (with timeout)
    try:
        sender_stdout, sender_stderr = await asyncio.wait_for(sender.communicate(), timeout=15)
        recv_stdout, recv_stderr = await asyncio.wait_for(recv.communicate(), timeout=15)
    except asyncio.TimeoutError:
        sender.kill()
        recv.kill()
        await asyncio.gather(sender.wait(), recv.wait())
        pytest.fail("Lua peers timed out")

    sender_out = sender_stdout.decode() if sender_stdout else ""
    sender_err = sender_stderr.decode() if sender_stderr else ""
    recv_out = recv_stdout.decode() if recv_stdout else ""
    recv_err = recv_stderr.decode() if recv_stderr else ""

    # Print on failure for debugging
    if sender.returncode != 0 or recv.returncode != 0 or "RECV" not in recv_out:
        print(f"sender exit={sender.returncode}\nstdout: {sender_out}\nstderr: {sender_err}")
        print(f"recv exit={recv.returncode}\nstdout: {recv_out}\nstderr: {recv_err}")

    assert sender.returncode == 0, f"sender failed: {sender_err}"
    assert recv.returncode == 0, f"recv failed: {recv_err}"

    # Verify the receiver got all 3 frames
    assert "RECV 10 1" in recv_out
    assert "RECV 20 2" in recv_out
    assert "RECV 30 3" in recv_out
    assert "DONE" in recv_out
