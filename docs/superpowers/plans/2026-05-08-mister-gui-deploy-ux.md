# MiSTer GUI Deploy UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-run MiSTer user experience to the PC bridge: choose hardware type, run a hardware-aware ROM/setup step, deploy missing MiSTer assets over bundled Python SSH support, start `mister-helper`, then run normal emu-coop mode/relay sync.

**Architecture:** Keep EDN8 behavior unchanged and add MiSTer as a parallel endpoint path. The PC bridge owns UX, relay, mode selection, and session loop; MiSTer receives only the custom NES core `.rbf` plus a small helper payload. Deployment uses Paramiko for SSH commands and SFTP upload, with a simple shell fallback if SFTP is unavailable.

**Tech Stack:** Python 3.10+, CustomTkinter, Paramiko, PyInstaller, existing `bridge_core.mister_*` endpoint modules, pytest with faked SSH/SFTP clients, live MiSTer smoke test at the end.

---

## File Structure

- `bridge/pyproject.toml`  
  Add `paramiko` to runtime dependencies.

- `bridge/bridge.spec`  
  Bundle Paramiko/cryptography dependencies and MiSTer payload data.

- `bridge/bridge_core/mister_deploy.py`  
  New testable deploy service around Paramiko. Owns SSH connect, remote command execution, SFTP upload, remote file detection, SHA-256 comparison, helper restart, and readiness checks.

- `bridge/bridge_core/mister_payload/manifest.json`  
  New payload manifest with helper/core filenames, versions, remote paths, standard ROM staging directory, and helper command template.

- `bridge/bridge_core/mister_payload/mister-helper.py`  
  New standalone MiSTer-side helper script. It should use only Python stdlib and `/dev/mem`, so MiSTer does not need the full PC bridge package or GUI dependencies.

- `bridge/bridge_core/mister_payload/NES_emu-coop.rbf`
  Custom odelot NES core build artifact. This can be added after the Quartus build exists. Until then, deploy should surface “core asset missing locally” instead of pretending deployment succeeded.

- `bridge/bridge_core/user_settings.py`  
  New small JSON settings store. Remember MiSTer host/IP between sessions. Do not persist the password.

- `bridge/bridge_gui/device_select_screen.py`  
  New intro screen: `EverDrive Pro N8` or `MiSTer`.

- `bridge/bridge_gui/setup_screen.py`  
  Make the existing ROM setup screen hardware-aware. EDN8 keeps the current patch/upload flow. MiSTer selects the source ROM without patching, collects MiSTer SSH settings, deploys core/helper, and starts `mister-helper`.

- `bridge/bridge_gui/app.py`  
  Register new screens and start on `device_select`.

- `bridge/bridge_gui/relay_setup_screen.py`  
  Make relay setup device-aware. EDN8 keeps COM-port controls. MiSTer hides COM-port controls and carries MiSTer helper host/port into `session_config`.

- `bridge/bridge_gui/session_worker.py`  
  Support `endpoint_type = "edn8"` and `endpoint_type = "mister"`. EDN8 uses `CCMemoryEndpoint`; MiSTer uses `MisterHelperMemoryEndpoint` and write-capable sync.

- `bridge/bridge_cli/__main__.py`  
  Add optional `mister-deploy` command for diagnostics and hardware bring-up outside the GUI.

- Tests:
  - `bridge/tests/test_mister_deploy.py`
  - `bridge/tests/test_user_settings.py`
  - `bridge/tests/test_mister_payload.py`
  - `bridge/tests/test_gui_device_flow.py`
  - `bridge/tests/test_session_worker_mister.py`
  - update `bridge/tests/test_mister_cli.py`

---

### Task 1: Paramiko Dependency and Deploy Service

**Files:**
- Modify: `bridge/pyproject.toml`
- Create: `bridge/bridge_core/mister_deploy.py`
- Test: `bridge/tests/test_mister_deploy.py`

