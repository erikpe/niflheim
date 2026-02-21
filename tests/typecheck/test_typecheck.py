import pytest

from compiler.lexer import lex
from compiler.parser import parse
from compiler.typecheck import TypeCheckError, typecheck


def _parse_and_typecheck(source: str) -> None:
    tokens = lex(source)
    module = parse(tokens)
    typecheck(module)


def test_typecheck_primitives_and_references_ok() -> None:
    source = """
class Person {
    name: Str;
    age: i64;

    fn birthday(years: i64) -> i64 {
        return years;
    }
}

fn main() -> unit {
    var x: i64 = 5;
    var y: i64 = 7;
    var z: i64 = x + y;
    var p: Person = Person("Ada", 30);
    var maybe: Person = null;
    if z > 0 {
        var next: i64 = p.birthday(1);
        var ok: bool = next == 1;
    }
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_non_bool_condition() -> None:
    source = """
fn main() -> unit {
    if 1 {
        return;
    }
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'bool', got 'i64'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_reference_to_primitive_assignment() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var p: Person = Person(42);
    var n: i64 = p;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'Person' to 'i64'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_primitive_to_reference_assignment() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var p: Person = 1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'Person'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_wrong_return_type() -> None:
    source = """
fn f() -> i64 {
    return true;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_double_modulo_operator() -> None:
    source = """
fn main() -> unit {
    var x: double = 7.5;
    var y: double = 2.0;
    var z: double = x % y;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Operator '%' is not supported for 'double'"):
        _parse_and_typecheck(source)


def test_typecheck_allows_explicit_primitive_casts() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 7;
    var y: double = (double)x;
    var z: u8 = (u8)x;
    var b: bool = (bool)x;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_u_suffix_integer_literal_is_u64() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 42u;
    var y: u64 = x + 1u;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_assigning_u_suffix_literal_to_i64() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 42u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'u64' to 'i64'"):
        _parse_and_typecheck(source)


def test_typecheck_allows_obj_upcast_and_explicit_downcast() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var p: Person = Person(1);
    var o0: Obj = p;
    var o: Obj = (Obj)p;
    var p2: Person = (Person)o;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_null_cast_to_reference() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var p: Person = (Person)null;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'null' to 'Person'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_obj_assignment_without_downcast() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var o: Obj = Person(1);
    var p: Person = o;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'Obj' to 'Person'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_unrelated_reference_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var p: Person = Person(1);
    var s: Str = (Str)p;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'Person' to 'Str'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_casts_involving_unit() -> None:
    source = """
fn main() -> unit {
    var x: i64 = (i64)(unit)0;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Casts involving 'unit' are not allowed"):
        _parse_and_typecheck(source)


def test_typecheck_allows_provably_null_field_and_method_deref_at_compile_time() -> None:
    source = """
class Person {
    age: i64;

    fn birthday(years: i64) -> i64 {
        return years;
    }
}

fn main() -> unit {
    var p: Person = null;
    var age: i64 = p.age;
    var next: i64 = p.birthday(1);
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_allows_provably_null_index_deref_at_compile_time() -> None:
    source = """
fn main() -> unit {
    var v: Vec = null;
    var x: Obj = v[0];

    var m: Map = null;
    var y: Obj = m[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_str_index_returns_u8() -> None:
    source = """
fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_str_index() -> None:
    source = """
fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s[true];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_assignment_through_str_index() -> None:
    source = """
fn main() -> unit {
    var s: Str = "A";
    s[0] = (u8)66;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Str is immutable"):
        _parse_and_typecheck(source)


def test_typecheck_allows_builtin_box_constructors_and_value_field_reads() -> None:
    source = """
fn main() -> unit {
    var a: BoxI64 = BoxI64(7);
    var b: BoxU64 = BoxU64((u64)9);
    var c: BoxU8 = BoxU8((u8)255);
    var d: BoxBool = BoxBool(true);

    var av: i64 = a.value;
    var bv: u64 = b.value;
    var cv: u8 = c.value;
    var dv: bool = d.value;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_assignment_through_box_value_field() -> None:
    source = """
fn main() -> unit {
    var a: BoxI64 = BoxI64(7);
    a.value = 9;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Box instances are immutable"):
        _parse_and_typecheck(source)


def test_typecheck_allows_builtin_vec_constructor_and_methods() -> None:
    source = """
fn main() -> unit {
    var v: Vec = Vec();
    v.push(BoxI64(1));
    var n: i64 = v.len();
    var x: Obj = v.get(0);
    v.set(0, x);
    var y: Obj = v[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_vec_push_non_obj_argument() -> None:
    source = """
fn main() -> unit {
    var v: Vec = Vec();
    v.push(1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'Obj'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_non_unit_function_missing_return_path() -> None:
    source = """
fn f(x: i64) -> i64 {
    if x > 0 {
        return 1;
    }
}
"""
    with pytest.raises(TypeCheckError, match="Non-unit function must return on all paths"):
        _parse_and_typecheck(source)


def test_typecheck_allows_non_unit_function_when_if_else_both_return() -> None:
    source = """
fn f(x: i64) -> i64 {
    if x > 0 {
        return 1;
    } else {
        return 2;
    }
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_assignment_to_function_symbol() -> None:
    source = """
fn f() -> i64 {
    return 1;
}

fn main() -> unit {
    f = 2;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid assignment target"):
        _parse_and_typecheck(source)


def test_typecheck_allows_call_to_extern_function() -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn main() -> unit {
    var x: Obj = null;
    rt_gc_collect(x);
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_extern_call_with_wrong_argument_type() -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn main() -> unit {
    rt_gc_collect(1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'Obj'"):
        _parse_and_typecheck(source)
