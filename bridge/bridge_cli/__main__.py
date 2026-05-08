"""CLI entry point for the bridge.

Usage:
  python -m bridge_cli run --mode tloz_all --port COM3 --code mycode \
                            [--relay 129.158.62.225] [--relay-port 9999]
                            [--force-send]
  python -m bridge_cli patch <input.nes> -o <output.nes>
  python -m bridge_cli read --port COM3 --addr 0x0657 --length 16
  python -m bridge_cli mister-run --mode tloz_all --mister-host mister.local \
                                  --code mycode
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
import uuid
from importlib import import_module
from pathlib import Path

import serial

from bridge_core import ips
from bridge_core.cc_client import CCClient
from bridge_core.cc_endpoint import CCMemoryEndpoint
from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint
from bridge_core.mister_helper import MisterHelperMemoryEndpoint, MisterHelperServer
from bridge_core.mister_ra import DevMemRAMirrorSource, FileRAMirrorSource
from bridge_core.pipe_client import PipeClient
from bridge_core.readonly_session import run_readonly_session
from bridge_core.status_sink import ConsoleStatusSink
from bridge_core.sync_engine import SyncEngine

POLL_HZ = 10
POLL_PERIOD = 1.0 / POLL_HZ


def cmd_patch(args: argparse.Namespace) -> int:
    src = Path(args.input).read_bytes()
    patches_dir = Path(__file__).parent.parent / "bridge_core" / "patches"
    patch_bytes = (patches_dir / "zelda_emu_coop_plus.ips").read_bytes()
    expected = ips.load_expected_manifest(
        (patches_dir / "zelda_emu_coop_plus.expected.json").read_bytes()
    )
    if ips.is_patched(src, patch_bytes):
        print(f"Already patched: {args.input}")
        if args.output:
            Path(args.output).write_bytes(src)
        return 0
    try:
        out = ips.apply_validated(src, patch_bytes, expected)
    except ips.RomConflict as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "This ROM has been modified at offsets where emu-coop-plus needs to "
            "write. If this is a randomizer seed, please report the flagstring "
            "so we can audit.",
            file=sys.stderr,
        )
        return 2
    out_path = args.output or args.input.replace(".nes", "_emucoop.nes")
    Path(out_path).write_bytes(out)
    print(f"Patched: {args.input} -> {out_path}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    cc = CCClient(sp)
    cc.send_read_array(args.addr, args.length)
    result = cc.poll_response(timeout_ms=500)
    if result is None:
        print("timeout", file=sys.stderr)
        return 1
    print(" ".join(f"{b:02X}" for b in result))
    return 0


def cmd_mister_read(args: argparse.Namespace) -> int:
    source = _make_mister_source(args.mirror_file)
    endpoint = ReadOnlyMisterMemoryEndpoint(source)
    try:
        snapshot = endpoint.read_ranges([(args.addr, args.length)])
        if snapshot is None:
            print("mirror busy or inactive", file=sys.stderr)
            return 1
        print(" ".join(f"{snapshot[args.addr + offset]:02X}" for offset in range(args.length)))
        return 0
    finally:
        endpoint.close()


def cmd_mister_helper(args: argparse.Namespace) -> int:
    source = _make_mister_source(args.mirror_file)
    endpoint = ReadOnlyMisterMemoryEndpoint(source)
    server = MisterHelperServer((args.host, args.port), endpoint)
    try:
        host, port = server.server_address
        print(f"MiSTer helper listening on {host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        endpoint.close()
    return 0


def cmd_mister_run(args: argparse.Namespace) -> int:
    sink = ConsoleStatusSink()
    sink.log(f"Loading mode: {args.mode}")
    mode = import_module(f"bridge_core.modes.{args.mode}")

    sink.log(f"Connecting to MiSTer helper {args.mister_host}:{args.mister_port}")
    endpoint = MisterHelperMemoryEndpoint(
        host=args.mister_host,
        port=args.mister_port,
        timeout=args.mister_timeout,
    )

    sink.log(f"Connecting to relay {args.relay}:{args.relay_port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((args.relay, args.relay_port))
    sock.setblocking(False)

    peer_id = uuid.uuid4().hex
    pipe = PipeClient(socket=sock, code=args.code, peer_id=peer_id)
    return run_readonly_session(
        endpoint=endpoint,
        pipe=pipe,
        mode=mode,
        sink=sink,
        poll_hz=args.poll_hz,
    )


def _make_mister_source(mirror_file: str | None):
    if mirror_file:
        return FileRAMirrorSource(mirror_file)
    return DevMemRAMirrorSource()


def cmd_run(args: argparse.Namespace) -> int:
    sink = ConsoleStatusSink()
    sink.log(f"Loading mode: {args.mode}")
    mode = import_module(f"bridge_core.modes.{args.mode}")

    sink.log(f"Opening serial port {args.port} @ {args.baud}")
    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    cc = CCClient(sp)
    endpoint = CCMemoryEndpoint(cc)

    sink.log(f"Connecting to relay {args.relay}:{args.relay_port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((args.relay, args.relay_port))
    sock.setblocking(False)

    peer_id = uuid.uuid4().hex
    pipe = PipeClient(socket=sock, code=args.code, peer_id=peer_id)
    pipe._reconnect_enabled = True

    engine = SyncEngine(endpoint=endpoint, mode=mode)
    if args.force_send:
        engine.force_send = True
        sink.log("force_send enabled")

    pipe.on_data = lambda body: _on_data(engine, sink, body)
    pipe.on_abort = lambda reason: sink.message(f"Partner aborted: {reason}")
    def _reconnected():
        sink.message("Partner reconnected — re-syncing state")
        engine.resync()
    pipe.on_partner_reconnected = _reconnected
    pipe.send_join()

    # App-level hello (after pipe ESTABLISHED)
    app_hello_sent = False
    last_state = None
    sink.state("CONNECTING")

    try:
        while pipe.state != "CLOSED":
            loop_start = time.monotonic()

            # When pipe wants to reconnect, open a fresh socket and re-JOIN.
            if pipe.state == "RECONNECTING":
                retry_at = pipe._next_retry_at or 0
                if loop_start >= retry_at:
                    try:
                        new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        new_sock.connect((args.relay, args.relay_port))
                        new_sock.setblocking(False)
                        pipe.reset_for_reconnect(new_sock)
                        pipe.send_join()
                        sink.log(f"Relay reconnect attempt #{pipe._reconnect_attempt}")
                        sock = new_sock
                    except Exception as e:
                        sink.log(f"Reconnect attempt failed: {e}")
                        pipe._next_retry_at = loop_start + pipe._next_backoff()

            pipe.tick()
            pipe.heartbeat_tick()

            # Surface every state transition
            if pipe.state != last_state:
                sink.state(pipe.state)
                if pipe.state == "RECONNECTING":
                    sink.message("Partner disconnected; reconnecting…")
                    app_hello_sent = False
                last_state = pipe.state

            if pipe.state == "ESTABLISHED" and not app_hello_sent:
                pipe.send_data({"op": "hello", "guid": mode.GUID, "version": "0.1.0"})
                app_hello_sent = True

            if pipe.state == "ESTABLISHED":
                # Poll the mode's READ_RANGES via Action 0x01 (ArrayRead).
                # Much lighter on the cart's main-loop than scattered reads.
                full_snapshot = endpoint.read_ranges(mode.READ_RANGES, timeout_ms=300)
                if full_snapshot is not None:
                    if engine.is_game_running(full_snapshot):
                        if not engine.did_cache:
                            to_send = engine.check_first_running(full_snapshot)
                            for addr, value in to_send:
                                pipe.send_data({"addr": addr, "value": value})
                        for addr, send_value, msg in engine.diff(full_snapshot):
                            pipe.send_data({"addr": addr, "value": send_value})
                            if msg:
                                sink.message(msg)
                    else:
                        if engine.did_cache:
                            sink.log("Game stopped running; pausing sync")
                            engine.did_cache = False

            elapsed = time.monotonic() - loop_start
            sleep = POLL_PERIOD - elapsed
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        sink.log("Interrupted by user")

    pipe.close()
    sp.close()
    sock.close()
    sink.state("DISCONNECTED")
    return 0 if pipe.state != "FAILED" else 1


def _on_data(engine: SyncEngine, sink: ConsoleStatusSink, body: dict) -> None:
    if body.get("op") == "hello":
        if body.get("guid") != engine.mode.GUID:
            sink.message(f"Partner has incompatible mode: {body.get('guid')}")
            return
        sink.log(f"Partner's app hello OK (guid={body['guid']}, version={body.get('version')})")
        return
    messages = engine.handle_table(body)
    for m in messages:
        sink.message(m)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_patch = sub.add_parser("patch", help="Apply CC IPS patch to a ROM")
    p_patch.add_argument("input")
    p_patch.add_argument("-o", "--output")

    p_read = sub.add_parser("read", help="One-shot RAM read for diagnostics")
    p_read.add_argument("--port", required=True)
    p_read.add_argument("--baud", type=int, default=115200)
    p_read.add_argument("--addr", type=lambda s: int(s, 0), required=True)
    p_read.add_argument("--length", type=int, default=1)

    p_mister_read = sub.add_parser(
        "mister-read",
        help="One-shot NES RAM read from MiSTer's RA mirror",
    )
    p_mister_read.add_argument(
        "--mirror-file",
        help="Read a captured RA mirror file instead of mapping /dev/mem",
    )
    p_mister_read.add_argument("--addr", type=lambda s: int(s, 0), required=True)
    p_mister_read.add_argument("--length", type=int, default=1)

    p_mister_helper = sub.add_parser(
        "mister-helper",
        help="Serve MiSTer RA mirror reads over a tiny JSON-line TCP helper",
    )
    p_mister_helper.add_argument("--host", default="0.0.0.0")
    p_mister_helper.add_argument("--port", type=int, default=55355)
    p_mister_helper.add_argument(
        "--mirror-file",
        help="Serve a captured RA mirror file instead of mapping /dev/mem",
    )

    p_mister_run = sub.add_parser(
        "mister-run",
        help="Run a read-only MiSTer bridge through the relay",
    )
    p_mister_run.add_argument("--mode", required=True, help="Mode module name, e.g. tloz_all")
    p_mister_run.add_argument("--mister-host", required=True)
    p_mister_run.add_argument("--mister-port", type=int, default=55355)
    p_mister_run.add_argument("--mister-timeout", type=float, default=1.0)
    p_mister_run.add_argument("--code", required=True, help="Session code (6+ chars)")
    p_mister_run.add_argument("--relay", default="129.158.62.225")
    p_mister_run.add_argument("--relay-port", type=int, default=9999)
    p_mister_run.add_argument("--poll-hz", type=int, default=POLL_HZ)

    p_run = sub.add_parser("run", help="Run the bridge: connect to relay and sync game state")
    p_run.add_argument("--mode", required=True, help="Mode module name, e.g. tloz_all")
    p_run.add_argument("--port", required=True, help="Serial port (e.g. COM3)")
    p_run.add_argument("--baud", type=int, default=115200)
    p_run.add_argument("--code", required=True, help="Session code (6+ chars)")
    p_run.add_argument("--relay", default="129.158.62.225")
    p_run.add_argument("--relay-port", type=int, default=9999)
    p_run.add_argument("--force-send", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "patch":
        return cmd_patch(args)
    elif args.cmd == "read":
        return cmd_read(args)
    elif args.cmd == "mister-read":
        return cmd_mister_read(args)
    elif args.cmd == "mister-helper":
        return cmd_mister_helper(args)
    elif args.cmd == "mister-run":
        return cmd_mister_run(args)
    elif args.cmd == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
