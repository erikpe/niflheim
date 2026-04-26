from __future__ import annotations

import json
from pathlib import Path

import compiler.cli as cli

from tests.compiler.integration.helpers import run_cli, write


def test_cli_stop_after_backend_ir_passes_prints_text_dump_and_runs_pipeline(
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

    seen = {"pipeline_calls": 0}
    real_run_backend_ir_pipeline = cli.run_backend_ir_pipeline

    def _counting_pipeline(program):
        seen["pipeline_calls"] += 1
        return real_run_backend_ir_pipeline(program)

    def _unexpected_emit_asm(*args, **kwargs):
        raise AssertionError("assembly emission should not run when stopping after backend-ir-passes")

    monkeypatch.setattr(cli, "run_backend_ir_pipeline", _counting_pipeline)
    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--stop-after", "backend-ir-passes"])
    captured = capsys.readouterr()

    assert rc == 0
    assert seen["pipeline_calls"] == 1
    assert captured.err == ""
    assert captured.out.startswith("backend_ir niflheim.backend-ir.v1 entry=main::main\n")


def test_cli_stop_after_backend_ir_passes_can_print_json_dump(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_emit_asm(*args, **kwargs):
        raise AssertionError("assembly emission should not run when stopping after backend-ir-passes")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--stop-after", "backend-ir-passes", "--dump-backend-ir", "json"],
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert captured.err == ""
    assert payload["schema_version"] == "niflheim.backend-ir.v1"
    assert payload["entry_callable_id"]["name"] == "main"


def test_cli_stop_after_backend_ir_passes_can_write_dump_file(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    dump_dir = tmp_path / "ir"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_emit_asm(*args, **kwargs):
        raise AssertionError("assembly emission should not run when stopping after backend-ir-passes")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(
        monkeypatch,
        [
            "nifc",
            str(entry),
            "--stop-after",
            "backend-ir-passes",
            "--dump-backend-ir-dir",
            str(dump_dir),
        ],
    )
    captured = capsys.readouterr()
    dump_path = dump_dir / "main.backend-ir.txt"

    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""
    assert dump_path.exists()
    assert dump_path.read_text(encoding="utf-8").startswith("backend_ir niflheim.backend-ir.v1 entry=main::main\n")


def test_cli_default_codegen_does_not_invoke_backend_ir_pipeline_without_backend_ir_flags(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    asm_path = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_pipeline(*args, **kwargs):
        raise AssertionError("backend IR pass pipeline should not run on the default checked codegen path")

    monkeypatch.setattr(cli, "run_backend_ir_pipeline", _unexpected_pipeline)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(asm_path)])

    assert rc == 0
    assert asm_path.exists()