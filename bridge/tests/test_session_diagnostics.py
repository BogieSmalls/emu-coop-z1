from bridge_core.session_diagnostics import SessionDiagnostics


def test_session_diagnostics_formats_edn8_summary():
    diag = SessionDiagnostics(
        endpoint_type="edn8",
        mode_name="tloz_all",
        com_port="COM7",
        peer_id="abcdef123456",
    )
    diag.record_running_probe(
        success=True,
        running=True,
        addr=0x0012,
        value=0x05,
        frame=77,
    )
    diag.record_full_poll(success=False, error="timed out")
    diag.record_incoming_update(0x0657, 0x01)
    diag.record_outgoing_update(0x067F, 0x10)
    diag.record_incoming_write_error("Could not write address 0x0657")
    diag.record_incoming_result(
        0x0660,
        0x01,
        applied=True,
        previous_value=0x00,
        written_value=0x01,
        messages=["Partner got Raft"],
    )
    diag.record_deferred_full_poll(map_backlog=3, resync_backlog=5)
    diag.set_relay_state("ESTABLISHED", reconnect_attempt=2)

    text = diag.render_text()

    assert "Endpoint: EDN8" in text
    assert "Mode: tloz_all" in text
    assert "COM port: COM7" in text
    assert "Peer ID: abcdef" in text
    assert "Relay state: ESTABLISHED" in text
    assert "Reconnect attempt: 2" in text
    assert "Running probes: 1 running / 0 not running / 0 failed" in text
    assert "Running state: running" in text
    assert "Last running byte: 0x0012=0x05" in text
    assert "Last endpoint frame: 77" in text
    assert "Full polls: 0 ok / 1 failed" in text
    assert "Incoming updates: 1" in text
    assert "Outgoing updates: 1" in text
    assert "Incoming write errors: 1" in text
    assert "Map backlog: 3" in text
    assert "Resync backlog: 5" in text
    assert "Deferred full polls: 1" in text
    assert "Last endpoint error: Could not write address 0x0657" in text
    assert "Last partner update: 0x0657=0x01" in text
    assert "Last incoming result: 0x0660 0x00 -> 0x01 applied; Partner got Raft" in text


def test_session_diagnostics_formats_not_running_probe_value():
    diag = SessionDiagnostics(endpoint_type="mister", mode_name="tloz_progress")

    diag.record_running_probe(
        success=True,
        running=False,
        addr=0x0012,
        value=0x00,
        frame=88,
    )
    diag.record_endpoint_sample(
        {
            0x0012: 0x00,
            0x0657: 0x01,
            0x065A: 0x00,
        }
    )

    text = diag.render_text()

    assert "Endpoint: mister" in text
    assert "Running probes: 0 running / 1 not running / 0 failed" in text
    assert "Running state: not running" in text
    assert "Last running byte: 0x0012=0x00" in text
    assert "Last endpoint frame: 88" in text
    assert "Last RAM sample: 0x0012=0x00, 0x0657=0x01, 0x065A=0x00" in text


def test_session_diagnostics_keeps_frame_for_failed_running_probe():
    diag = SessionDiagnostics(endpoint_type="mister", mode_name="tloz_progress")

    diag.record_running_probe(
        success=False,
        running=None,
        addr=0x0012,
        frame=99,
        error="mirror_busy_or_inactive",
    )

    text = diag.render_text()

    assert "Running probes: 0 running / 0 not running / 1 failed" in text
    assert "Running state: unknown" in text
    assert "Last running byte: 0x0012=-" in text
    assert "Last endpoint frame: 99" in text
    assert "Last endpoint error: mirror_busy_or_inactive" in text


def test_session_diagnostics_clears_endpoint_error_after_success():
    diag = SessionDiagnostics(endpoint_type="mister", mode_name="tloz_progress")

    diag.record_running_probe(success=False, error="mirror_busy_or_inactive")
    diag.record_full_poll(success=True)

    text = diag.render_text()

    assert "Last endpoint error: -" in text
