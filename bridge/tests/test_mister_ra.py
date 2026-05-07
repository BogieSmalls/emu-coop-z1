from bridge_core.mister_ra import RAMirror

from .mister_mirror_factory import make_nes_ra_mirror


def test_ra_mirror_parses_active_header_and_regions():
    mirror = RAMirror(make_nes_ra_mirror(frame=123))

    assert mirror.active is True
    assert mirror.busy is False
    assert mirror.frame == 123
    assert len(mirror.regions) == 2
    assert mirror.regions[0].size == 0x0800
    assert mirror.regions[1].size == 0x2000


def test_ra_mirror_reads_nes_cpu_ram_and_mirrors():
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x07FF] = 0xAA
    mirror = RAMirror(make_nes_ra_mirror(cpu_ram=cpu_ram))

    assert mirror.read_nes_byte(0x0012) == 0x05
    assert mirror.read_nes_byte(0x0812) == 0x05
    assert mirror.read_nes_byte(0x1FFF) == 0xAA


def test_ra_mirror_reads_nes_cart_ram():
    cart_ram = bytearray(0x2000)
    cart_ram[0x0123] = 0x77
    mirror = RAMirror(make_nes_ra_mirror(cart_ram=cart_ram))

    assert mirror.read_nes_byte(0x6123) == 0x77


def test_ra_mirror_returns_zero_for_unmirrored_addresses():
    mirror = RAMirror(make_nes_ra_mirror())

    assert mirror.read_nes_byte(0x2000) == 0
    assert mirror.read_nes_byte(0x8000) == 0


def test_ra_mirror_rejects_inactive_header():
    raw = make_nes_ra_mirror()
    raw[0:4] = b"BAD!"
    mirror = RAMirror(raw)

    assert mirror.active is False
    assert mirror.frame == 0
    assert mirror.regions == []
    assert mirror.read_nes_byte(0x0012) == 0
