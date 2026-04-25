from __future__ import annotations

import json
from pathlib import Path

import compiler.cli as cli

from tests.compiler.integration.helpers import run_cli, write


def test_cli_stop_after_backend_ir_prints_text_dump_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
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
        raise AssertionError("assembly emission should not run when stopping after backend-ir")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--stop-after", "backend-ir"])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.err == ""
    assert captured.out.startswith("backend_ir niflheim.backend-ir.v1 entry=main::main\n")


def test_cli_stop_after_backend_ir_can_print_json_dump(tmp_path: Path, monkeypatch, capsys) -> None:
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
        raise AssertionError("assembly emission should not run when stopping after backend-ir")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--stop-after", "backend-ir", "--dump-backend-ir", "json"],
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert captured.err == ""
    assert payload["schema_version"] == "niflheim.backend-ir.v1"
    assert payload["entry_callable_id"]["name"] == "main"
    assert payload["callables"][0]["callable_id"]["name"] == "main"


def test_cli_dump_backend_ir_dir_defaults_to_text_and_continues_to_codegen(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    dump_dir = tmp_path / "ir"
    asm_path = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    lower_calls = {"count": 0}
    real_lower_to_backend_ir = cli.lower_to_backend_ir

    def _counting_lower_to_backend_ir(program):
        lower_calls["count"] += 1
        return real_lower_to_backend_ir(program)

    monkeypatch.setattr(cli, "lower_to_backend_ir", _counting_lower_to_backend_ir)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--dump-backend-ir-dir", str(dump_dir), "-o", str(asm_path)])

    dump_path = dump_dir / "main.backend-ir.txt"
    assert rc == 0
    assert lower_calls["count"] == 1
    assert dump_path.exists()
    assert dump_path.read_text(encoding="utf-8").startswith("backend_ir niflheim.backend-ir.v1 entry=main::main\n")
    assert asm_path.exists()


def test_cli_stop_after_backend_ir_can_write_json_dump_file(tmp_path: Path, monkeypatch, capsys) -> None:
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
        raise AssertionError("assembly emission should not run when stopping after backend-ir")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    rc = run_cli(
        monkeypatch,
        [
            "nifc",
            str(entry),
            "--stop-after",
            "backend-ir",
            "--dump-backend-ir",
            "json",
            "--dump-backend-ir-dir",
            str(dump_dir),
        ],
    )
    captured = capsys.readouterr()
    dump_path = dump_dir / "main.backend-ir.json"

    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""
    payload = json.loads(dump_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "niflheim.backend-ir.v1"
    assert payload["entry_callable_id"]["name"] == "main"
