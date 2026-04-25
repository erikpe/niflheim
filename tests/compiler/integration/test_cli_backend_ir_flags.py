from __future__ import annotations

from pathlib import Path

import pytest

from tests.compiler.integration.helpers import run_cli, write


def test_cli_help_lists_reserved_backend_ir_flags(monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", "-h"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 0
    assert "--dump-backend-ir {text,json}" in captured.out
    assert "--dump-backend-ir-dir DIR" in captured.out
    assert "backend-ir" in captured.out
    assert "backend-ir-passes" in captured.out


@pytest.mark.parametrize(
    ("extra_args", "expected_markers"),
    [
        (["--dump-backend-ir", "text"], ["--dump-backend-ir"]),
        (["--dump-backend-ir", "json", "--dump-backend-ir-dir", "ir-out"], ["--dump-backend-ir", "--dump-backend-ir-dir"]),
        (["--stop-after", "backend-ir"], ["--stop-after backend-ir"]),
        (["--stop-after", "backend-ir-passes"], ["--stop-after backend-ir-passes"]),
    ],
)
def test_cli_backend_ir_surface_is_reserved(
    tmp_path: Path, monkeypatch, capsys, extra_args: list[str], expected_markers: list[str]
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

    rc = run_cli(monkeypatch, ["nifc", str(entry), *extra_args])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Backend IR CLI surface is reserved for phase 2" in captured.err
    assert "backend lowering is not wired into the checked compiler path yet" in captured.err
    assert "unsupported request(s):" in captured.err
    assert "Phase 1 only freezes the flag names and stop phases." in captured.err
    for marker in expected_markers:
        assert marker in captured.err
