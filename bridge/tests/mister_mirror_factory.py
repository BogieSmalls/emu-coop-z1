import struct


RA_MAGIC = 0x52414348


def make_nes_ra_mirror(
    *,
    cpu_ram: bytes | bytearray | None = None,
    cart_ram: bytes | bytearray | None = None,
    frame: int = 1,
    busy: bool = False,
) -> bytearray:
    cpu = bytes(cpu_ram or bytes(0x0800))
    cart = bytes(cart_ram or bytes(0x2000))
    buf = bytearray(0x10000)
    flags = 0x01 if busy else 0x00
    struct.pack_into("<IBBHI", buf, 0x00, RA_MAGIC, 2, flags, 0, frame)
    struct.pack_into("<I", buf, 0x0C, 0)
    struct.pack_into("<IHH", buf, 0x10, 0, len(cpu), 0x40)
    struct.pack_into("<IHH", buf, 0x18, 0, len(cart), 0x40 + len(cpu))
    buf[0x40:0x40 + len(cpu)] = cpu
    cart_base = 0x40 + len(cpu)
    buf[cart_base:cart_base + len(cart)] = cart
    return buf
