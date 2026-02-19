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
