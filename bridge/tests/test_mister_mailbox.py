import pytest

from bridge_core.mister_mailbox import (
    MAILBOX_CTRL_OFFSET,
    MAILBOX_PAIR_OFFSET,
    STATUS_OK,
    BufferMailboxMemory,
    MisterWriteMailbox,
)


class AutoAckMailboxMemory(BufferMailboxMemory):
    def write_u64(self, offset: int, value: int) -> None:
        super().write_u64(offset, value)
        if offset == MAILBOX_CTRL_OFFSET:
            request_seq = value & 0xFF
            count = (value >> 8) & 0xFF
            ack = request_seq << 16
            status = STATUS_OK << 24
            super().write_u64(offset, request_seq | (count << 8) | ack | status)


def test_submit_pairs_writes_pair_words_before_control_word():
    memory = BufferMailboxMemory(bytearray(0x60000))
    mailbox = MisterWriteMailbox(memory)

    seq = mailbox.submit_pairs([(0x0657, 0x01), (0x0671, 0x03)])

    assert memory.read_u64(MAILBOX_PAIR_OFFSET) == 0x01_0657
    assert memory.read_u64(MAILBOX_PAIR_OFFSET + 8) == 0x03_0671
    assert memory.read_u64(MAILBOX_CTRL_OFFSET) == seq | (2 << 8)


def test_wait_for_ack_requires_matching_ack_sequence():
    memory = BufferMailboxMemory(bytearray(0x60000))
    mailbox = MisterWriteMailbox(memory)

    seq = mailbox.submit_pairs([(0x0657, 0x01)])
    assert mailbox.wait_for_ack(seq, timeout_ms=0) is False

    memory.write_u64(MAILBOX_CTRL_OFFSET, seq | (1 << 8) | (seq << 16))
    assert mailbox.wait_for_ack(seq, timeout_ms=0) is True


def test_write_pairs_submits_and_waits_for_fpga_ack():
    mailbox = MisterWriteMailbox(AutoAckMailboxMemory(bytearray(0x60000)))

    assert mailbox.write_pairs([(0x0657, 0x01)]) is True


def test_submit_pairs_rejects_non_cpu_ram_addresses_before_touching_mailbox():
    memory = BufferMailboxMemory(bytearray(0x60000))
    mailbox = MisterWriteMailbox(memory)

    with pytest.raises(ValueError, match="outside CPU RAM"):
        mailbox.submit_pairs([(0x6000, 0x01)])

    assert memory.read_u64(MAILBOX_CTRL_OFFSET) == 0
    assert memory.read_u64(MAILBOX_PAIR_OFFSET) == 0


def test_submit_pairs_rejects_oversized_batches():
    memory = BufferMailboxMemory(bytearray(0x60000))
    mailbox = MisterWriteMailbox(memory, max_pairs=2)

    with pytest.raises(ValueError, match="at most 2"):
        mailbox.submit_pairs([(0x0001, 1), (0x0002, 2), (0x0003, 3)])

    assert memory.read_u64(MAILBOX_CTRL_OFFSET) == 0
