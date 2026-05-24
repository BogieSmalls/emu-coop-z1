"""EDN8-specific sync safety policy."""
from __future__ import annotations


EDN8_TLOZ_ALL_RESYNC_SEND_LIMIT = 2


def tloz_all_overload_options(endpoint_type: str, mode_name: str) -> dict[str, int | bool]:
    if endpoint_type == "edn8" and mode_name == "tloz_all":
        return {
            "resync_send_limit": EDN8_TLOZ_ALL_RESYNC_SEND_LIMIT,
            "defer_full_poll_while_map_pending": True,
        }
    return {}
