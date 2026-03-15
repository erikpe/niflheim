from __future__ import annotations

from pathlib import Path

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
