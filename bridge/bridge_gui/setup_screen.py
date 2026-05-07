"""ROM Setup screen: pick a ROM, apply emu-coop-plus patch, optionally upload to EDN8."""
from __future__ import annotations

import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from bridge_core import ips


# Where to copy the patched ROM on the EDN8 SD card (auto-created by edlink-n8)
EDN8_TARGET_DIR = "sd:\\emu-coop-plus\\"


class ROMSetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        self._rom_path: Path | None = None
        self._patched_path: Path | None = None

        ctk.CTkLabel(
            self,
            text="ROM Setup",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            self,
            text="Choose your Z1 ROM (vanilla or Z1R seed).\n"
                 "We'll apply the emu-coop-plus patch if it's not already patched.",
            justify="center",
        ).pack(pady=(0, 20))

        self._file_label = ctk.CTkLabel(self, text="(no file selected)", wraplength=500)
        self._file_label.pack(pady=10)

        ctk.CTkButton(self, text="Browse...", command=self._pick_file).pack(pady=10)

        # Upload to EDN8 SD card via edlink-n8.exe (auto-detected; default ON if found)
        edlink_present = self._edlink_path() is not None
        self._upload_var = ctk.BooleanVar(value=edlink_present)
        self._upload_check = ctk.CTkCheckBox(
            self,
            text=f"Also upload patched ROM to EDN8 ({EDN8_TARGET_DIR})",
            variable=self._upload_var,
            state="normal" if edlink_present else "disabled",
        )
        self._upload_check.pack(pady=8)
        if not edlink_present:
            ctk.CTkLabel(
                self,
                text="(edlink-n8.exe not found in bridge/tools/ or PATH; upload disabled)",
                text_color="gray",
                font=ctk.CTkFont(size=10),
            ).pack()

        self._status_label = ctk.CTkLabel(self, text="", wraplength=500, text_color="gray")
        self._status_label.pack(pady=10)

        self._continue_btn = ctk.CTkButton(
            self,
            text="Continue",
            state="disabled",
            command=self._continue,
        )
        self._continue_btn.pack(pady=20)

    def _pick_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Choose Z1 ROM",
            filetypes=[("NES ROMs", "*.nes"), ("All files", "*.*")],
        )
        if not filename:
            return
        self._rom_path = Path(filename)
        self._file_label.configure(text=str(self._rom_path))
        self._inspect_rom()

    def _inspect_rom(self) -> None:
        assert self._rom_path is not None
        try:
            rom_bytes = self._rom_path.read_bytes()
        except OSError as e:
            self._status_label.configure(text=f"Error reading file: {e}", text_color="red")
            self._continue_btn.configure(state="disabled")
            return
        if len(rom_bytes) < 16 or rom_bytes[:4] != b"NES\x1a":
            self._status_label.configure(
                text="This doesn't look like a NES ROM (.nes header missing).",
                text_color="red",
            )
            self._continue_btn.configure(state="disabled")
            return
        patch_bytes = self._load_patch()
        if ips.is_patched(rom_bytes, patch_bytes):
            self._status_label.configure(
                text="✓ ROM is already patched. Ready.", text_color="green"
            )
            self._patched_path = self._rom_path
        else:
            self._status_label.configure(
                text="ROM is not patched. Will save as <name>_emucoop.nes when you click Continue.",
                text_color="gray",
            )
            self._patched_path = None
        self._continue_btn.configure(state="normal")

    def _continue(self) -> None:
        assert self._rom_path is not None
        rom_bytes = self._rom_path.read_bytes()
        patch_bytes = self._load_patch()
        if not ips.is_patched(rom_bytes, patch_bytes):
            try:
                expected = ips.load_expected_manifest(self._load_manifest())
                patched = ips.apply_validated(rom_bytes, patch_bytes, expected)
            except ips.RomConflict as exc:
                offsets = ", ".join(f"0x{o:06X}" for o, _, _ in exc.mismatches[:6])
                more = f" (+{len(exc.mismatches) - 6} more)" if len(exc.mismatches) > 6 else ""
                self._status_label.configure(
                    text=(
                        f"✗ ROM modified at {len(exc.mismatches)} patch site(s) "
                        f"({offsets}{more}). If this is a randomizer seed, "
                        f"please report the flagstring."
                    ),
                    text_color="red",
                )
                return
            out_path = self._rom_path.with_name(self._rom_path.stem + "_emucoop.nes")
            out_path.write_bytes(patched)
            self._patched_path = out_path
            self._status_label.configure(
                text=f"✓ Patched and saved: {out_path.name}", text_color="green"
            )
        # Optionally upload to EDN8 via edlink-n8.exe
        if self._upload_var.get() and self._patched_path is not None:
            self._upload_to_edn8(self._patched_path)
        # Stash the patched path on the controller for later screens
        self.controller.patched_rom_path = self._patched_path
        self.controller.show_screen("relay_setup")

    def _upload_to_edn8(self, file_path: Path) -> None:
        """Push the patched ROM to the EDN8's SD card via edlink-n8.exe.
        First ensures the target folder exists (mkdir is idempotent), then copies."""
        edlink = self._edlink_path()
        if edlink is None:
            self._status_label.configure(
                text="(edlink-n8.exe not found; skipping upload)",
                text_color="orange",
            )
            return
        # edlink target dir without the trailing slash for -mkdir
        target_dir_arg = EDN8_TARGET_DIR.rstrip("\\")
        try:
            mkdir_result = subprocess.run(
                [str(edlink), "-mkdir", target_dir_arg],
                capture_output=True, text=True, timeout=15,
            )
            if mkdir_result.returncode != 0:
                err = (mkdir_result.stderr or mkdir_result.stdout or "(no output)").strip()[:300]
                self._status_label.configure(
                    text=f"Could not create {target_dir_arg} (rc={mkdir_result.returncode}): {err}",
                    text_color="red",
                )
                return
            cp_result = subprocess.run(
                [str(edlink), "-cp", str(file_path), EDN8_TARGET_DIR],
                capture_output=True, text=True, timeout=30,
            )
            if cp_result.returncode != 0:
                err = (cp_result.stderr or cp_result.stdout or "(no output)").strip()[:300]
                self._status_label.configure(
                    text=f"Upload failed (rc={cp_result.returncode}): {err}",
                    text_color="red",
                )
            else:
                self._status_label.configure(
                    text=f"✓ Patched, saved, and uploaded to {EDN8_TARGET_DIR}{file_path.name}",
                    text_color="green",
                )
        except Exception as e:
            self._status_label.configure(text=f"Upload error: {e}", text_color="red")

    @staticmethod
    def _edlink_path() -> Path | None:
        """Find edlink-n8.exe: PyInstaller bundle, source bridge/tools/, then PATH."""
        # PyInstaller bundle: datas extract under sys._MEIPASS
        if hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "tools" / "edlink-n8.exe"
            if bundled.is_file():
                return bundled
        # Source layout: bridge/tools/edlink-n8.exe
        bundled = Path(__file__).parent.parent / "tools" / "edlink-n8.exe"
        if bundled.is_file():
            return bundled
        # System PATH
        which = shutil.which("edlink-n8.exe") or shutil.which("edlink-n8")
        return Path(which) if which else None

    @staticmethod
    def _load_patch() -> bytes:
        path = files("bridge_core").joinpath("patches/zelda_emu_coop_plus.ips")
        return path.read_bytes()

    @staticmethod
    def _load_manifest() -> bytes:
        path = files("bridge_core").joinpath("patches/zelda_emu_coop_plus.expected.json")
        return path.read_bytes()
