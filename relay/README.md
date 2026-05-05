# emu-coop relay

Small Python asyncio TCP server that pairs emu-coop peers by session code and forwards frames between them. Stateless across restarts.

## Architecture

The relay is the matchmaking + forwarding component for emu-coop's `RelayPipe` transport. Each peer connects outbound to the relay, sends a `join` frame with a shared session code and a per-launch peer-id, and the relay pairs the first two peers using the same code. After pairing, the relay is a transparent byte forwarder — it never inspects gameplay traffic.

If a paired peer drops, the relay holds the surviving peer's slot for 60 seconds (configurable). If the dropped peer reconnects with the same code + peer_id within that window, the relay re-pairs them and notifies the survivor with a `partner-reconnected` frame, allowing peer-side state resync without restarting either emulator.

## Local development

```powershell
cd relay
python -m pip install -e ".[test]"
python -m relay  # listens on 0.0.0.0:9999
python -m pytest tests/ -v --timeout=15  # 6 unit tests + 1 opt-in integration
```

## Configuration (env vars)

| Variable | Default | Meaning |
|---|---|---|
| `RELAY_PORT` | `9999` | TCP listen port |
| `RELAY_MAX_PAIRS` | `100` | Max concurrent paired sessions |
| `RELAY_TTL_SECONDS` | `600` | Time the first peer can wait alone before relay closes |
| `RELAY_GRACE_SECONDS` | `60` | Time the survivor is held after partner drops |
| `RELAY_IDLE_SECONDS` | `30` | Per-connection inactivity timeout (heartbeats reset this) |

## OCI Always Free deployment

Tested on Oracle Cloud "Always Free" ARM Ampere VM (Ubuntu 22.04+).

### 1. Create the instance

- OCI Console → Compute → Instances → Create Instance
- Image: Canonical Ubuntu 22.04 (or newer)
- Shape: VM.Standard.A1.Flex (ARM/Ampere; 1 OCPU + 6 GB RAM is plenty)
- Networking: assign a public IPv4 (free)
- Add your SSH public key

### 2. Open port 9999 (TWO firewalls — both required)

**(a) OCI Security List (cloud-side):**

- VCN → Security Lists → "Default Security List" for your VCN → Ingress Rules → Add Ingress Rule
- Source CIDR: `0.0.0.0/0`
- IP Protocol: TCP
- Destination Port Range: `9999`

**(b) Ubuntu host firewall (instance-side):**

```bash
sudo ufw allow 9999/tcp
# Some Ubuntu images on OCI also need iptables tweaked because OCI's default
# image has REJECT rules from the start:
sudo iptables -I INPUT 1 -p tcp --dport 9999 -j ACCEPT
sudo netfilter-persistent save
```

Verify from your laptop: `nc -zv <vm-public-ip> 9999` should report "succeeded". (Or use `Test-NetConnection -ComputerName <vm-public-ip> -Port 9999` from PowerShell.)

### 3. Install the relay on the VM

```bash
ssh ubuntu@<vm-public-ip>

sudo apt update && sudo apt install -y python3.11 python3.11-venv git
sudo useradd -r -s /usr/sbin/nologin relay
sudo mkdir /opt/emu-coop-relay && sudo chown relay:relay /opt/emu-coop-relay

# Clone the repo (or scp just the relay/ directory)
sudo -u relay git clone https://github.com/BogieSmalls/emu-coop-z1.git /tmp/emu-coop-z1
sudo -u relay cp -r /tmp/emu-coop-z1/relay/* /opt/emu-coop-relay/

# Create venv and install
sudo -u relay python3.11 -m venv /opt/emu-coop-relay/.venv
sudo -u relay /opt/emu-coop-relay/.venv/bin/pip install -e /opt/emu-coop-relay
```

### 4. Install the systemd unit

```bash
sudo cp /opt/emu-coop-relay/deploy/relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now relay
sudo systemctl status relay
sudo journalctl -u relay -f  # tail logs
```

You should see `relay listening on 0.0.0.0:9999` in the journal.

### 5. Smoke test from a real client

In FCEUX with `coop.lua`, fill in the connection dialog:

- Transport: Relay
- Host address: `<vm-public-ip>`
- Port: `9999`
- Session code: any 6+ char string you and your partner agree on out-of-band

Both peers should pair within ~1 second. If they don't pair: check the relay's journal for the join frames arriving (or not).

### 6. Updating the relay

```bash
sudo -u relay git -C /tmp/emu-coop-z1 pull
sudo -u relay cp -r /tmp/emu-coop-z1/relay/* /opt/emu-coop-relay/
sudo -u relay /opt/emu-coop-relay/.venv/bin/pip install -e /opt/emu-coop-relay
sudo systemctl restart relay
```

## Wire protocol

Every frame is 4-byte big-endian length prefix + JSON body. Max frame size: 4 KiB.

**Peer → relay:**

| kind | shape | meaning |
|---|---|---|
| `join` | `{kind:"join", code, peer_id}` | matchmaking request |

**Relay → peer:**

| kind | shape | meaning |
|---|---|---|
| `joined` | `{kind:"joined"}` | you're paired |
| `abort` | `{kind:"abort", reason}` | session terminated; reason is human-readable |
| `partner-reconnected` | `{kind:"partner-reconnected", peer_id}` | your partner just rejoined; do hello + resync |

Once paired, all peer-to-peer frames are forwarded by the relay without inspection. The peer-to-peer protocol (hello, ping/pong, data, abort) is opaque from the relay's perspective.

## What's NOT here

- TLS — peers and relay use plain TCP. Game-sync data is uninteresting; pairing auth is via session code + peer_id. If you ever need TLS, run `stunnel` in front of the relay.
- Authentication beyond session code — see above.
- Persistence — relay is stateless across restarts. Restarting it will drop in-flight pairs; surviving peers will see "Connection lost" and auto-reconnect (re-pair) when the relay comes back.

## Troubleshooting

- **"Could not reach relay" from FCEUX:** check both firewalls (security list AND iptables/ufw). Use `nc -zv` or `Test-NetConnection` from a non-VM machine.
- **"Session code already in use":** another pair is using the same code. Pick a different one. (Codes are not reservable; first two peers to use a code get paired.)
- **"No partner showed up":** the TTL (default 600s) expired before a second peer joined. Try again.
- **Both peers "Connection lost" simultaneously:** relay process crashed and restarted. Both peers will auto-reconnect; nothing to do.
