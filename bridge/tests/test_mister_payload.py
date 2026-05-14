import ast
import json
import subprocess
import sys
from pathlib import Path


PAYLOAD_DIR = Path(__file__).parents[1] / "bridge_core" / "mister_payload"
BRIDGE_DIR = Path(__file__).parents[1]


def test_payload_manifest_loads_helper_metadata():
    manifest = json.loads((PAYLOAD_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["helper"]["filename"] == "mister-helper.py"
    assert manifest["helper"]["remote_path"] == "/media/fat/Scripts/z1rr-coop/mister-helper.py"
    assert manifest["helper"]["port"] == 55355
    assert manifest["roms"]["remote_dir"] == "/media/fat/games/NES/z1rr-coop"
    assert manifest["core"]["filename"] == "NES_z1rr-coop.rbf"
    assert manifest["core"]["remote_path"] == "/media/fat/_Console/NES_z1rr-coop.rbf"


def test_pyinstaller_spec_bundles_mister_core_payload():
    spec = (BRIDGE_DIR / "bridge.spec").read_text(encoding="utf-8")

    assert "bridge_core/mister_payload/manifest.json" in spec
    assert "bridge_core/mister_payload/mister-helper.py" in spec
    assert "bridge_core/mister_payload/NES_z1rr-coop.rbf" in spec


def test_pyinstaller_spec_embeds_hardware_icon():
    spec = (BRIDGE_DIR / "bridge.spec").read_text(encoding="utf-8")

    assert (BRIDGE_DIR / "assets" / "ganon_blue.ico").is_file()
    assert "assets/ganon_blue.ico" in spec
    assert "icon='assets/ganon_blue.ico'" in spec


def test_payload_helper_script_is_stdlib_only():
    helper = PAYLOAD_DIR / "mister-helper.py"
    tree = ast.parse(helper.read_text(encoding="utf-8"))
    forbidden = {
        "bridge_core",
        "bridge_gui",
        "customtkinter",
        "paramiko",
        "serial",
    }

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])

    assert not (imports & forbidden)


def test_payload_helper_script_avoids_modern_type_syntax():
    source = (PAYLOAD_DIR / "mister-helper.py").read_text(encoding="utf-8")
    tree = ast.parse(source, type_comments=True)

    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            annotations.extend(
                arg.annotation
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if arg.annotation is not None
            )
            if node.args.vararg and node.args.vararg.annotation is not None:
                annotations.append(node.args.vararg.annotation)
            if node.args.kwarg and node.args.kwarg.annotation is not None:
                annotations.append(node.args.kwarg.annotation)
            if node.returns is not None:
                annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)

    uses_pep604 = any(
        isinstance(child, ast.BinOp) and isinstance(child.op, ast.BitOr)
        for annotation in annotations
        for child in ast.walk(annotation)
    )
    uses_pep585 = any(
        isinstance(child, ast.Subscript)
        and isinstance(child.value, ast.Name)
        and child.value.id in {"dict", "list", "set", "tuple"}
        for annotation in annotations
        for child in ast.walk(annotation)
    )

    assert not uses_pep604
    assert not uses_pep585


def test_payload_helper_script_has_cli_help():
    result = subprocess.run(
        [sys.executable, str(PAYLOAD_DIR / "mister-helper.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "--enable-writes" in result.stdout
