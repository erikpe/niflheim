from pathlib import Path

import pytest

from compiler.resolver import resolve_program
from compiler.typecheck import typecheck_program
from compiler.typecheck_model import TypeCheckError

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


def test_typecheck_program_allows_unqualified_imported_exported_class_as_type(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
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
            var c: Counter = util.Counter(1);
            var x: i64 = c.inc(2);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_type(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "model.nif",
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
        import model;

        fn main() -> unit {
            var c: Counter = util.Counter(1);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported type 'Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_qualified_type_annotation_with_local_shadow(tmp_path: Path) -> None:
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

        class Counter {
            value: i64;
        }

        fn main() -> unit {
            var c1: util.Counter = util.Counter(1);
            var c2: Counter = Counter(2);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_qualified_type_annotation_for_non_exported_class(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        class Hidden {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var h: util.Hidden = null;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="has no exported class 'Hidden'"):
        typecheck_program(program)


def test_typecheck_program_rejects_assigning_local_class_to_qualified_imported_class_type(tmp_path: Path) -> None:
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

        class Counter {
            value: i64;
        }

        fn main() -> unit {
            var c1: util.Counter = util.Counter(1);
            var c2: Counter = Counter(2);
            c1 = c2;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'Counter' to 'util::Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_constructor_when_unique(tmp_path: Path) -> None:
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
            var c: Counter = Counter(1);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_constructor(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "model.nif",
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
        import model;

        fn main() -> unit {
            var c: Obj = Counter(1);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported type 'Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_function_when_unique(tmp_path: Path) -> None:
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
            var x: i64 = add(20, 3);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_function(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    _write(
        tmp_path / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a - b;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;
        import math;

        fn main() -> unit {
            var x: i64 = add(1, 2);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported function 'add'"):
        typecheck_program(program)


def test_typecheck_program_imported_std_str_methods_on_unqualified_str(tmp_path: Path) -> None:
    _write(
        tmp_path / "std" / "str.nif",
        """
        export class Str {
            fn strip() -> Str {
                return __self;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import std.str;

        fn main() -> unit {
            var s: Str = "Hello world!";
            var t: Str = s.strip();
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)
