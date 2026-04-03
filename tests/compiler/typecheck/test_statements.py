import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


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
        parse_and_typecheck(source)


def test_typecheck_allows_shadowing_param_and_outer_local_in_nested_blocks() -> None:
    source = """
fn main(value: i64) -> i64 {
    var total: i64 = value;
    {
        var value: i64 = 7;
        total = total + value;
    }
    return total;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_shadowing_outer_local_in_for_in_loop() -> None:
    source = """
fn main() -> unit {
    var item: i64 = 9;
    for item in i64[](1u) {
    }
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_local_name_in_same_block() -> None:
    source = """
fn main() -> unit {
    var value: i64 = 1;
    var value: i64 = 2;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate local variable 'value'"):
        parse_and_typecheck(source)


def test_typecheck_reports_original_source_name_for_unknown_identifier() -> None:
    source = """
fn main() -> i64 {
    var total: i64 = 1;
    return missing;
}
"""
    with pytest.raises(TypeCheckError, match="Unknown identifier 'missing'"):
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


def test_typecheck_rejects_break_outside_while() -> None:
    source = """
fn main() -> unit {
    break;
}
"""
    with pytest.raises(TypeCheckError, match="'break' is only allowed inside while loops"):
        parse_and_typecheck(source)


def test_typecheck_rejects_continue_outside_while() -> None:
    source = """
fn main() -> unit {
    continue;
}
"""
    with pytest.raises(TypeCheckError, match="'continue' is only allowed inside while loops"):
        parse_and_typecheck(source)


def test_typecheck_rejects_wrong_return_type() -> None:
    source = """
fn f() -> i64 {
    return true;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_bare_return_in_non_unit_function() -> None:
    source = """
fn f() -> i64 {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Non-unit function must return a value"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_unit_function_missing_return_path() -> None:
    source = """
fn f(x: i64) -> i64 {
    if x > 0 {
        return 1;
    }
}
"""
    with pytest.raises(TypeCheckError, match="Non-unit function must return on all paths"):
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


def test_typecheck_allows_implicit___self_in_constructor_body() -> None:
    source = """
class Counter {
    value: i64;

    constructor(value: i64) {
        __self.value = value;
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }
}

fn main() -> unit {
    var c: Counter = Counter(7);
    var value: i64 = c.read();
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_value_return_in_constructor_body() -> None:
    source = """
class Counter {
    constructor() {
        return 1;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Constructors cannot return a value"):
        parse_and_typecheck(source)


def test_typecheck_rejects_missing_required_field_initialization_in_constructor() -> None:
    source = """
class Counter {
    value: i64;

    constructor() {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Constructor for class 'Counter' does not initialize field 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assignment_to_inherited_final_field() -> None:
    source = """
class Base {
    final value: i64;
}

class Derived extends Base {
    fn bump() -> unit {
        __self.value = 2;
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Field 'Base.value' is final"):
        parse_and_typecheck(source)


def test_typecheck_allows_subclass_constructor_super_chaining() -> None:
    source = """
class Base {
    value: i64;
}

class Derived extends Base {
    extra: i64;

    constructor(value: i64, extra: i64) {
        super(value);
        __self.extra = extra;
        return;
    }
}

fn main() -> unit {
    var derived: Derived = Derived(1, 2);
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_subclass_constructor_missing_first_super_call() -> None:
    source = """
class Base {
    value: i64;
}

class Derived extends Base {
    extra: i64;

    constructor(value: i64, extra: i64) {
        __self.extra = extra;
        super(value);
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Subclass constructor must begin with super\(\.\.\.\)"):
        parse_and_typecheck(source)


def test_typecheck_rejects_direct_inherited_field_initialization_in_subclass_constructor() -> None:
    source = """
class Base {
    value: i64;
}

class Derived extends Base {
    extra: i64;

    constructor(value: i64, extra: i64) {
        super(value);
        __self.value = value;
        __self.extra = extra;
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Inherited field 'Base.value' must be initialized via super\(\.\.\.\)"):
        parse_and_typecheck(source)


def test_typecheck_allows_single_assignment_to_final_field_in_constructor() -> None:
    source = """
class Counter {
    final value: i64;

    constructor(value: i64) {
        __self.value = value;
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    return c.read();
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_double_assignment_to_final_field_in_constructor() -> None:
    source = """
class Counter {
    final value: i64;

    constructor(value: i64) {
        __self.value = value;
        __self.value = value;
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Final field 'Counter.value' may be assigned multiple times in constructor"):
        parse_and_typecheck(source)
