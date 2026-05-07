from bridge_core.memory_endpoint import DictMemoryEndpoint


def test_dict_endpoint_reads_ranges_as_address_map():
    endpoint = DictMemoryEndpoint({0x0012: 0x05, 0x0657: 0x01})

    snapshot = endpoint.read_ranges([(0x0012, 1), (0x0657, 1)])

    assert snapshot == {0x0012: 0x05, 0x0657: 0x01}


def test_dict_endpoint_reads_single_byte():
    endpoint = DictMemoryEndpoint({0x0657: 0x02})

    assert endpoint.read_byte(0x0657) == 0x02


def test_dict_endpoint_write_pairs_updates_memory():
    endpoint = DictMemoryEndpoint({0x0657: 0x00})

    assert endpoint.write_pairs([(0x0657, 0x01)]) is True
    assert endpoint.read_byte(0x0657) == 0x01
