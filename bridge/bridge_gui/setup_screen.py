import customtkinter as ctk


class ROMSetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="ROM Setup (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Continue → Relay Setup", command=self._continue).pack(pady=10)

    def _continue(self) -> None:
        self.controller.show_screen("relay_setup")
