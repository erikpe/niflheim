from __future__ import annotations

from pathlib import Path

import pytest

from compiler.resolver import resolve_program
from compiler.typecheck import TypeCheckError, typecheck_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_typecheck_program_allows_imported_function_and_class_usage(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;

            fn inc(delta: i64) -> i64 {
                return delta;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var n: i64 = util.add(1, 2);
            var c: Obj = util.Counter(10);
            var m: i64 = util.Counter(1).inc(2);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_bad_imported_function_argument_type(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var n: i64 = util.add(true, 2);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        typecheck_program(program)


def test_typecheck_program_rejects_bad_imported_constructor_argument_type(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: Obj = util.Counter(true);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        typecheck_program(program)