- [ ] **Step 1: Write failing deploy service tests**

Create fake Paramiko clients and assert the desired deploy behavior without opening a real network connection.

Required tests:

```python
def test_connect_uses_password_defaults_and_auto_add_host_key_policy():
    # Given host="192.168.1.50", username="root", password="1"
    # MisterDeployService.connect() should call SSHClient.connect with those values.
```

```python
def test_upload_skips_remote_file_when_hash_matches():
    # Fake remote sha256sum returns the local hash.
    # ensure_file() should not call sftp.put().
```

```python
def test_uploads_remote_file_when_missing_or_hash_differs():
    # Fake remote test command says file is missing or hash differs.
    # ensure_file() should mkdir parent dir and upload.
```

```python
def test_restart_helper_uses_nohup_and_existing_helper_port():
    # restart_helper() should pkill old helper, start new helper in background,
    # then probe helper TCP readiness.
```

```python
def test_sftp_fallback_uploads_with_base64_cat_when_open_sftp_fails():
    # If open_sftp raises, fallback should write via remote shell using base64.
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_deploy.py -v
```

Expected: FAIL because `bridge_core.mister_deploy` does not exist.

- [ ] **Step 3: Add dependency**

Modify `bridge/pyproject.toml`:

```toml
dependencies = [
  "pyserial>=3.5",
  "customtkinter>=5.2",
  "paramiko>=3.5",
]
```

- [ ] **Step 4: Implement deploy service**

Add `bridge_core/mister_deploy.py` with these public types:

```python
@dataclass(frozen=True)
class MisterSshConfig:
    host: str
    username: str = "root"
    password: str = "1"
    port: int = 22
    timeout_s: float = 8.0


@dataclass(frozen=True)
class DeployAsset:
    local_path: Path
    remote_path: str
    executable: bool = False


@dataclass(frozen=True)
class DeployEvent:
    level: str
    message: str


class MisterDeployService:
    def connect(self) -> None: ...
    def run(self, command: str, timeout_s: float = 10.0) -> tuple[int, str, str]: ...
    def remote_exists(self, remote_path: str) -> bool: ...
    def remote_sha256(self, remote_path: str) -> str | None: ...
    def ensure_file(self, asset: DeployAsset) -> bool: ...
    def ensure_python3(self) -> bool: ...
    def stage_rom(self, local_rom_path: Path, remote_rom_dir: str) -> str: ...
    def restart_helper(self, remote_helper_path: str, port: int = 55355) -> None: ...
    def deploy(self, assets: list[DeployAsset]) -> None: ...
    def close(self) -> None: ...
```

Implementation rules:

- Use `paramiko.SSHClient`.
- Use `set_missing_host_key_policy(paramiko.AutoAddPolicy())` for the POC.
- Use SFTP for normal uploads.
- Use `shlex.quote()` for every remote path inserted into shell commands.
- Stage MiSTer ROMs under `/media/fat/games/NES/emu-coop-plus/`, mirroring the EDN8 `sd:\emu-coop-plus\` convention without patching the ROM.
- Remote helper start command:

```sh
pkill -f 'emu-coop.*mister-helper.py' || true
nohup python3 /media/fat/Scripts/emu-coop/mister-helper.py --enable-writes --host 0.0.0.0 --port 55355 >/media/fat/Scripts/emu-coop/mister-helper.log 2>&1 &
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_deploy.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add bridge/pyproject.toml bridge/bridge_core/mister_deploy.py bridge/tests/test_mister_deploy.py
git commit -m "feat(bridge): add MiSTer SSH deploy service"
```

### Task 2: MiSTer Payload Assets

**Files:**
- Create: `bridge/bridge_core/mister_payload/manifest.json`
- Create: `bridge/bridge_core/mister_payload/mister-helper.py`
- Modify: `bridge/pyproject.toml`
- Modify: `bridge/bridge.spec`
- Test: `bridge/tests/test_mister_payload.py`

- [ ] **Step 1: Write failing payload tests**

Required tests:

```python
def test_payload_manifest_loads_helper_metadata():
    # manifest has helper filename, version, remote dir, remote command, helper port.
