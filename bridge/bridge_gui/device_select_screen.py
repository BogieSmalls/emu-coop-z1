from __future__ import annotations

import customtkinter as ctk

from bridge_gui.device_flow import DEVICE_EDN8, DEVICE_MISTER, next_screen_for_device


class DeviceSelectScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller

        ctk.CTkLabel(
            self,
            text="Choose Device",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(40, 24))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(pady=20)

        ctk.CTkButton(
            actions,
            text="EverDrive Pro N8",
            width=220,
            command=lambda: self._select(DEVICE_EDN8),
        ).pack(pady=8)

        ctk.CTkButton(
            actions,
            text="MiSTer",
            width=220,
            command=lambda: self._select(DEVICE_MISTER),
        ).pack(pady=8)

    def _select(self, device: str) -> None:
        self.controller.endpoint_type = device
        self.controller.show_screen(next_screen_for_device(device))
