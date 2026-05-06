"""CLI entry point for the bridge.

Usage:
  python -m bridge_cli run --mode tloz_all --port COM3 --code mycode \
                            [--relay 129.158.62.225] [--relay-port 9999]
                            [--force-send]
  python -m bridge_cli patch <input.nes> -o <output.nes>
  python -m bridge_cli read --port COM3 --addr 0x0657 --length 16
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
from bridge_core.pipe_client import PipeClient
from bridge_core.status_sink import ConsoleStatusSink
from bridge_core.sync_engine import SyncEngine

POLL_HZ = 10
POLL_PERIOD = 1.0 / POLL_HZ


def cmd_patch(args: argparse.Namespace) -> int:
    src = Path(args.input).read_bytes()
    patch_path = Path(__file__).parent.parent / "bridge_core" / "patches" / "zelda_cc.ips"
    patch_bytes = patch_path.read_bytes()
    if ips.is_patched(src, patch_bytes):
        print(f"Already patched: {args.input}")
        if args.output:
            Path(args.output).write_bytes(src)
        return 0
    out = ips.apply(src, patch_bytes)
    out_path = args.output or args.input.replace(".nes", "_CC.nes")
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


def cmd_run(args: argparse.Namespace) -> int:
    sink = ConsoleStatusSink()
    sink.log(f"Loading mode: {args.mode}")
    mode = import_module(f"bridge_core.modes.{args.mode}")

    sink.log(f"Opening serial port {args.port} @ {args.baud}")
    sp = serial.Serial(args.port, baudrate=args.baud, timeout=0)
    cc = CCClient(sp)

    sink.log(f"Connecting to relay {args.relay}:{args.relay_port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((args.relay, args.relay_port))
    sock.setblocking(False)

    peer_id = uuid.uuid4().hex
    pipe = PipeClient(socket=sock, code=args.code, peer_id=peer_id)
    pipe._reconnect_enabled = True

    engine = SyncEngine(cc_client=cc, mode=mode)
    if args.force_send:
        engine.force_send = True
        sink.log("force_send enabled")

    pipe.on_data = lambda body: _on_data(engine, sink, body)
    pipe.on_abort = lambda reason: sink.message(f"Partner aborted: {reason}")
    pipe.on_partner_reconnected = lambda: engine.resync()
    pipe.send_join()

    # App-level hello (after pipe ESTABLISHED)
    app_hello_sent = False
    sink.state("CONNECTING")

    try:
        while pipe.state not in ("FAILED", "CLOSED"):
            loop_start = time.monotonic()

            pipe.tick()
            pipe.heartbeat_tick()

            if pipe.state == "ESTABLISHED" and not app_hello_sent:
                pipe.send_data({"op": "hello", "guid": mode.GUID, "version": "0.1.0"})
                app_hello_sent = True
                sink.state("ESTABLISHED")

            if pipe.state == "ESTABLISHED":
                # Poll the mode's READ_RANGES via Action 0x01 (ArrayRead).
                # Much lighter on the cart's main-loop than scattered reads.
                full_snapshot = cc.read_ranges(mode.READ_RANGES, timeout_ms=300)
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
    elif args.cmd == "run":
        return cmd_run(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