```

```python
def test_payload_helper_script_is_stdlib_only():
    # Parse AST imports and reject customtkinter, serial, paramiko, bridge_gui.
```

```python
def test_payload_helper_script_has_cli_help():
    # Run script with --help and assert exit 0.
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_payload.py -v
```

Expected: FAIL because payload files do not exist.

- [ ] **Step 3: Create payload manifest**

Create `bridge/bridge_core/mister_payload/manifest.json`:

```json
{
  "helper": {
    "filename": "mister-helper.py",
    "version": "0.1.0",
    "remote_path": "/media/fat/Scripts/emu-coop/mister-helper.py",
    "log_path": "/media/fat/Scripts/emu-coop/mister-helper.log",
    "port": 55355
  },
  "roms": {
    "remote_dir": "/media/fat/games/NES/emu-coop-plus"
  },
  "core": {
    "filename": "NES_emu-coop.rbf",
    "version": "0.1.0",
    "remote_path": "/media/fat/_Console/NES_emu-coop.rbf",
    "required": true
  }
}
```

- [ ] **Step 4: Create standalone helper**

Create `bridge/bridge_core/mister_payload/mister-helper.py` as a stdlib-only helper. It should:

- mmap `/dev/mem` at `0x3D000000`
- implement odelot smart-cache reads:
  - write requested addresses at byte offset `0x40000`
  - read response at byte offset `0x48000`
- implement emu-coop write mailbox:
  - write pairs at byte offset `0x58008`
  - write control at byte offset `0x58000`
  - wait for ack sequence
- expose JSON-line TCP ops:
  - `read_ranges`
  - `read_byte`
  - `write_pairs`
- accept:

```sh
python3 mister-helper.py --host 0.0.0.0 --port 55355 --enable-writes
```

- [ ] **Step 5: Include payload in packaging**

Modify `bridge/pyproject.toml` package data:

```toml
[tool.setuptools.package-data]
"bridge_core" = [
  "patches/*.ips",
  "patches/*.json",
  "mister_payload/*",
]
```

Modify `bridge/bridge.spec` `datas`:

```python
('bridge_core/mister_payload/manifest.json', 'bridge_core/mister_payload'),
('bridge_core/mister_payload/mister-helper.py', 'bridge_core/mister_payload'),
('bridge_core/mister_payload/NES_emu-coop.rbf', 'bridge_core/mister_payload'),
```

If `NES_emu-coop.rbf` does not exist yet, do not add the spec entry until the artifact exists; instead have deploy report a blocking “core asset missing” status.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_payload.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add bridge/bridge_core/mister_payload bridge/pyproject.toml bridge/bridge.spec bridge/tests/test_mister_payload.py
git commit -m "feat(bridge): add MiSTer helper payload"
```

### Task 3: Remember MiSTer Host/IP

**Files:**
- Create: `bridge/bridge_core/user_settings.py`
- Test: `bridge/tests/test_user_settings.py`

- [ ] **Step 1: Write failing settings tests**

Required tests:

```python
def test_settings_default_mister_username_and_password():
    settings = UserSettings.load(path)
    assert settings.mister_username == "root"
    assert settings.mister_password_default == "1"
```

```python
def test_settings_remembers_mister_host_but_not_password():
    settings.mister_host = "192.168.1.50"
    settings.mister_password = "secret"
    settings.save()
    raw = path.read_text()
    assert "192.168.1.50" in raw
    assert "secret" not in raw
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_user_settings.py -v
```

Expected: FAIL because settings module does not exist.

- [ ] **Step 3: Implement settings store**

Use JSON under:

```text
%LOCALAPPDATA%\emu-coop-plus\bridge-settings.json
```

