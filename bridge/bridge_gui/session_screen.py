"""Session: live status panel with two readiness indicators + Log/Messages tabs."""
from __future__ import annotations

import customtkinter as ctk


class SessionScreen(ctk.CTkFrame):
    def __init__(self, master, controller) -> None:
        super().__init__(master)
        self.controller = controller

        ctk.CTkLabel(
            self,
            text="Session",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(10, 5))

        # Readiness indicators row
        indicators = ctk.CTkFrame(self, fg_color="transparent")
        indicators.pack(pady=10, padx=20, fill="x")

        # Cart panel
        cart_panel = ctk.CTkFrame(indicators)
        cart_panel.pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkLabel(cart_panel, text="Cart connection", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 0))
        self._cart_usb_label = ctk.CTkLabel(cart_panel, text="USB: ⚫ disconnected")
        self._cart_usb_label.pack(pady=2)
        self._cart_game_label = ctk.CTkLabel(cart_panel, text="Game: ⚫ unknown")
        self._cart_game_label.pack(pady=(2, 8))

        # Network panel
        net_panel = ctk.CTkFrame(indicators)
        net_panel.pack(side="left", padx=10, fill="x", expand=True)
        ctk.CTkLabel(net_panel, text="Network connection", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 0))
        self._net_relay_label = ctk.CTkLabel(net_panel, text="Relay: ⚫ disconnected")
        self._net_relay_label.pack(pady=2)
        self._net_partner_label = ctk.CTkLabel(net_panel, text="Partner: ⚫ unpaired")
        self._net_partner_label.pack(pady=(2, 8))

        # Sync state
        self._sync_label = ctk.CTkLabel(self, text="Sync: ⚫ IDLE", font=ctk.CTkFont(size=14, weight="bold"))
        self._sync_label.pack(pady=10)

        # Tabs
        self._tabs = ctk.CTkTabview(self, height=250)
        self._tabs.pack(pady=10, padx=20, fill="both", expand=True)
        self._tabs.add("Messages")
        self._tabs.add("Log")
        self._tabs.set("Messages")

        # Messages textbox
        self._messages_text = ctk.CTkTextbox(self._tabs.tab("Messages"), state="disabled")
        self._messages_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Log textbox
        self._log_text = ctk.CTkTextbox(self._tabs.tab("Log"), state="disabled")
        self._log_text.pack(fill="both", expand=True, padx=5, pady=5)

        # Disconnect button
        ctk.CTkButton(self, text="Disconnect", command=self._disconnect).pack(pady=10)

    def on_show(self) -> None:
        # The actual session worker is wired up in Task 22
        self._append_log("Entered Session screen")

    def _disconnect(self) -> None:
        # Confirmation will be added when worker exists in Task 22
        self.controller.show_screen("relay_setup")

    # --- StatusSink-style methods (called by worker thread via after()) ---

    def message(self, text: str) -> None:
        self._append_messages(text)

    def log(self, text: str, level: str = "INFO") -> None:
        self._append_log(f"[{level}] {text}")

    def state(self, state: str) -> None:
        self._append_log(f"state -> {state}")
        # Update the sync label color/text based on state
        color = {"ESTABLISHED": "green", "RECONNECTING": "orange", "DISCONNECTED": "red"}.get(state, "gray")
        self._sync_label.configure(text=f"Sync: {state}", text_color=color)

    def update_cart_usb(self, connected: bool) -> None:
        self._cart_usb_label.configure(text=f"USB: {'🟢 connected' if connected else '🔴 disconnected'}")

    def update_cart_game(self, running: bool) -> None:
        self._cart_game_label.configure(text=f"Game: {'🟢 running' if running else '🟡 not running'}")

    def update_net_relay(self, connected: bool) -> None:
        self._net_relay_label.configure(text=f"Relay: {'🟢 connected' if connected else '⚫ disconnected'}")

    def update_net_partner(self, paired: bool) -> None:
        self._net_partner_label.configure(text=f"Partner: {'🟢 paired' if paired else '🟡 unpaired'}")

    # --- internals ---

    def _append_messages(self, text: str) -> None:
        import time as _t
        ts = _t.strftime("%H:%M:%S")
        self._messages_text.configure(state="normal")
        self._messages_text.insert("end", f"[{ts}] {text}\n")
        self._messages_text.see("end")
        self._messages_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        import time as _t
        ts = _t.strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] {text}\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")
