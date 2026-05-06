"""GUI entry point.

Usage: python -m bridge_gui
"""
from bridge_gui.app import BridgeApp


def main() -> None:
    ctk_init()
    app = BridgeApp()
    app.mainloop()


def ctk_init() -> None:
    import customtkinter as ctk
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")


if __name__ == "__main__":
    main()
