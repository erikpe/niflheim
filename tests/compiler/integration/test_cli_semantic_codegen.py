from __future__ import annotations

from pathlib import Path

import compiler.cli as cli

from compiler.semantic_ir import SemanticProgram
from tests.compiler.integration.helpers import run_cli, write


def test_cli_semantic_codegen_flag_selects_lowered_program_path(tmp_path: Path, monkeypatch) -> None:
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
        raise AssertionError("old AST backend should not be used when --semantic-codegen is set")

    def _fake_emit_semantic_asm(semantic_program: SemanticProgram) -> str:
        seen["semantic_program"] = semantic_program
        return "; semantic backend selected\n"

    monkeypatch.setattr(cli, "build_codegen_module", _unexpected_old_backend)
    monkeypatch.setattr(cli, "emit_semantic_asm", _fake_emit_semantic_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--semantic-codegen", "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; semantic backend selected\n"
    semantic_program = seen["semantic_program"]
    assert isinstance(semantic_program, SemanticProgram)
    assert semantic_program.entry_module == ("main",)
