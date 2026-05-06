"""Pluggable status sink. GUI subscribes; CLI prints; tests capture."""
from __future__ import annotations

import time
from typing import Protocol


class StatusSink(Protocol):
    def message(self, text: str) -> None: ...
    def log(self, text: str, level: str = "INFO") -> None: ...
    def state(self, state: str) -> None: ...


class ConsoleStatusSink:
    """Prints to stdout. Useful for CLI use and tests."""

    def message(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {text}", flush=True)

    def log(self, text: str, level: str = "INFO") -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {text}", flush=True)

    def state(self, state: str) -> None:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] state -> {state}", flush=True)


class MultiSink:
    """Fan-out to multiple sinks."""

    def __init__(self, sinks: list) -> None:
        self._sinks = sinks

    def message(self, text: str) -> None:
        for s in self._sinks:
            s.message(text)

    def log(self, text: str, level: str = "INFO") -> None:
        for s in self._sinks:
            s.log(text, level)

    def state(self, state: str) -> None:
        for s in self._sinks:
            s.state(state)
