from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
CORE_DIR = REPO_ROOT / "mister" / "cores" / "NES_z1rr-coop"


def test_mister_core_project_is_vendored_without_nested_git_repo():
    assert (CORE_DIR / "NES.qpf").is_file()
    assert (CORE_DIR / "NES.qsf").is_file()
    assert (CORE_DIR / "NES.sv").is_file()
    assert (CORE_DIR / "rtl" / "ra_ram_mirror_nes.sv").is_file()
    assert not (CORE_DIR / ".git").exists()


def test_mister_core_build_wrapper_lands_named_bridge_payload():
    script = (REPO_ROOT / "build-mister-core.ps1").read_text(encoding="utf-8")

    assert "mister/cores/NES_z1rr-coop" in script
    assert "quartus_sh --flow compile NES" in script
    assert "output_files\\NES.rbf" in script
    assert "bridge\\bridge_core\\mister_payload\\NES_z1rr-coop.rbf" in script
