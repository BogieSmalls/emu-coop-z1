import customtkinter as ctk


class SessionScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller
        ctk.CTkLabel(self, text="Session (placeholder)").pack(pady=20)
        ctk.CTkButton(self, text="Disconnect → Relay Setup", command=self._disconnect).pack(pady=10)

    def _disconnect(self) -> None:
        self.controller.show_screen("relay_setup")
