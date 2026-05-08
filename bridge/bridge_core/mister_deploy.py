"""SSH deployment helpers for the MiSTer bridge POC."""
from __future__ import annotations

import base64
import hashlib
import posixpath
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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
    def __init__(
        self,
        config: MisterSshConfig,
        *,
        paramiko_module: Any | None = None,
        on_event: Callable[[DeployEvent], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._paramiko = paramiko_module
        self._client = None
        self._on_event = on_event
        self._sleep = sleep

    def connect(self) -> None:
        paramiko = self._paramiko
        if paramiko is None:
            import paramiko as loaded_paramiko

            paramiko = loaded_paramiko
            self._paramiko = loaded_paramiko
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self.config.host,
            port=self.config.port,
            username=self.config.username,
            password=self.config.password,
            timeout=self.config.timeout_s,
            look_for_keys=False,
            allow_agent=False,
        )
        self._emit("info", f"Connected to MiSTer at {self.config.host}")

    def run(self, command: str, timeout_s: float = 10.0) -> tuple[int, str, str]:
        client = self._require_client()
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def remote_exists(self, remote_path: str) -> bool:
        rc, _out, _err = self.run(f"test -f {shlex.quote(remote_path)} && echo exists")
        return rc == 0

    def remote_sha256(self, remote_path: str) -> str | None:
        rc, out, _err = self.run(f"sha256sum {shlex.quote(remote_path)}")
        if rc != 0:
            return None
        first = out.strip().split(maxsplit=1)[0] if out.strip() else ""
        return first or None

    def local_sha256(self, local_path: Path) -> str:
        digest = hashlib.sha256()
        with local_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def ensure_file(self, asset: DeployAsset) -> bool:
        local_path = Path(asset.local_path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        remote_path = asset.remote_path
        local_hash = self.local_sha256(local_path)
        if self.remote_exists(remote_path) and self.remote_sha256(remote_path) == local_hash:
            self._emit("info", f"Already current: {remote_path}")
            return False

        remote_dir = posixpath.dirname(remote_path)
        if remote_dir:
            self.run(f"mkdir -p {shlex.quote(remote_dir)}")
        self._upload(local_path, remote_path)
        if asset.executable:
            self.run(f"chmod +x {shlex.quote(remote_path)}")
        self._emit("info", f"Uploaded: {remote_path}")
        return True

    def ensure_python3(self) -> bool:
        rc, _out, _err = self.run("command -v python3 >/dev/null 2>&1")
        return rc == 0

    def stage_rom(self, local_rom_path: Path, remote_rom_dir: str) -> str:
        remote_path = posixpath.join(remote_rom_dir.rstrip("/"), Path(local_rom_path).name)
        self.ensure_file(DeployAsset(Path(local_rom_path), remote_path))
        return remote_path

    def restart_helper(self, remote_helper_path: str, port: int = 55355) -> None:
        helper = shlex.quote(remote_helper_path)
        helper_dir = shlex.quote(posixpath.dirname(remote_helper_path))
        log_path = shlex.quote(posixpath.join(posixpath.dirname(remote_helper_path), "mister-helper.log"))
        command = (
            "pkill -f 'emu-coop.*mister-helper.py' || true; "
            f"mkdir -p {helper_dir}; "
            f"nohup python3 {helper} --enable-writes --host 0.0.0.0 --port {int(port)} "
            f">{log_path} 2>&1 &"
        )
        self.run(command)
        for _attempt in range(20):
            rc, _out, _err = self.run(f"nc -z 127.0.0.1 {int(port)}")
            if rc == 0:
                self._emit("info", f"MiSTer helper is listening on port {port}")
                return
            self._sleep(0.25)
        raise TimeoutError(f"MiSTer helper did not start on port {port}")

    def deploy(self, assets: list[DeployAsset]) -> None:
        if not self.ensure_python3():
            raise RuntimeError("MiSTer does not have python3 on PATH")
        for asset in assets:
            self.ensure_file(asset)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _upload(self, local_path: Path, remote_path: str) -> None:
        client = self._require_client()
        try:
            sftp = client.open_sftp()
        except Exception:
            self._upload_with_base64(local_path, remote_path)
            return
        try:
            sftp.put(str(local_path), remote_path)
        finally:
            sftp.close()

    def _upload_with_base64(self, local_path: Path, remote_path: str) -> None:
        encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
        command = (
            "python3 - <<'PY'\n"
            "import base64\n"
            f"data = {encoded!r}\n"
            "open('/tmp/emucoop_upload.b64', 'w').write(data)\n"
            "PY\n"
            f"cat /tmp/emucoop_upload.b64 | base64 -d > {shlex.quote(remote_path)}; "
            "rm -f /tmp/emucoop_upload.b64"
        )
        rc, _out, err = self.run(command)
        if rc != 0:
            raise RuntimeError(f"fallback upload failed: {err.strip()}")

    def _require_client(self):
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    def _emit(self, level: str, message: str) -> None:
        if self._on_event is not None:
            self._on_event(DeployEvent(level=level, message=message))
