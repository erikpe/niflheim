from __future__ import annotations

from pathlib import Path

import pytest

from tests.compiler.integration.helpers import run_cli, write


def test_cli_error_reports_missing_import_module(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import missing.mod;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Module 'missing.mod' not found" in captured.err


def test_cli_error_requires_main_i64_entrypoint(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn not_main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(source)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Program entrypoint missing" in captured.err


def test_cli_error_rejects_extern_main_entrypoint(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        extern fn main() -> i64;
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(source)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Invalid main signature: expected concrete definition 'fn main() -> i64'" in captured.err


def test_cli_error_rejects_main_with_parameters(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main(argc: i64) -> i64 {
            return argc;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(source)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Invalid main signature: expected 'fn main() -> i64' (no parameters)" in captured.err


def test_cli_error_rejects_main_with_wrong_return_type(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> unit {
            return;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(source)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Invalid main signature: expected return type 'i64'" in captured.err


def test_cli_error_rejects_removed_source_ast_backend_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--source-ast-codegen"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --source-ast-codegen" in captured.err


def test_cli_error_rejects_removed_semantic_codegen_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--semantic-codegen"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --semantic-codegen" in captured.err


def test_cli_error_rejects_removed_skip_check_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--skip-check"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --skip-check" in captured.err


def test_cli_error_rejects_removed_print_tokens_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--print-tokens"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --print-tokens" in captured.err


def test_cli_error_rejects_removed_print_ast_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--print-ast", "--print-ast-spans"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --print-ast --print-ast-spans" in captured.err


def test_cli_error_rejects_removed_stop_after_parse(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--stop-after", "parse"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "invalid choice: 'parse'" in captured.err


def test_cli_error_rejects_removed_stop_after_lex(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    write(
        source,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(source), "--stop-after", "lex"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "invalid choice: 'lex'" in captured.err