Public API:

```python
class UserSettings:
    mister_host: str
    mister_username: str

    @classmethod
    def load(cls, path: Path | None = None) -> "UserSettings": ...
    def save(self) -> None: ...
```

Rules:

- Default host: `""`
- Default username: `"root"`
- Password is not persisted.
- GUI password field always defaults to `"1"` when the screen opens.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_user_settings.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add bridge/bridge_core/user_settings.py bridge/tests/test_user_settings.py
git commit -m "feat(bridge): remember MiSTer host settings"
```

### Task 4: Device Selection and MiSTer Setup GUI

**Files:**
- Create: `bridge/bridge_gui/device_select_screen.py`
- Create: `bridge/bridge_gui/device_flow.py`
- Modify: `bridge/bridge_gui/app.py`
- Modify: `bridge/bridge_gui/setup_screen.py`
- Test: `bridge/tests/test_gui_device_flow.py`

- [ ] **Step 1: Write failing pure flow tests**

Avoid requiring a display server in tests by putting config-building logic in `device_flow.py`.

Required tests:

```python
def test_edn8_device_selection_routes_to_rom_setup():
    assert next_screen_for_device("edn8") == "rom_setup"
```

```python
def test_mister_device_selection_routes_to_rom_setup():
    assert next_screen_for_device("mister") == "rom_setup"
```

```python
def test_mister_setup_config_uses_defaults_and_remembered_host():
    config = build_mister_rom_setup_config(
        rom_path="zelda.nes",
        host="192.168.1.50",
        username="",
        password="",
    )
    assert config["rom_path"] == "zelda.nes"
    assert config["mister_host"] == "192.168.1.50"
    assert config["mister_username"] == "root"
    assert config["mister_password"] == "1"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_gui_device_flow.py -v
```

Expected: FAIL because GUI flow helper does not exist.

- [ ] **Step 3: Implement pure device flow helpers**

Create `bridge_gui/device_flow.py`:

```python
AVAILABLE_DEVICES = ["edn8", "mister"]

def next_screen_for_device(device: str) -> str:
    if device == "edn8":
        return "rom_setup"
    if device == "mister":
        return "rom_setup"
    raise ValueError(f"unknown device: {device}")

def build_mister_rom_setup_config(rom_path: str, host: str, username: str, password: str) -> dict:
    return {
        "endpoint_type": "mister",
        "rom_path": rom_path,
        "mister_host": host.strip(),
        "mister_username": username.strip() or "root",
        "mister_password": password or "1",
        "mister_port": 55355,
        "enable_writes": True,
    }
```

- [ ] **Step 4: Add device selection screen**

Create `DeviceSelectScreen`:

- Title: `Choose Device`
- Two buttons:
  - `EverDrive Pro N8`
  - `MiSTer`
- EDN8 button sets `controller.endpoint_type = "edn8"` and routes to `rom_setup`.
- MiSTer button sets `controller.endpoint_type = "mister"` and routes to `rom_setup`.

- [ ] **Step 5: Make ROM setup screen hardware-aware**

Modify `ROMSetupScreen` so `on_show()` checks `controller.endpoint_type`.

EDN8 mode keeps the current behavior:

- choose Z1 ROM
- validate NES header
- apply CC IPS patch when needed
- optionally upload and auto-launch through EDN8
- Continue routes to relay setup

MiSTer mode changes the same screen into a MiSTer source ROM/setup step:

- Title: `MiSTer Setup`
- ROM picker text: choose the Zelda 1 source ROM; no CC patch is applied
- selected ROM is uploaded to `/media/fat/games/NES/emu-coop-plus/`
- Host/IP entry:
  - blank first run
  - remembered value on later runs
- Username entry default: `root`
- Password entry default: `1`
- Button: `Test & Deploy`
- Status log textbox
- Continue button disabled until ROM is selected and deploy succeeds

On MiSTer deploy:

- run `MisterDeployService` in a background thread
- emit progress to the UI
- save host/username after successful SSH connection
- on success stash:

```python
controller.mister_config = {
    "endpoint_type": "mister",
    "rom_path": str(selected_rom_path),
    "mister_remote_rom_path": "/media/fat/games/NES/emu-coop-plus/<rom filename>",
    "mister_host": host,
    "mister_port": 55355,
    "enable_writes": True,
}
```

Then enable Continue.

- [ ] **Step 6: Register device selection and start there**

Modify `bridge_gui/app.py`:

```python
self.show_screen("device_select")
```

Register:

```python
self._screens["device_select"] = DeviceSelectScreen(...)
```

- [ ] **Step 7: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_gui_device_flow.py -v
```

