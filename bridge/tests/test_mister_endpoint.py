import pytest

from bridge_core.mister_endpoint import ReadOnlyMisterMemoryEndpoint

from .mister_mirror_factory import make_nes_ra_mirror


def test_mister_endpoint_reads_cpu_ram_ranges_from_ra_mirror():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0657] = 0x01
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(cpu_ram=cpu_ram))

    assert endpoint.read_ranges([(0x0012, 1), (0x0657, 1)]) == {
        0x0012: 0x05,
        0x0657: 0x01,
    }


def test_mister_endpoint_reads_single_byte():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0671] = 0x03
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(cpu_ram=cpu_ram))

    assert endpoint.read_byte(0x0671) == 0x03


def test_mister_endpoint_skips_reads_while_mirror_busy():
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror(busy=True))

    assert endpoint.read_ranges([(0x0012, 1)]) is None
    assert endpoint.read_byte(0x0012) is None


def test_mister_endpoint_is_read_only_until_write_channel_exists():
    endpoint = ReadOnlyMisterMemoryEndpoint(make_nes_ra_mirror())

    with pytest.raises(NotImplementedError):
        endpoint.write_pairs([(0x0657, 0x01)])
