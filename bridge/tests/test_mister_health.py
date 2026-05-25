from bridge_core.mister_health import (
    MisterHelperHealth,
    format_mister_health_summary,
    probe_mister_helper,
)
from bridge_core.modes import tloz_progress


class FakeEndpoint:
    def __init__(self, value=None, *, frame=0, error=None, exc=None):
        self.value = value
        self.last_frame = frame
        self.last_error = error
        self.exc = exc
        self.closed = False
        self.reads = []

    def read_byte(self, addr, timeout_ms=200):
        self.reads.append((addr, timeout_ms))
        if self.exc is not None:
            raise self.exc
        return self.value

    def close(self):
        self.closed = True


def test_probe_mister_helper_reports_live_mirror_running_byte():
    endpoint = FakeEndpoint(value=0x05, frame=123)

    health = probe_mister_helper(
        "192.168.0.130",
        port=55355,
        mode=tloz_progress,
        endpoint_factory=lambda **_kwargs: endpoint,
    )

    assert health == MisterHelperHealth(
        helper_reachable=True,
        mirror_ok=True,
        addr=0x0012,
        value=0x05,
        frame=123,
        running=True,
        error=None,
    )
    assert endpoint.reads == [(0x0012, 300)]
    assert endpoint.closed is True


def test_probe_mister_helper_reports_mirror_busy_without_losing_helper_status():
    endpoint = FakeEndpoint(value=None, frame=456, error="mirror_busy_or_inactive")

    health = probe_mister_helper(
        "192.168.0.130",
        mode=tloz_progress,
        endpoint_factory=lambda **_kwargs: endpoint,
    )

    assert health.helper_reachable is True
    assert health.mirror_ok is False
    assert health.frame == 456
    assert health.error == "mirror_busy_or_inactive"


def test_probe_mister_helper_reports_unreachable_helper():
    endpoint = FakeEndpoint(exc=ConnectionError("connection refused"))

    health = probe_mister_helper(
        "192.168.0.130",
        mode=tloz_progress,
        endpoint_factory=lambda **_kwargs: endpoint,
    )

    assert health.helper_reachable is False
    assert health.mirror_ok is False
    assert health.error == "connection refused"


def test_format_mister_health_summary_includes_frame_and_running_state():
    text = format_mister_health_summary(
        MisterHelperHealth(
            helper_reachable=True,
            mirror_ok=True,
            addr=0x0012,
            value=0x00,
            frame=77,
            running=False,
            error=None,
        )
    )

    assert text == "MiSTer helper/mirror OK: 0x0012=0x00 frame=77 running=no"
