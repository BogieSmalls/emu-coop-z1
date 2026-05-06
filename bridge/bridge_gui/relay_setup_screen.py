import customtkinter as ctk


class RelaySetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="Relay Setup (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Connect → Session", command=self._connect).pack(pady=10)
        ctk.CTkButton(self, text="← Back to ROM Setup", command=self._back).pack(pady=5)

    def _connect(self) -> None:
        self.controller.show_screen("session")

    def _back(self) -> None:
        self.controller.show_screen("rom_setup")
