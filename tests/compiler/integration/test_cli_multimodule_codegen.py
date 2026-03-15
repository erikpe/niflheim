from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_to_asm, run_cli, write_project


def test_cli_codegen_uses_program_resolution_for_multimodule_build(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "util.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import util;

            fn main() -> i64 {
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(out_file)])

    assert rc == 0
    assert out_file.exists()


def test_cli_codegen_imported_constructor_call_lowers(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "util.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import util;

            fn main() -> i64 {
                var b: util.Box = util.Box(7);
                if b == null {
                    return 1;
                }
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")
    assert "    call __nif_ctor_Box" in asm