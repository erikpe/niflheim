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


def test_typecheck_program_rejects_private_member_access_across_modules(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            private value: i64;

            static fn make(value: i64) -> Counter {
                return Counter(value);
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var c: Counter = util.Counter.make(1);
            return c.value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
        typecheck_program(program)


def test_typecheck_program_rejects_private_method_call_across_modules(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            private fn hidden() -> i64 {
                return 1;
            }

            static fn make() -> Counter {
                return Counter();
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var c: Counter = util.Counter.make();
            return c.hidden();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Member 'Counter.hidden' is private"):
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


def test_typecheck_program_allows_imported_std_vec_with_index_and_slice_sugar(tmp_path: Path) -> None:
    _write(
        tmp_path / "std" / "vec.nif",
        """
        export class Vec {
            values: Obj[];

            static fn new() -> Vec {
                return Vec(Obj[](4u));
            }

            fn len() -> i64 {
                return 4;
            }

            fn get(index: i64) -> Obj {
                return __self.values[index];
            }

            fn set(index: i64, value: Obj) -> unit {
                __self.values[index] = value;
                return;
            }

            fn slice(begin: i64, end: i64) -> Vec {
                return __self;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import std.vec;

        fn main() -> unit {
            var v: Vec = Vec.new();
            v[0] = null;
            var x: Obj = v[-1];
            var s: Vec = v[:];
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
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


def test_typecheck_program_allows_unqualified_imported_class_static_method_call(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            static fn from_i64(value: i64) -> Counter {
                return Counter(value);
            }

            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: Counter = Counter.from_i64(7);
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


def test_typecheck_program_allows_array_types_for_unqualified_and_qualified_imported_class(tmp_path: Path) -> None:
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
            var a: Counter[] = Counter[](2u);
            var b: util.Counter[] = a;
            b[0] = util.Counter(1);
            var x: util.Counter = b.get(0);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
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


def test_typecheck_program_imported_std_newstr_methods_on_unqualified_newstr(tmp_path: Path) -> None:
    _write(
        tmp_path / "std" / "newstr.nif",
        """
        export class NewStr {
            fn strip() -> NewStr {
                return __self;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import std.newstr;

        fn main() -> unit {
            var s: NewStr = "Hello world!";
            var t: NewStr = s.strip();
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_imported_std_newstr_from_char_static_call(tmp_path: Path) -> None:
    _write(
        tmp_path / "std" / "newstr.nif",
        """
        export class NewStr {
            static fn from_char(value: u8) -> NewStr {
                return "A";
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import std.newstr;

        fn main() -> unit {
            var s: NewStr = NewStr.from_char('Z');
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_imported_array_equality_with_different_element_types(tmp_path: Path) -> None:
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
            var counters: util.Counter[] = util.Counter[](1u);
            var objs: Obj[] = Obj[](1u);
            var same: bool = counters == objs;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    with pytest.raises(TypeCheckError, match="Operator '==' has incompatible operand types"):
        typecheck_program(program)