Expected: PASS.

- [ ] **Step 8: Manual GUI smoke**

Run:

```powershell
cd bridge
uv run python -m bridge_gui
```

Expected:

- app opens to Choose Device
- EDN8 routes to the existing ROM setup screen
- MiSTer routes to the same ROM setup screen in MiSTer mode

- [ ] **Step 9: Commit**

```powershell
git add bridge/bridge_gui/device_select_screen.py bridge/bridge_gui/device_flow.py bridge/bridge_gui/app.py bridge/bridge_gui/setup_screen.py bridge/tests/test_gui_device_flow.py
git commit -m "feat(gui): add device selection and MiSTer ROM setup"
```

### Task 5: Device-Aware Relay Setup

**Files:**
- Modify: `bridge/bridge_gui/relay_setup_screen.py`
- Test: `bridge/tests/test_gui_device_flow.py`

- [ ] **Step 1: Write failing relay config tests**

Add pure helper tests for relay/session config creation:

```python
def test_edn8_relay_config_includes_com_port_and_force_send():
    config = build_session_config(endpoint_type="edn8", ...)
    assert config["endpoint_type"] == "edn8"
    assert config["com_port"] == "COM5"
```

```python
def test_mister_relay_config_omits_com_port_and_keeps_helper_host():
    config = build_session_config(endpoint_type="mister", mister_config={...}, ...)
    assert config["endpoint_type"] == "mister"
    assert config["mister_host"] == "192.168.1.50"
    assert "com_port" not in config
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_gui_device_flow.py -v
```

Expected: FAIL until helper exists.

- [ ] **Step 3: Extract session config builder**

Move config-building logic out of `RelaySetupScreen._connect()` into `bridge_gui/device_flow.py`:

```python
def build_session_config(
    *,
    endpoint_type: str,
    mode: str,
    relay: str,
    relay_port: int,
    code: str,
    com_port: str | None = None,
    force_send: bool = False,
    mister_config: dict | None = None,
) -> dict: ...
```

- [ ] **Step 4: Make relay setup screen device-aware**

Rules:

- EDN8:
  - show COM-port dropdown
  - show force-send checkbox
  - validate COM port and session code
- MiSTer:
  - hide COM-port dropdown or disable it with a clear “MiSTer helper already configured” status
  - default force-send off but allow it if useful
  - validate session code and MiSTer config exists
  - carry `mister_host`, `mister_port`, and `enable_writes=True` into `session_config`

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_gui_device_flow.py -v
```

Expected: PASS.

- [ ] **Step 6: Manual GUI smoke**

Run:

```powershell
cd bridge
uv run python -m bridge_gui
```

Expected:

- EDN8 path shows ROM patching/upload, then relay/mode/session setup with COM selection.
- MiSTer path shows source ROM selection plus MiSTer deploy, then relay/mode/session setup with no COM requirement.

- [ ] **Step 7: Commit**

```powershell
git add bridge/bridge_gui/relay_setup_screen.py bridge/bridge_gui/device_flow.py bridge/tests/test_gui_device_flow.py
git commit -m "feat(gui): make relay setup device-aware"
```

### Task 6: Session Worker MiSTer Endpoint

**Files:**
- Modify: `bridge/bridge_gui/session_worker.py`
- Test: `bridge/tests/test_session_worker_mister.py`

- [ ] **Step 1: Write failing session worker tests**

Use monkeypatches/fakes; do not open real sockets.

Required tests:

```python
def test_session_worker_uses_edn8_endpoint_for_edn8_config():
    # endpoint_type="edn8" should instantiate serial.Serial, CCClient, CCMemoryEndpoint.
