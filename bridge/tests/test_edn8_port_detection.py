from types import SimpleNamespace

from bridge_gui.relay_setup_screen import port_is_likely_edn8, sort_edn8_ports


def port(device, *, vid=None, pid=None, description="USB Serial Device"):
    return SimpleNamespace(device=device, vid=vid, pid=pid, description=description)


def test_old_stm32_edn8_vid_is_still_detected():
    assert port_is_likely_edn8(port("COM5", vid=0x0483, pid=0x5740))


def test_newer_edn8_vid_pid_is_detected():
    assert port_is_likely_edn8(port("COM8", vid=0x38DF, pid=0x0017))


def test_ch340_adapter_is_not_detected_as_edn8():
    assert not port_is_likely_edn8(port("COM7", vid=0x1A86, pid=0x7523, description="USB-SERIAL CH340"))


def test_sort_edn8_ports_prioritizes_old_and_new_edn8_ids():
    ports = [
        port("COM7", vid=0x1A86, pid=0x7523, description="USB-SERIAL CH340"),
        port("COM8", vid=0x38DF, pid=0x0017),
        port("COM5", vid=0x0483, pid=0x5740),
    ]

    assert [p.device for p in sort_edn8_ports(ports)] == ["COM8", "COM5", "COM7"]
