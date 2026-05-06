"""ROM Setup screen: pick a ROM, optionally apply CC patch, optionally upload to EDN8."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from bridge_core import ips


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
                 "We'll apply the CC patch if it's not already patched.",
            justify="center",
        ).pack(pady=(0, 20))

        self._file_label = ctk.CTkLabel(self, text="(no file selected)", wraplength=500)
        self._file_label.pack(pady=10)

        ctk.CTkButton(self, text="Browse...", command=self._pick_file).pack(pady=10)

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
                text="ROM is not patched. Will save as <name>_CC.nes when you click Continue.",
                text_color="gray",
            )
            self._patched_path = None
        self._continue_btn.configure(state="normal")

    def _continue(self) -> None:
        assert self._rom_path is not None
        rom_bytes = self._rom_path.read_bytes()
        patch_bytes = self._load_patch()
        if not ips.is_patched(rom_bytes, patch_bytes):
            patched = ips.apply(rom_bytes, patch_bytes)
            out_path = self._rom_path.with_name(self._rom_path.stem + "_CC.nes")
            out_path.write_bytes(patched)
            self._patched_path = out_path
            self._status_label.configure(
                text=f"✓ Patched and saved: {out_path.name}", text_color="green"
            )
        # Stash the patched path on the controller for later screens
        self.controller.patched_rom_path = self._patched_path
        self.controller.show_screen("relay_setup")

    @staticmethod
    def _load_patch() -> bytes:
        path = files("bridge_core").joinpath("patches/zelda_cc.ips")
        return path.read_bytes()
