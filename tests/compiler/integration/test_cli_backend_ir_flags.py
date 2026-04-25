from __future__ import annotations

from pathlib import Path

import pytest

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


def test_cli_backend_ir_passes_stop_phase_remains_reserved(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--stop-after", "backend-ir-passes"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Backend IR passes are not wired into the checked compiler path yet" in captured.err
    assert "--stop-after backend-ir-passes remains reserved for phase 3." in captured.err
