from bridge_core.mister_mailbox import BufferMailboxMemory
from bridge_core.mister_smartcache import (
    ADDRLIST_CTRL_OFFSET,
    ADDRLIST_VALUES_OFFSET,
    VALCACHE_CTRL_OFFSET,
    VALCACHE_VALUES_OFFSET,
    MisterSmartCacheMemoryEndpoint,
)


def test_submit_read_request_writes_addresses_before_request_header():
    memory = BufferMailboxMemory(bytearray(0x60000))
    endpoint = MisterSmartCacheMemoryEndpoint(memory)

    request = endpoint.submit_read_request([(0x0012, 1), (0x0657, 1), (0x0671, 1)])

    assert memory.read_u64(ADDRLIST_VALUES_OFFSET) == (0x0657 << 32) | 0x0012
    assert memory.read_u64(ADDRLIST_VALUES_OFFSET + 8) == 0x0671
    assert memory.read_u64(ADDRLIST_CTRL_OFFSET) == (request.request_id << 32) | 3


def test_read_response_unpack_values_for_matching_request():
    memory = BufferMailboxMemory(bytearray(0x60000))
    endpoint = MisterSmartCacheMemoryEndpoint(memory)
    request = endpoint.submit_read_request([(0x0012, 1), (0x0657, 1), (0x0671, 1)])
    memory.write_u64(VALCACHE_VALUES_OFFSET, 0x03_01_05)
    memory.write_u64(VALCACHE_CTRL_OFFSET, (42 << 32) | request.request_id)

    assert endpoint.read_response(request, timeout_ms=0) == {
        0x0012: 0x05,
        0x0657: 0x01,
        0x0671: 0x03,
    }
    assert endpoint.last_frame == 42


def test_read_ranges_returns_none_when_response_id_does_not_match():
    memory = BufferMailboxMemory(bytearray(0x60000))
    endpoint = MisterSmartCacheMemoryEndpoint(memory)

    assert endpoint.read_ranges([(0x0012, 1)], timeout_ms=0) is None


def test_read_byte_uses_smart_cache_request():
    class AutoRespondMemory(BufferMailboxMemory):
        def write_u64(self, offset: int, value: int) -> None:
            super().write_u64(offset, value)
            if offset == ADDRLIST_CTRL_OFFSET:
                request_id = (value >> 32) & 0xFFFFFFFF
                super().write_u64(VALCACHE_VALUES_OFFSET, 0x05)
                super().write_u64(VALCACHE_CTRL_OFFSET, (7 << 32) | request_id)

    endpoint = MisterSmartCacheMemoryEndpoint(AutoRespondMemory(bytearray(0x60000)))

    assert endpoint.read_byte(0x0012, timeout_ms=0) == 0x05
    assert endpoint.last_frame == 7
