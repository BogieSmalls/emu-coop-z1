"""Relay Setup: mode + relay address + session code + COM port + force_send."""
from __future__ import annotations

import customtkinter as ctk
import serial.tools.list_ports


AVAILABLE_MODES = ["tloz_all"]  # extend as more modes are ported
DEFAULT_RELAY = "129.158.62.225"
DEFAULT_RELAY_PORT = 9999


class RelaySetupScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller

        ctk.CTkLabel(
            self,
            text="Relay Setup",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(20, 10))

        form = ctk.CTkFrame(self)
        form.pack(pady=20, padx=40, fill="x")

        # Mode
        ctk.CTkLabel(form, text="Mode:").grid(row=0, column=0, sticky="e", padx=10, pady=8)
        self._mode_var = ctk.StringVar(value=AVAILABLE_MODES[0])
        ctk.CTkOptionMenu(form, variable=self._mode_var, values=AVAILABLE_MODES).grid(
            row=0, column=1, sticky="w", padx=10, pady=8
        )

        # Relay
        ctk.CTkLabel(form, text="Relay address:").grid(row=1, column=0, sticky="e", padx=10, pady=8)
        self._relay_var = ctk.StringVar(value=DEFAULT_RELAY)
        ctk.CTkEntry(form, textvariable=self._relay_var, width=200).grid(
            row=1, column=1, sticky="w", padx=10, pady=8
        )

        # Port
        ctk.CTkLabel(form, text="Relay port:").grid(row=2, column=0, sticky="e", padx=10, pady=8)
        self._port_var = ctk.StringVar(value=str(DEFAULT_RELAY_PORT))
        ctk.CTkEntry(form, textvariable=self._port_var, width=80).grid(
            row=2, column=1, sticky="w", padx=10, pady=8
        )

        # Session code
        ctk.CTkLabel(form, text="Session code:").grid(row=3, column=0, sticky="e", padx=10, pady=8)
        self._code_var = ctk.StringVar()
        self._code_entry = ctk.CTkEntry(form, textvariable=self._code_var, width=200)
        self._code_entry.grid(row=3, column=1, sticky="w", padx=10, pady=8)
        self._code_var.trace_add("write", lambda *_: self._update_connect_state())

        # COM port
        ctk.CTkLabel(form, text="COM port:").grid(row=4, column=0, sticky="e", padx=10, pady=8)
        com_ports = self._detect_com_ports()
        self._com_var = ctk.StringVar(value=com_ports[0] if com_ports else "")
        ctk.CTkOptionMenu(
            form,
            variable=self._com_var,
            values=com_ports if com_ports else ["(none detected)"],
        ).grid(row=4, column=1, sticky="w", padx=10, pady=8)

        # Force send
        self._force_send_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            form,
            text="Resending all my state on connect (after a crash)",
            variable=self._force_send_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=8)

        # Status text
        self._status_label = ctk.CTkLabel(self, text="", text_color="red", wraplength=500)
        self._status_label.pack(pady=5)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=20)

        ctk.CTkButton(btn_row, text="← Back", command=self._back).pack(side="left", padx=5)
        self._connect_btn = ctk.CTkButton(
            btn_row,
            text="Connect",
            command=self._connect,
            state="disabled",
        )
        self._connect_btn.pack(side="left", padx=5)

    def _detect_com_ports(self) -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def _update_connect_state(self) -> None:
        code = self._code_var.get().strip()
        ok = (
            len(code) >= 6
            and len(self._com_var.get()) > 0
            and self._com_var.get() != "(none detected)"
        )
        self._connect_btn.configure(state="normal" if ok else "disabled")

    def _back(self) -> None:
        self.controller.show_screen("rom_setup")

    def _connect(self) -> None:
        # Validate port number
        try:
            port = int(self._port_var.get())
        except ValueError:
            self._status_label.configure(text="Port must be a number")
            return
        # Stash session config on the controller
        self.controller.session_config = {
            "mode": self._mode_var.get(),
            "relay": self._relay_var.get(),
            "relay_port": port,
            "code": self._code_var.get().strip(),
            "com_port": self._com_var.get(),
            "force_send": self._force_send_var.get(),
        }
        self.controller.show_screen("session")

    def on_show(self) -> None:
        # Re-detect COM ports each time (user may have plugged in cart)
        com_ports = self._detect_com_ports()
        if com_ports and self._com_var.get() not in com_ports:
            self._com_var.set(com_ports[0])
        self._update_connect_state()