```

```python
def test_session_worker_uses_mister_endpoint_for_mister_config():
    # endpoint_type="mister" should instantiate MisterHelperMemoryEndpoint(host, port)
    # and should not touch serial.Serial.
```

```python
def test_mister_session_applies_incoming_writes():
    # Incoming relay data should call endpoint.write_pairs through SyncEngine.
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_session_worker_mister.py -v
```

Expected: FAIL because worker only knows EDN8.

- [ ] **Step 3: Refactor endpoint creation**

In `SessionWorker`, add:

```python
def _open_endpoint(self, cfg: dict):
    if cfg.get("endpoint_type", "edn8") == "edn8":
        ...
    if cfg["endpoint_type"] == "mister":
        return MisterHelperMemoryEndpoint(
            host=cfg["mister_host"],
            port=cfg.get("mister_port", 55355),
            timeout=cfg.get("mister_timeout", 1.0),
        )
```

Keep the polling/diff/apply loop shared through `SyncEngine`.

- [ ] **Step 4: Add MiSTer readiness events**

Emit events:

- `device_connection`: helper connected / disconnected
- `cart_game`: game running / not running, same as EDN8
- `net_relay`
- `net_partner`

For a narrow first pass, map `device_connection` to the existing cart USB label if changing `SessionScreen` would be too large.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_session_worker_mister.py tests/test_sync_session.py tests/test_mister_helper.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add bridge/bridge_gui/session_worker.py bridge/tests/test_session_worker_mister.py
git commit -m "feat(gui): run sessions against MiSTer helper"
```

### Task 7: CLI Deploy Command

**Files:**
- Modify: `bridge/bridge_cli/__main__.py`
- Test: `bridge/tests/test_mister_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests:

```python
def test_mister_deploy_cli_passes_ssh_defaults():
    rc = cli.main(["mister-deploy", "--host", "192.168.1.50"])
    # fake deploy service sees username root and password 1
```

```python
def test_mister_deploy_cli_accepts_custom_username_password():
    rc = cli.main(["mister-deploy", "--host", "...", "--username", "...", "--password", "..."])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_cli.py -v
```

Expected: FAIL until CLI command exists.

- [ ] **Step 3: Implement command**

Add:

```powershell
python -m bridge_cli mister-deploy --host 192.168.1.50 --username root --password 1
```

It should:

- connect over SSH
- deploy payload/core if available
- restart helper
- print progress
- return non-zero if local core asset is missing

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd bridge
uv run python -m pytest tests/test_mister_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add bridge/bridge_cli/__main__.py bridge/tests/test_mister_cli.py
git commit -m "feat(cli): add MiSTer deploy command"
```

### Task 8: Build and Package

**Files:**
- Modify: `bridge/bridge.spec`
- Modify: `bridge/README.md`
- Modify: `bridge/build-edn8.ps1` if the build name should change from EDN8-only language

- [ ] **Step 1: Verify dependency lock**

Run:

```powershell
cd bridge
uv sync --extra test --extra dist
```

Expected: lockfile updates with Paramiko and dependencies.

- [ ] **Step 2: Run full tests**

Run:

