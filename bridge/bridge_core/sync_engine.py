"""Sync engine — Python port of driver.lua.

record_changed() is line-by-line equivalent to the Lua function. Other parts
(SyncEngine class with poll/cache/handleTable) come in a later task.
"""
from __future__ import annotations

from typing import Any


def record_changed(
    record: dict[str, Any],
    value: int,
    previous_value: int,
    receiving: bool,
) -> tuple[bool, int]:
    """Port of driver.lua's recordChanged().

    Returns (allow, value): whether to send/apply this change, and the resolved
    value to send/apply (which may differ from the input).
    """
    if record.get("kind") == "trigger":
        return False, value

    unaltered = value
    allow = True

    # Compute mask
    size = record.get("size", 1)
    if size == 2:
        mask = 0xFFFF
    elif size == 4:
        mask = 0xFFFFFFFF
    else:
        mask = 0xFF

    inverse_mask = 0
    masked_value = value

    if "mask" in record:
        mask = record["mask"]
        inverse_mask = (~mask) & 0xFFFFFFFF
        masked_value = (mask & value) | (inverse_mask & previous_value)

    kind = record.get("kind")

    if callable(kind):
        result = kind(value, previous_value, receiving)
        if isinstance(result, tuple):
            allow, value = result
        else:
            allow = bool(result)
        if value is None:
            value = unaltered
    elif kind == "high":
        allow = (mask & value) > (mask & previous_value)
        value = masked_value
    elif kind == "bitOr":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value | previous_value
        else:
            value = masked_value
    elif kind == "bitAnd":
        allow = masked_value != previous_value
        if receiving:
            value = masked_value & previous_value
        else:
            value = masked_value
    elif kind == "delta":
        if not receiving:
            allow = masked_value != previous_value
            value = (mask & value) - (mask & previous_value)
        else:
            allow = value != 0
            masked_sum = previous_value + value
            if "deltaMin" in record and masked_sum < record["deltaMin"]:
                masked_sum = record["deltaMin"]
            if "deltaMax" in record and masked_sum > record["deltaMax"]:
                masked_sum = record["deltaMax"]
            value = (inverse_mask & previous_value) | (mask & masked_sum)
    else:
        allow = masked_value != previous_value
        value = masked_value

    if allow and "cond" in record:
        # cond is a callable: cond(value, size) -> bool
        cond_fn = record["cond"]
        if callable(cond_fn):
            allow = cond_fn(masked_value, size)

    return allow, value


from bridge_core.memory_endpoint import MemoryEndpoint
from bridge_core.sync_probe import endpoint_error, read_running_byte


