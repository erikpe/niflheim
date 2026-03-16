import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


def test_typecheck_rejects_field_method_name_collision() -> None:
    source = """
class Bad {
    value: i64;

    fn value() -> i64 {
        return 1;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate member 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_class_and_function_declaration_name() -> None:
    source = """
class Counter {
    value: i64;
}

fn Counter() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate declaration 'Counter'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_field_names() -> None:
    source = """
class Counter {
    value: i64;
    value: bool;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate field 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_method_names() -> None:
    source = """
class Counter {
    fn tick() -> unit {
        return;
    }

    fn tick() -> unit {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate method 'tick'"):
        parse_and_typecheck(source)


def test_typecheck_allows_public_implicit_constructor_for_public_final_fields() -> None:
    source = """
class BoxI64 {
    final value: i64;
}

fn main() -> unit {
    var b: BoxI64 = BoxI64(7);
    var x: i64 = b.value;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_constructor_omits_default_initialized_fields_from_params() -> None:
    source = """
class Counter {
    value: i64;
    cached: bool = false;
}

fn main() -> unit {
    var c: Counter = Counter(7);
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_constructor_call_including_defaulted_field_argument() -> None:
    source = """
class Counter {
    value: i64;
    cached: bool = false;
}

fn main() -> unit {
    var c: Counter = Counter(7, true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 1 arguments, got 2"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_constant_class_field_initializer() -> None:
    source = """
fn seed() -> i64 {
    return 1;
}

class Counter {
    value: i64 = seed();
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Class field initializer must be a constant expression in MVP"):
        parse_and_typecheck(source)
