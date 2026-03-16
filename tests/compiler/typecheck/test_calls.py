import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import _parse_and_typecheck


def test_typecheck_allows_static_method_class_call() -> None:
    source = """
class Counter {
    static fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }
}

fn main() -> i64 {
    return Counter.add(2, 3);
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_static_method_called_on_instance() -> None:
    source = """
class Counter {
    static fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }
}

fn main() -> i64 {
    var c: Counter = null;
    return c.add(2, 3);
}
"""
    with pytest.raises(TypeCheckError, match="Static method 'Counter.add' must be called on the class"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_instance_method_called_on_class() -> None:
    source = """
class Counter {
    fn add(delta: i64) -> i64 {
        return delta;
    }
}

fn main() -> i64 {
    return Counter.add(3);
}
"""
    with pytest.raises(TypeCheckError, match="Method 'Counter.add' is not static"):
        _parse_and_typecheck(source)


def test_typecheck_allows_top_level_function_value_and_indirect_call() -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = add;
    return f(20, 22);
}
"""
    _parse_and_typecheck(source)


def test_typecheck_allows_static_method_value_and_indirect_call() -> None:
    source = """
class Math {
    static fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = Math.add;
    return f(20, 22);
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_instance_method_value_in_mvp() -> None:
    source = """
class Math {
    fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }
}

fn main() -> unit {
    var m: Math = Math();
    var f: fn(i64, i64) -> i64 = m.add;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Instance methods are not first-class values in MVP"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_function_value_assignment_type_mismatch() -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> unit {
    var f: fn(i64) -> i64 = add;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Cannot assign 'fn\(i64, i64\) -> i64' to 'fn\(i64\) -> i64'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_indirect_call_argument_type_mismatch() -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = add;
    return f(true, 1);
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        _parse_and_typecheck(source)


def test_typecheck_allows_direct_callable_field_invocation() -> None:
    source = """
fn inc(v: i64) -> i64 {
    return v + 1;
}

class Holder {
    f: fn(i64) -> i64;

    fn run(v: i64) -> i64 {
        return __self.f(v);
    }
}

fn main() -> i64 {
    var h: Holder = Holder(inc);
    return h.run(41);
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_direct_call_on_non_callable_field() -> None:
    source = """
class Box {
    value: i64;

    fn bad() -> i64 {
        return __self.value();
    }
}

fn main() -> i64 {
    var b: Box = Box(1);
    return b.bad();
}
"""
    with pytest.raises(TypeCheckError, match="Expression of type 'i64' is not callable"):
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


def test_typecheck_allows_box_class_constructors_and_value_getters() -> None:
    source = """
class BoxI64 {
    final _value: i64;

    fn value() -> i64 {
        return __self._value;
    }
}

class BoxU64 {
    final _value: u64;

    fn value() -> u64 {
        return __self._value;
    }
}

class BoxU8 {
    final _value: u8;

    fn value() -> u8 {
        return __self._value;
    }
}

class BoxBool {
    final _value: bool;

    fn value() -> bool {
        return __self._value;
    }
}

fn main() -> unit {
    var a: BoxI64 = BoxI64(7);
    var b: BoxU64 = BoxU64((u64)9);
    var c: BoxU8 = BoxU8((u8)255);
    var d: BoxBool = BoxBool(true);

    var av: i64 = a.value();
    var bv: u64 = b.value();
    var cv: u8 = c.value();
    var dv: bool = d.value();
    return;
}
"""
    _parse_and_typecheck(source)