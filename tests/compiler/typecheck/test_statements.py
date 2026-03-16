import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import _parse_and_typecheck


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


def test_typecheck_rejects_duplicate_local_name_across_non_overlapping_blocks() -> None:
    source = """
fn main() -> unit {
    for line in i64[](0u) {
        var x: i64 = 1;
    }

    var line: i64 = 2;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate local variable 'line'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_for_in_element_name_in_same_function() -> None:
    source = """
fn main() -> unit {
    for item in i64[](0u) {
    }
    for item in i64[](0u) {
    }
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate local variable 'item'"):
        _parse_and_typecheck(source)


def test_typecheck_allows_break_continue_inside_while() -> None:
    source = """
fn main() -> unit {
    var i: i64 = 0;
    while i < 10 {
        i = i + 1;
        if i == 3 {
            continue;
        }
        if i == 7 {
            break;
        }
    }
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_break_outside_while() -> None:
    source = """
fn main() -> unit {
    break;
}
"""
    with pytest.raises(TypeCheckError, match="'break' is only allowed inside while loops"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_continue_outside_while() -> None:
    source = """
fn main() -> unit {
    continue;
}
"""
    with pytest.raises(TypeCheckError, match="'continue' is only allowed inside while loops"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_wrong_return_type() -> None:
    source = """
fn f() -> i64 {
    return true;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
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


def test_typecheck_allows_implicit___self_in_method_body() -> None:
    source = """
class Str {
    fn index_get(index: i64) -> u8 {
        return 0u8;
    }
}

fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s.index_get(0);
    return;
}
"""
    _parse_and_typecheck(source)