class SyncEngine:
    """Polling-based equivalent of GameDriver in driver.lua.

    Holds a cache of last-known RAM values for the mode's sync set, diffs each
    poll snapshot against it, runs record_changed, and either emits outgoing
    data frames (via the caller) or applies incoming ones (via cc_client).
    """

    def __init__(self, endpoint: MemoryEndpoint, mode: Any) -> None:
        self.endpoint = endpoint
        self.mode = mode
        self.cache: dict[int, int] = {}
        self.did_cache = False
        self.force_send = False
        self.sleep_queue: list[dict] = []

    def is_game_running(self, snapshot: dict[int, int]) -> bool:
        return self.mode.is_running(snapshot)

    def implausible_snapshot_reason(self, snapshot: dict[int, int]) -> str | None:
        for addr, record in self.mode.SYNC.items():
            if addr not in snapshot:
                continue
            reason = self.implausible_change_reason(addr, snapshot[addr])
            if reason:
                return reason
        return None

    def implausible_change_reason(self, addr: int, value: int) -> str | None:
        record = self.mode.SYNC.get(addr)
        if record is None:
            return None
        if record.get("kind") in {"bitOr", "bitAnd"} and "mask" in record:
            size_mask = self._record_size_mask(record)
            outside_mask = size_mask & ~int(record["mask"])
            if value & outside_mask:
                label = self._record_label(record)
                return (
                    f"0x{addr:04X} {label} value {value} "
                    f"has bits outside mask 0x{int(record['mask']):X}"
                )
        max_value = self._max_plausible_value(record)
        if max_value is None:
            return None
        if value < 0 or value > max_value:
            label = self._record_label(record)
            return f"0x{addr:04X} {label} value {value} exceeds max {max_value}"
        return None

    def check_first_running(self, snapshot: dict[int, int]) -> list[tuple[int, int]]:
        """Populate cache on the first running tick. If force_send is True,
        return a list of (addr, value) pairs to broadcast."""
        if self.implausible_snapshot_reason(snapshot):
            return []
        if self.did_cache:
            return []
        to_send: list[tuple[int, int]] = []
        for addr in self.mode.SYNC:
            value = snapshot.get(addr, 0)
            if addr not in self.cache:
                self.cache[addr] = value
            if self.force_send and value != 0:
                to_send.append((addr, value))
        self.did_cache = True
        return to_send

    def diff(self, snapshot: dict[int, int]) -> list[tuple[int, int, str | None]]:
        """For each watched address that changed since last poll, run
        record_changed (sending side). Returns list of (addr, send_value, message)
        for changes that should be transmitted."""
        if self.implausible_snapshot_reason(snapshot):
            return []
        out: list[tuple[int, int, str | None]] = []
        for addr, record in self.mode.SYNC.items():
            cur = snapshot.get(addr, 0)
            prev = self.cache.get(addr, cur)
            if cur == prev:
                continue
            allow, send_value = record_changed(record, cur, prev, receiving=False)
            if allow:
                self.cache[addr] = cur
                msg = self._build_send_message(record, cur, prev)
                out.append((addr, send_value, msg))
        return out

    def handle_table(self, t: dict, *, queue_if_not_running: bool = True) -> list[str]:
        """Apply a partner's data frame to RAM. Returns any user-visible messages."""
        addr = t.get("addr")
        if addr is None:
            return []
        record = self.mode.SYNC.get(addr)
        if record is None:
            return [f"Partner changed unknown address 0x{addr:04X}"]
        invalid_reason = self.implausible_change_reason(addr, t["value"])
        if invalid_reason:
            return [f"Ignoring implausible partner change: {invalid_reason}"]
        if queue_if_not_running:
            try:
                running = read_running_byte(self.endpoint, self.mode)
            except Exception:
                running = None
            if not running:
                self.sleep_queue.append(dict(t))
                return []
        try:
            previous_value = self.endpoint.read_byte(addr)
        except Exception as exc:
            return [f"Could not read address 0x{addr:04X}: {endpoint_error(exc)}"]
        if previous_value is None:
            return [f"Could not read address 0x{addr:04X}"]
        allow, value = record_changed(record, t["value"], previous_value, receiving=True)
        messages: list[str] = []
        if allow:
            try:
                wrote = self.endpoint.write_pairs([(addr, value & 0xFF)])
            except NotImplementedError:
                wrote = False
            except Exception as exc:
                return [f"Could not write address 0x{addr:04X}: {endpoint_error(exc)}"]
            if not wrote:
                return [f"Could not write address 0x{addr:04X}"]
            self.cache[addr] = value & 0xFF
            # Receive trigger
            if "receive_trigger" in record:
                msg = record["receive_trigger"](value, previous_value)
                if msg:
                    messages.append(msg)
            # Function-kind messages
            elif "message" in record:
                msg = record["message"](value, previous_value)
                if msg:
                    messages.append(msg)
            # Single-name items
            elif "name" in record and value != previous_value:
                messages.append(f"Partner got {record['name']}")
            # Multi-name items
            elif "name_map" in record and value > 0 and value != previous_value:
                idx = value - 1
                if 0 <= idx < len(record["name_map"]):
                    messages.append(f"Partner got {record['name_map'][idx]}")
        return messages

    def drain_sleep_queue(self) -> list[str]:
        queued = self.sleep_queue
        self.sleep_queue = []
        messages: list[str] = []
        for item in queued:
            messages.extend(self.handle_table(item, queue_if_not_running=False))
        return messages

    def resync(self) -> None:
        """Clear cache and arm force_send so the next running tick re-broadcasts state."""
        self.cache.clear()
        self.did_cache = False
        self.force_send = True

    def _build_send_message(self, record: dict, cur: int, prev: int) -> str | None:
        """Local-side analog of handle_table's message construction (for the
        sending peer's own UI: 'You picked up Wood Sword')."""
        if "name" in record and cur > prev:
            return f"You got {record['name']}"
        if "name_map" in record and cur > prev:
            idx = cur - 1
            if 0 <= idx < len(record["name_map"]):
                return f"You got {record['name_map'][idx]}"
        return None

    @staticmethod
    def _max_plausible_value(record: dict) -> int | None:
        if record.get("kind") != "high":
            return None
        if "name_map" in record:
            return len(record["name_map"])
        if "name" in record:
            return 1
        return None

    @staticmethod
    def _record_size_mask(record: dict) -> int:
        size = record.get("size", 1)
        if size == 2:
            return 0xFFFF
        if size == 4:
            return 0xFFFFFFFF
        return 0xFF

    @staticmethod
    def _record_label(record: dict) -> str:
        if "name" in record:
            return record["name"]
        if "name_map" in record:
            return "/".join(record["name_map"])
        return str(record.get("kind", "record"))
