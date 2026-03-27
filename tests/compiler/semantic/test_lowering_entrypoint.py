from __future__ import annotations

import compiler.semantic.lowering as lowering
from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import build_checked_program, lower_checked_program, lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_lowering_package_does_not_reexport_lower_program() -> None:
    assert not hasattr(lowering, "lower_program")


def test_lower_checked_program_matches_lower_program(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn main(x: i64) -> i64 {
            var total: i64 = x;
            return total;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    checked_program = build_checked_program(program)

    assert lower_checked_program(checked_program) == lower_program(program)
