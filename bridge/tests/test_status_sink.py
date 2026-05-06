from bridge_core.status_sink import ConsoleStatusSink, StatusSink, MultiSink


def test_console_status_sink_prints_to_capsys(capsys):
    sink = ConsoleStatusSink()
    sink.message("Partner got Wood Sword")
    sink.log("connected to relay", level="INFO")
    sink.state("CONNECTED")
    captured = capsys.readouterr()
    assert "Wood Sword" in captured.out
    assert "connected to relay" in captured.out


def test_multi_sink_dispatches_to_all_subscribers():
    captured: list[tuple[str, str]] = []

    class Capture:
        def message(self, text: str) -> None:
            captured.append(("message", text))

        def log(self, text: str, level: str = "INFO") -> None:
            captured.append(("log", text))

        def state(self, state: str) -> None:
            captured.append(("state", state))

    cap1 = Capture()
    cap2 = Capture()
    multi = MultiSink([cap1, cap2])
    multi.message("hi")
    assert captured.count(("message", "hi")) == 2
