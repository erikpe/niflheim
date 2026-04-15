from pathlib import Path

import pytest

from compiler.resolver import ResolveError
from compiler.typecheck.api import typecheck_program
from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import resolve_program_from_main, write


def test_typecheck_program_allows_imported_function_and_class_usage(tmp_path: Path) -> None:
    write(
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
    write(
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

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_full_path_qualified_usage_for_dotted_import(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math;

        fn main() -> unit {
            var n: i64 = util.math.add(1, 2);
            var c: Obj = util.math.Counter(10);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_explicit_import_alias_qualification(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math as math;

        fn main() -> unit {
            var n: i64 = math.add(1, 2);
            var c: Obj = math.Counter(10);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_keeps_legacy_leaf_alias_qualification_during_alias_migration(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math;

        fn main() -> unit {
            var n: i64 = math.add(1, 2);
            var c: Obj = math.Counter(10);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Unknown identifier 'math'"):
        typecheck_program(program)


def test_typecheck_program_rejects_plain_import_leaf_alias_in_type_annotations(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math;

        fn main() -> unit {
            var c: math.Counter = util.math.Counter(10);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Unknown type 'math.Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_imported_function_value(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var f: fn(i64, i64) -> i64 = util.add;
            return f(20, 22);
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_imported_static_method_value(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var f: fn(i64, i64) -> i64 = util.Math.add;
            return f(20, 22);
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_imported_interface_annotations_and_assignment(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn echo(value: Hashable) -> util.Hashable {
            return value;
        }

        fn main() -> unit {
            var h: Hashable = util.Key();
            var q: util.Hashable = echo(h);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_imported_superclass_reference(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Base {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        export class Derived extends util.Base {
            extra: i64;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_imported_base_subtyping_and_inherited_members(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Base implements Hashable {
            value: i64 = 7;

            fn read() -> i64 {
                return __self.value;
            }

            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        class Derived extends util.Base {
            extra: i64 = 1;
        }

        fn main() -> unit {
            var d: Derived = Derived();
            var b: util.Base = d;
            var h: util.Hashable = d;
            var r: i64 = d.read();
            var casted: util.Base = (util.Base)d;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_imported_inheritance_cycle(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        import main;

        export class Base extends main.Derived {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        export class Derived extends util.Base {
            extra: i64;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Inheritance cycle detected"):
        typecheck_program(program)


def test_typecheck_program_rejects_private_member_access_across_modules(tmp_path: Path) -> None:
    write(
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
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var c: Counter = util.Counter.make(1);
            return c.value;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
        typecheck_program(program)


def test_typecheck_program_rejects_private_method_call_across_modules(tmp_path: Path) -> None:
    write(
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
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var c: Counter = util.Counter.make();
            return c.hidden();
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Member 'Counter.hidden' is private"):
        typecheck_program(program)


def test_typecheck_program_rejects_bad_imported_function_argument_type(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var n: i64 = util.add(true, 2);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        typecheck_program(program)


def test_typecheck_program_allows_imported_std_vec_with_index_and_slice_sugar(tmp_path: Path) -> None:
    write(
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

            fn index_get(index: i64) -> Obj {
                return __self.values[index];
            }

            fn index_set(index: i64, value: Obj) -> unit {
                __self.values[index] = value;
                return;
            }

            fn slice_get(begin: i64, end: i64) -> Vec {
                return __self;
            }
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_bad_imported_constructor_argument_type(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: Obj = util.Counter(true);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        typecheck_program(program)


def test_typecheck_program_rejects_private_implicit_constructor_call_across_modules(tmp_path: Path) -> None:
    write(
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
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var a: Counter = util.Counter.make(1);
            var b: Counter = util.Counter(2);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Constructor for class 'Counter' is private"):
        typecheck_program(program)


def test_typecheck_program_allows_imported_overloaded_constructor_resolution(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        export class Sink {
            private constructor(value: Obj) {
                return;
            }

            constructor(value: Key) {
                return;
            }
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var s: Sink = Sink(Key());
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_imported_public_implicit_constructor_with_final_field(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class BoxI64 {
            final value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var b: BoxI64 = util.BoxI64(7);
            var x: i64 = b.value;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_exported_class_as_type(tmp_path: Path) -> None:
    write(
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
    write(
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

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_class_static_method_call(tmp_path: Path) -> None:
    write(
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
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: Counter = Counter.from_i64(7);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_type(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "model.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported type 'Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_qualified_type_annotation_with_local_shadow(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_qualified_type_annotation_for_non_exported_class(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        class Hidden {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var h: util.Hidden = null;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="has no exported class 'Hidden'"):
        typecheck_program(program)


def test_typecheck_program_rejects_assigning_local_class_to_qualified_imported_class_type(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Cannot assign 'Counter' to 'util::Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_constructor_when_unique(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: Counter = Counter(1);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_constructor(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "model.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported type 'Counter'"):
        typecheck_program(program)


def test_typecheck_program_allows_array_types_for_unqualified_and_qualified_imported_class(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var a: Counter[] = Counter[](2u);
            var b: util.Counter[] = a;
            b[0] = util.Counter(1);
            var x: util.Counter = b.index_get(0);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_unqualified_imported_function_when_unique(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var x: i64 = add(20, 3);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_ambiguous_unqualified_imported_function(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a - b;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Ambiguous imported function 'add'"):
        typecheck_program(program)


def test_typecheck_program_imported_std_str_methods_on_unqualified_str(tmp_path: Path) -> None:
    write(
        tmp_path / "std" / "str.nif",
        """
        export class Str {
            fn strip() -> Str {
                return __self;
            }
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_imported_std_str_from_char_static_call(tmp_path: Path) -> None:
    write(
        tmp_path / "std" / "str.nif",
        """
        export class Str {
            static fn from_char(value: u8) -> Str {
                return "A";
            }
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import std.str;

        fn main() -> unit {
            var s: Str = Str.from_char('Z');
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_imported_array_equality_with_different_element_types(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
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

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Operator '==' has incompatible operand types"):
        typecheck_program(program)


def test_typecheck_program_allows_access_through_reexported_nested_module(tmp_path: Path) -> None:
    write(
        tmp_path / "pkg" / "inner.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "util.nif",
        """
        export import pkg.inner;
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: util.pkg.inner.Counter = util.pkg.inner.Counter(1);
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_direct_access_without_root_flatten(tmp_path: Path) -> None:
    write(
        tmp_path / "pkg" / "inner.nif",
        """
        export fn score() -> i64 {
            return 42;
        }
        """,
    )
    write(
        tmp_path / "util.nif",
        """
        export import pkg.inner;
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            util.score();
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Module 'util' has no exported member 'score'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_allows_local_plain_import_bind_path_lookup(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn score() -> i64 {
            return 42;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        import util.math as tools.calc;

        export fn total() -> i64 {
            var counter: tools.calc.Counter = tools.calc.Counter(42);
            return tools.calc.score() + counter.value - 42;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var total: i64 = lib.total();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_local_plain_root_flatten_lookup(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "api.nif",
        """
        export import util.math as math;

        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            seed: u64;

            fn hash_code() -> u64 {
                return __self.seed + 500u;
            }
        }

        export fn twice(value: i64) -> i64 {
            return value * 2;
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        import api as .;

        export fn total() -> i64 {
            var key: Key = Key(7u);
            var face: Hashable = key;
            return math.add(19, 23) + twice(0) + (i64)face.hash_code() - 507;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var total: i64 = lib.total();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_plain_root_flatten_import_conflicting_with_local_definition(tmp_path: Path) -> None:
    write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import dep as .;

        fn clash() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate imported symbol 'clash'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_root_flatten_reexport_conflicting_with_local_definition(tmp_path: Path) -> None:
    write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        export import dep as .;

        fn clash() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate exported symbol 'clash'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_import_bind_path_conflicting_with_local_definition(tmp_path: Path) -> None:
    write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import dep as tools.calc;

        fn tools() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate import path 'tools.calc'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_export_import_bind_path_conflicting_with_local_definition(tmp_path: Path) -> None:
    write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        export import dep as tools.calc;

        fn tools() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate exported module 'tools.calc'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_duplicate_export_import_bind_path(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "util" / "ops.nif",
        """
        export fn mul(a: i64, b: i64) -> i64 {
            return a * b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        export import util.math as tools.calc;
        export import util.ops as tools.calc;

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate import path 'tools.calc'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_duplicate_mixed_import_bind_path(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "util" / "ops.nif",
        """
        export fn mul(a: i64, b: i64) -> i64 {
            return a * b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math as tools.calc;
        export import util.ops as tools.calc;

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate import path 'tools.calc'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_rejects_duplicate_same_module_import_bind_path(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math as tools.calc;
        import util.math as tools.calc;

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError, match="Duplicate import path 'tools.calc'"):
        resolve_program_from_main(tmp_path)


def test_typecheck_program_allows_disjoint_multi_root_flatten_plain_imports(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;

            fn inc(delta: i64) -> i64 {
                return __self.value + delta;
            }
        }
        """,
    )
    write(
        tmp_path / "util" / "ops.nif",
        """
        export fn mul(a: i64, b: i64) -> i64 {
            return a * b;
        }

        export class Box {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        import util.math as .;
        import util.ops as .;

        export fn total() -> i64 {
            var counter: Counter = Counter(40);
            var box: Box = Box(0);
            return add(19, 23) + counter.inc(2) + mul(6, 7) + box.read() - 84;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var total: i64 = lib.total();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_disjoint_multi_root_flatten_reexports(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;

            fn inc(delta: i64) -> i64 {
                return __self.value + delta;
            }
        }
        """,
    )
    write(
        tmp_path / "util" / "ops.nif",
        """
        export fn mul(a: i64, b: i64) -> i64 {
            return a * b;
        }

        export class Box {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        export import util.math as .;
        export import util.ops as .;

        export fn total() -> i64 {
            return add(19, 23) + mul(6, 7) - 42;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var n1: i64 = lib.add(19, 23);
            var n2: i64 = lib.mul(6, 7);
            var counter: lib.Counter = lib.Counter(40);
            var box: lib.Box = lib.Box(42);
            var total: i64 = lib.total() + counter.inc(2) + box.read() - 84;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_mixed_multi_root_flatten_import_and_reexport(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        export class Counter {
            value: i64;

            fn inc(delta: i64) -> i64 {
                return __self.value + delta;
            }
        }
        """,
    )
    write(
        tmp_path / "util" / "ops.nif",
        """
        export fn mul(a: i64, b: i64) -> i64 {
            return a * b;
        }

        export class Box {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        import util.math as .;
        export import util.ops as .;

        export fn total() -> i64 {
            var counter: Counter = Counter(40);
            var box: Box = Box(42);
            return add(19, 23) + counter.inc(2) + mul(0, 1) + box.read() - 84;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var n: i64 = lib.mul(6, 7);
            var box: lib.Box = lib.Box(42);
            var total: i64 = lib.total() + n + box.read() - 84;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_access_through_explicit_reexport_path_alias(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn score() -> i64 {
            return 42;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        export import util.math as tools.calc;

        export fn total() -> i64 {
            var counter: tools.calc.Counter = tools.calc.Counter(42);
            return tools.calc.score() + counter.value - 42;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            var total: i64 = lib.tools.calc.score();
            var counter: lib.tools.calc.Counter = lib.tools.calc.Counter(42);
            var same: i64 = lib.total();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_allows_access_through_root_flatten_reexport(tmp_path: Path) -> None:
    write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            seed: u64;

            fn hash_code() -> u64 {
                return __self.seed + 500u;
            }
        }

        export fn score(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    write(
        tmp_path / "lib.nif",
        """
        export import util as .;

        export fn total() -> i64 {
            var key: Key = Key(7u);
            var face: Hashable = key;
            return score(19, 23) + (i64)face.hash_code() - 507;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import lib;

        fn echo(value: Hashable) -> lib.Hashable {
            return value;
        }

        fn main() -> unit {
            var total: i64 = lib.score(19, 23);
            var key: lib.Key = lib.Key(7u);
            var face: Hashable = echo(key);
            var same: i64 = lib.total();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    typecheck_program(program)


def test_typecheck_program_rejects_original_module_path_after_dotted_bind_path(tmp_path: Path) -> None:
    write(
        tmp_path / "util" / "math.nif",
        """
        export fn score() -> i64 {
            return 42;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util.math as tools.calc;

        fn main() -> unit {
            util.math.score();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Unknown identifier 'util'"):
        typecheck_program(program)


def test_typecheck_program_rejects_original_module_path_after_root_flatten_bind(tmp_path: Path) -> None:
    write(
        tmp_path / "api.nif",
        """
        export fn score() -> i64 {
            return 42;
        }
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import api as .;

        fn main() -> unit {
            api.score();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Unknown identifier 'api'"):
        typecheck_program(program)


def test_typecheck_program_rejects_missing_reexported_nested_module_segment(tmp_path: Path) -> None:
    write(
        tmp_path / "pkg" / "inner.nif",
        """
        export class Counter {
            value: i64;
        }
        """,
    )
    write(
        tmp_path / "util.nif",
        """
        export import pkg.inner;
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            var c: util.missing.Counter = null;
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Module 'util' has no exported module 'missing'"):
        typecheck_program(program)


def test_typecheck_program_rejects_calling_reexported_module_value(tmp_path: Path) -> None:
    write(
        tmp_path / "pkg" / "inner.nif",
        """
        export fn make() -> i64 {
            return 1;
        }
        """,
    )
    write(
        tmp_path / "util.nif",
        """
        export import pkg.inner;
        """,
    )
    write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            util.pkg.inner();
            return;
        }
        """,
    )

    program = resolve_program_from_main(tmp_path)
    with pytest.raises(TypeCheckError, match="Module values are not callable"):
        typecheck_program(program)
