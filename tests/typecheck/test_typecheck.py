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
