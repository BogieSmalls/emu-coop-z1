from bridge_core.session_diagnostics import SessionDiagnostics


def test_session_diagnostics_formats_edn8_summary():
    diag = SessionDiagnostics(
        endpoint_type="edn8",
        mode_name="tloz_all",
        com_port="COM7",
        peer_id="abcdef123456",
    )
    diag.record_running_probe(success=True)
    diag.record_full_poll(success=False, error="timed out")
    diag.record_incoming_update(0x0657, 0x01)
    diag.record_outgoing_update(0x067F, 0x10)
    diag.record_incoming_write_error("Could not write address 0x0657")
    diag.record_deferred_full_poll(map_backlog=3, resync_backlog=5)
    diag.set_relay_state("ESTABLISHED", reconnect_attempt=2)

    text = diag.render_text()

    assert "Endpoint: EDN8" in text
    assert "Mode: tloz_all" in text
    assert "COM port: COM7" in text
    assert "Peer ID: abcdef" in text
    assert "Relay state: ESTABLISHED" in text
    assert "Reconnect attempt: 2" in text
    assert "Running probes: 1 ok / 0 failed" in text
    assert "Full polls: 0 ok / 1 failed" in text
    assert "Incoming updates: 1" in text
    assert "Outgoing updates: 1" in text
    assert "Incoming write errors: 1" in text
    assert "Map backlog: 3" in text
    assert "Resync backlog: 5" in text
    assert "Deferred full polls: 1" in text
    assert "Last endpoint error: Could not write address 0x0657" in text
    assert "Last partner update: 0x0657=0x01" in text
