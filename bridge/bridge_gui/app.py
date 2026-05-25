"""CustomTkinter app shell with screen navigation."""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

WINDOW_GEOMETRY = "760x720"
WINDOW_MIN_SIZE = (700, 560)
APP_TITLE = "Z1RR-coop Bridge"
APP_ICON = Path("assets/ganon_blue.ico")


def asset_path(relative_path: Path) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative_path


class BridgeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self._set_window_icon()
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(*WINDOW_MIN_SIZE)

        self._screens: dict[str, ctk.CTkFrame] = {}
        self._current_screen: ctk.CTkFrame | None = None
        self.endpoint_type = "edn8"
        self.patched_rom_path = None
        self.mister_config = None
        self.session_config = None

        self._register_screens()
        self.show_screen("device_select")

    def _set_window_icon(self) -> None:
        try:
            self.iconbitmap(default=str(asset_path(APP_ICON)))
        except Exception:
            pass

    def _register_screens(self) -> None:
        from bridge_gui.device_select_screen import DeviceSelectScreen
        from bridge_gui.setup_screen import ROMSetupScreen
        from bridge_gui.relay_setup_screen import RelaySetupScreen
        from bridge_gui.session_screen import SessionScreen

        self._screens["device_select"] = DeviceSelectScreen(self, controller=self)
        self._screens["rom_setup"] = ROMSetupScreen(self, controller=self)
        self._screens["relay_setup"] = RelaySetupScreen(self, controller=self)
        self._screens["session"] = SessionScreen(self, controller=self)

    def show_screen(self, name: str) -> None:
        if self._current_screen is not None:
            self._current_screen.pack_forget()
        screen = self._screens[name]
        screen.pack(fill="both", expand=True, padx=20, pady=20)
        self._current_screen = screen
        # Each screen can react to becoming visible
        if hasattr(screen, "on_show"):
            screen.on_show()
