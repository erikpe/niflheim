from __future__ import annotations

from pathlib import Path

import pytest

import compiler.cli as cli

from compiler.semantic.linker import LinkedSemanticProgram
from tests.compiler.integration.helpers import compile_to_asm, run_cli, write, write_project


def test_cli_defaults_to_codegen_path(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_emit_asm(program: LinkedSemanticProgram) -> str:
        seen["program"] = program
        return "; codegen backend selected\n"

    monkeypatch.setattr(cli, "emit_asm", _fake_emit_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; codegen backend selected\n"
    program = seen["program"]
    assert isinstance(program, LinkedSemanticProgram)
    assert program.entry_module == ("main",)


def test_cli_source_ast_codegen_flag_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(entry), "--source-ast-codegen"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --source-ast-codegen" in captured.err


def test_cli_default_codegen_prunes_dead_duplicate_class_symbols_before_link(
    tmp_path: Path, monkeypatch
) -> None:
    write_project(
        tmp_path,
        {
            "left.nif": """
            export class Box {
                value: i64;
            }
            """,
            "right.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import left;
            import right;

            fn main() -> i64 {
                return 0;
            }
            """,
        },
    )

    out_file = compile_to_asm(monkeypatch, tmp_path / "main.nif", project_root=tmp_path, out_path=tmp_path / "out.s")

    assert out_file.exists()


def test_cli_default_codegen_prunes_dead_declarations_from_assembly(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;

            static fn make(value: i64) -> Box {
                return Box(value);
            }

            fn read() -> i64 {
                return __self.value;
            }

            fn dead() -> i64 {
                return 99;
            }
        }

        fn helper() -> i64 {
            return 1;
        }

        fn dead_helper() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            var box: Box = Box.make(helper());
            return box.read();
        }
        """,
    )

    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert "dead_helper:" not in asm
    assert "__nif_method_Box_dead:" not in asm
    assert "helper:" in asm
    assert "__nif_method_Box_make:" in asm
    assert "__nif_method_Box_read:" in asm
