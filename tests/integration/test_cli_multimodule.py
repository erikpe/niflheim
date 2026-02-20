from __future__ import annotations

import sys
from pathlib import Path

from compiler.cli import main


def test_cli_uses_program_resolution_for_multimodule_build(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "util.nif").write_text(
        """
export class Box {
    value: i64;
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import util;

fn main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "out.s"
    monkeypatch.setattr(sys, "argv", ["nifc", str(entry), "-o", str(out_file)])

    rc = main()
    assert rc == 0
    assert out_file.exists()


def test_cli_reports_missing_import_module(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import missing.mod;

fn main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["nifc", str(entry)])

    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Module 'missing.mod' not found" in captured.err


def test_cli_requires_main_i64_entrypoint(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
fn not_main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["nifc", str(source)])
    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Program entrypoint missing" in captured.err
