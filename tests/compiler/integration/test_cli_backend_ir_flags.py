from __future__ import annotations

from pathlib import Path

import pytest

import compiler.cli as cli

from tests.compiler.integration.helpers import run_cli, write


def test_cli_help_lists_backend_ir_flags(monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", "-h"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 0
    assert "--dump-backend-ir {text,json}" in captured.out
    assert "--dump-backend-ir-dir DIR" in captured.out
    assert "backend-ir" in captured.out
    assert "backend-ir-passes" in captured.out


def test_cli_backend_ir_dump_requires_directory_when_continuing_to_codegen(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--dump-backend-ir", "text"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Continuing past backend IR with --dump-backend-ir requires --dump-backend-ir-dir" in captured.err


def test_cli_backend_ir_passes_stop_phase_is_available(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen = {"pipeline_calls": 0}
    real_run_backend_ir_pipeline = cli.run_backend_ir_pipeline

    def _counting_pipeline(program):
        seen["pipeline_calls"] += 1
        return real_run_backend_ir_pipeline(program)

    monkeypatch.setattr(cli, "run_backend_ir_pipeline", _counting_pipeline)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--stop-after", "backend-ir-passes"])
    captured = capsys.readouterr()

    assert rc == 0
    assert seen["pipeline_calls"] == 1
    assert captured.err == ""
    assert captured.out.startswith("backend_ir niflheim.backend-ir.v1 entry=main::main\n")
