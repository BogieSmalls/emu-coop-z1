from bridge_cli.__main__ import main

from .mister_mirror_factory import make_nes_ra_mirror


def test_mister_read_cli_reads_hex_bytes_from_mirror_file(tmp_path, capsys):
    cpu_ram = bytearray(0x0800)
    cpu_ram[0x0012] = 0x05
    cpu_ram[0x0013] = 0x06
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror(cpu_ram=cpu_ram))

    rc = main(
        [
            "mister-read",
            "--mirror-file",
            str(mirror_path),
            "--addr",
            "0x0012",
            "--length",
            "2",
        ]
    )

    assert rc == 0
    assert capsys.readouterr().out.strip() == "05 06"


def test_mister_read_cli_reports_busy_mirror_file(tmp_path, capsys):
    mirror_path = tmp_path / "ra_mirror.bin"
    mirror_path.write_bytes(make_nes_ra_mirror(busy=True))

    rc = main(
        [
            "mister-read",
            "--mirror-file",
            str(mirror_path),
            "--addr",
            "0x0012",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "mirror busy or inactive" in captured.err
