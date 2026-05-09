from bridge_core.memory_endpoint import DictMemoryEndpoint
from bridge_core.modes import tloz_all
from bridge_core.sync_session import SyncSession


class FakePipe:
    def __init__(self) -> None:
        self.state = "ESTABLISHED"
        self.sent = []
        self.on_data = None
        self.on_abort = None
        self.on_partner_reconnected = None

    def send_data(self, body):
        self.sent.append(body)

    def tick(self):
        return None

    def heartbeat_tick(self):
        return None


class FakeSink:
    def __init__(self) -> None:
        self.messages = []
        self.logs = []
        self.states = []

    def message(self, text):
        self.messages.append(text)

    def log(self, text, level="INFO"):
        self.logs.append((level, text))

    def state(self, state):
        self.states.append(state)


def test_sync_session_sends_app_hello_once():
    endpoint = DictMemoryEndpoint({0x0012: 0x00})
    pipe = FakePipe()
    session = SyncSession(endpoint=endpoint, pipe=pipe, mode=tloz_all, sink=FakeSink())

    session.tick_once()
    session.tick_once()

    assert pipe.sent == [{"op": "hello", "guid": tloz_all.GUID, "version": "0.1.0"}]


def test_sync_session_sends_tloz_all_changes_outward():
    endpoint = DictMemoryEndpoint({0x0012: 0x05, 0x0657: 0x00})
    pipe = FakePipe()
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=pipe, mode=tloz_all, sink=sink)

    session.tick_once()
    endpoint.memory[0x0657] = 0x01
    session.tick_once()

    assert {"addr": 0x0657, "value": 0x01} in pipe.sent
    assert "You got Wood Sword" in sink.messages


def test_sync_session_skips_full_poll_when_running_probe_is_not_running():
    class RecordingEndpoint(DictMemoryEndpoint):
        def __init__(self, memory):
            super().__init__(memory)
            self.read_ranges_calls = []

        def read_ranges(self, ranges, timeout_ms=300):
            self.read_ranges_calls.append(ranges)
            return super().read_ranges(ranges, timeout_ms=timeout_ms)

    endpoint = RecordingEndpoint({0x0012: 0x00, 0x0657: 0x00})
    session = SyncSession(endpoint=endpoint, pipe=FakePipe(), mode=tloz_all, sink=FakeSink())

    session.tick_once()

    assert endpoint.read_ranges_calls == [[(tloz_all.RUNNING_ADDR, 1)]]


def test_sync_session_applies_incoming_partner_writes():
    endpoint = DictMemoryEndpoint({0x0012: 0x05, 0x0657: 0x00})
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=FakePipe(), mode=tloz_all, sink=sink)

    session.on_data({"addr": 0x0657, "value": 0x01})

    assert endpoint.read_byte(0x0657) == 0x01
    assert sink.messages == ["Partner got Wood Sword"]


def test_sync_session_queues_incoming_partner_writes_until_game_is_running():
    endpoint = DictMemoryEndpoint({0x0012: 0x00, 0x0657: 0x00})
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=FakePipe(), mode=tloz_all, sink=sink)

    session.on_data({"addr": 0x0657, "value": 0x01})

    assert endpoint.read_byte(0x0657) == 0x00
    assert sink.messages == []

    endpoint.memory[0x0012] = 0x05
    session.tick_once()

    assert endpoint.read_byte(0x0657) == 0x01
    assert sink.messages == ["Partner got Wood Sword"]


def test_sync_session_reports_failed_incoming_partner_write():
    class FailingWriteEndpoint(DictMemoryEndpoint):
        def write_pairs(self, pairs):
            return False

    endpoint = FailingWriteEndpoint({0x0012: 0x05, 0x0657: 0x00})
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=FakePipe(), mode=tloz_all, sink=sink)

    session.on_data({"addr": 0x0657, "value": 0x01})

    assert endpoint.read_byte(0x0657) == 0x00
    assert sink.messages == ["Could not write address 0x0657"]


def test_sync_session_reports_incoming_endpoint_read_exception():
    class TimeoutReadEndpoint(DictMemoryEndpoint):
        def read_byte(self, addr, timeout_ms=200):
            if addr == tloz_all.RUNNING_ADDR:
                return 0x05
            raise TimeoutError("timed out")

    endpoint = TimeoutReadEndpoint({0x0012: 0x05, 0x0661: 0x00})
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=FakePipe(), mode=tloz_all, sink=sink)

    session.on_data({"addr": 0x0661, "value": 0x01})

    assert sink.messages == ["Could not read address 0x0661: timed out"]


def test_sync_session_keeps_pipe_alive_when_endpoint_poll_times_out():
    class TimeoutRangesEndpoint(DictMemoryEndpoint):
        def read_ranges(self, ranges, timeout_ms=300):
            raise TimeoutError("timed out")

    endpoint = TimeoutRangesEndpoint({0x0012: 0x05})
    pipe = FakePipe()
    sink = FakeSink()
    session = SyncSession(endpoint=endpoint, pipe=pipe, mode=tloz_all, sink=sink)

    session.tick_once()

    assert pipe.state == "ESTABLISHED"
    assert sink.logs == [("ERROR", "Endpoint read failed: timed out")]


def test_sync_session_validates_partner_mode_hello():
    session = SyncSession(
        endpoint=DictMemoryEndpoint({}),
        pipe=FakePipe(),
        mode=tloz_all,
        sink=FakeSink(),
    )

    session.on_data({"op": "hello", "guid": "wrong", "version": "0.1.0"})

    assert session.sink.messages == ["Partner has incompatible mode: wrong"]
