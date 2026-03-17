from __future__ import annotations

from pathlib import Path

import compiler.cli as cli

from compiler.semantic_linker import SemanticCodegenProgram
from tests.compiler.integration.helpers import run_cli, write


def test_cli_defaults_to_semantic_codegen_path(tmp_path: Path, monkeypatch) -> None:
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

    def _unexpected_old_backend(*_args, **_kwargs):
        raise AssertionError("old AST backend should not be used by default")

    def _fake_emit_semantic_asm(semantic_program: SemanticCodegenProgram) -> str:
        seen["semantic_program"] = semantic_program
        return "; semantic backend selected\n"

    monkeypatch.setattr(cli, "build_codegen_module", _unexpected_old_backend)
    monkeypatch.setattr(cli, "emit_semantic_asm", _fake_emit_semantic_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; semantic backend selected\n"
    semantic_program = seen["semantic_program"]
    assert isinstance(semantic_program, SemanticCodegenProgram)
    assert semantic_program.entry_module == ("main",)


def test_cli_source_ast_codegen_flag_selects_legacy_backend(tmp_path: Path, monkeypatch) -> None:
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

    def _fake_build_codegen_module(program) -> object:
        seen["program"] = program
        return program.modules[program.entry_module].ast

    def _unexpected_semantic_backend(*_args, **_kwargs):
        raise AssertionError("semantic backend should not be used when --source-ast-codegen is set")

    def _fake_emit_asm(_module_ast) -> str:
        seen["emit_asm"] = True
        return "; legacy backend selected\n"

    monkeypatch.setattr(cli, "build_codegen_module", _fake_build_codegen_module)
    monkeypatch.setattr(cli, "emit_semantic_asm", _unexpected_semantic_backend)
    monkeypatch.setattr(cli, "emit_asm", _fake_emit_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--source-ast-codegen", "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; legacy backend selected\n"
    assert seen["emit_asm"] is True
    assert "program" in seen
