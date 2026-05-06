import pytest

from bridge_core.cc_client import CCClient

from .mock_cc_server import MockCCServer


def make_client_with_mock(ram_size: int = 0x0800) -> tuple[CCClient, MockCCServer]:
    server = MockCCServer(ram_size=ram_size)
    client = CCClient(serial_port=server.serial)
    return client, server


def test_read_array_returns_correct_bytes():
    client, server = make_client_with_mock()
    server.set_ram(0x0010, b"\xab\xcd\xef")
    client.send_read_array(0x0010, 3)
    server.step()
    result = client.poll_response(timeout_ms=100)
    assert result == b"\xab\xcd\xef"


def test_read_individual_addresses():
    client, server = make_client_with_mock()
    server.set_ram(0x0010, 0xAB)
    server.set_ram(0x0050, 0xCD)
    server.set_ram(0x0100, 0xEF)
    client.send_read_addrs([0x0010, 0x0050, 0x0100])
    server.step()
    result = client.poll_response(timeout_ms=100)
    assert result == b"\xab\xcd\xef"


def test_write_pairs_updates_ram():
    client, server = make_client_with_mock()
    client.send_write_pairs([(0x0010, 0xAB), (0x0050, 0xCD)])
    server.step()
    assert server.ram[0x0010] == 0xAB
    assert server.ram[0x0050] == 0xCD


def test_write_array_updates_ram():
    client, server = make_client_with_mock()
    client.send_write_array(0x0010, b"\xab\xcd\xef")
    server.step()
    assert server.ram[0x0010:0x0013] == b"\xab\xcd\xef"


def test_msg_id_wraps_after_255():
    client, server = make_client_with_mock()
    for _ in range(257):
        client.send_read_array(0x0000, 4)
        server.step()
        client.poll_response(timeout_ms=100)
    # Should not raise; client should keep msg_id in 1-255 range (skipping 0)
    assert 1 <= client._msg_id <= 255


def test_poll_response_returns_none_on_timeout():
    client, _server = make_client_with_mock()
    # Don't issue a request; nothing should be in the RX buffer
    result = client.poll_response(timeout_ms=10)
    assert result is None