```powershell
cd bridge
uv run python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Build app**

Run:

```powershell
cd bridge
powershell -ExecutionPolicy Bypass -File .\build-edn8.ps1
```

Expected: `bridge/dist/bridge.exe` builds successfully. If the script name is misleading, rename in a follow-up commit after confirming no release automation depends on it.

- [ ] **Step 4: Smoke packaged app**

Run:

```powershell
bridge\dist\bridge.exe
```

Expected:

- choose device screen appears
- EDN8 path still opens ROM patch flow
- MiSTer path opens SSH deploy flow

- [ ] **Step 5: Commit**

```powershell
git add bridge/pyproject.toml bridge/uv.lock bridge/bridge.spec bridge/README.md bridge/build-edn8.ps1
git commit -m "build(bridge): package MiSTer deploy support"
```

### Task 9: Live MiSTer Validation

**Files:**
- No code changes unless smoke reveals a bug.
- Update docs if setup behavior differs from plan.

- [ ] **Step 1: Confirm custom core artifact exists**

From the odelot core branch `emu-coop-ddram-mailbox-poc`, build the `.rbf` and place it at:

```text
bridge/bridge_core/mister_payload/NES_emu-coop.rbf
```

Expected: deploy service can find the local core asset.

- [ ] **Step 2: CLI deploy smoke against your MiSTer**

Run:

```powershell
cd bridge
uv run python -m bridge_cli mister-deploy --host <YOUR_MISTER_IP>
```

Defaults:

- username: `root`
- password: `1`

Expected:

- SSH connects
- `/media/fat/Scripts/emu-coop/mister-helper.py` exists or is uploaded
- `/media/fat/_Console/NES_emu-coop.rbf` exists or is uploaded
- selected ROM exists under `/media/fat/games/NES/emu-coop-plus/`
- helper is restarted
- helper TCP port `55355` is reachable

- [ ] **Step 3: GUI deploy smoke**

Run:

```powershell
cd bridge
uv run python -m bridge_gui
```

Flow:

1. Choose `MiSTer`
2. Choose your Zelda 1 source ROM
3. Enter your MiSTer IP
4. Keep username `root`
5. Keep password `1`
6. Click `Test & Deploy`

Expected:

- progress log shows deploy steps
- host is remembered after success
- Continue becomes enabled

- [ ] **Step 4: Helper read diagnostic**

Run:

```powershell
cd bridge
uv run python -m bridge_cli mister-run --mode tloz_all --mister-host <YOUR_MISTER_IP> --code test123 --enable-writes
```

Expected:

- PC bridge connects to helper
- relay connection starts
- while Zelda is running, game-running state is detected from `$0012`

- [ ] **Step 5: One-byte write diagnostic**

Add a temporary CLI diagnostic if needed:

```powershell
uv run python -m bridge_cli mister-write --mister-host <YOUR_MISTER_IP> --addr 0x0657 --value 0x01
```

Expected:

- helper returns `ok`
- next read of `$0657` returns `01`

- [ ] **Step 6: End-to-end session smoke**

Run one peer as FCEUX or EDN8 and the MiSTer peer through the GUI.

Use mode:

```text
tloz_all
```

Expected:

- MiSTer local pickup sends outward
- incoming peer pickup applies to MiSTer
- item messages show in PC bridge
- reconnect still works

- [ ] **Step 7: Commit docs updates**

```powershell
git add bridge/README.md bridge/docs/mister-port-plan.md
git commit -m "docs(bridge): document MiSTer GUI deploy flow"
```

## Execution Notes

- The first implementation should not store the root password. Default it to `1` in the UI every time.
- The host/IP should be blank on first launch and remembered after successful deploy.
- Use Paramiko SFTP first. Add SCP only if MiSTer’s SSH server lacks SFTP in practice.
- Keep EDN8 behavior stable. Every GUI and worker change should be tested against EDN8 config as well as MiSTer config.
- If MiSTer lacks `python3`, stop the deploy flow with a clear error. A compiled helper binary can be a follow-up milestone after the Python helper proves the full path.
- Do not overwrite the stock upstream `NES.rbf`. Deploy the POC core as `NES_emu-coop.rbf`.
