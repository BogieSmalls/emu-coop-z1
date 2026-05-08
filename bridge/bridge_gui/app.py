"""CustomTkinter app shell with screen navigation."""
from __future__ import annotations

import customtkinter as ctk


class BridgeApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("emu-coop bridge")
        self.geometry("700x500")
        self.minsize(600, 400)

        self._screens: dict[str, ctk.CTkFrame] = {}
        self._current_screen: ctk.CTkFrame | None = None
        self.endpoint_type = "edn8"
        self.patched_rom_path = None
        self.mister_config = None
        self.session_config = None

        self._register_screens()
        self.show_screen("device_select")

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
