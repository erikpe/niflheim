import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


def test_typecheck_allows_private_members_inside_declaring_class() -> None:
    source = """
class Counter {
    private value: i64;

    private fn hidden(delta: i64) -> i64 {
        return __self.value + delta;
    }

    fn use_hidden(delta: i64) -> i64 {
        return __self.hidden(delta);
    }

    private static fn make_with(value: i64) -> Counter {
        return Counter(value);
    }

    static fn make_public(value: i64) -> Counter {
        return Counter.make_with(value);
    }
}

fn main() -> i64 {
    var c: Counter = Counter.make_public(5);
    return c.use_hidden(2);
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_private_members_inside_constructor_body() -> None:
    source = """
class Counter {
    private value: i64;

    private fn hidden(delta: i64) -> i64 {
        return __self.value + delta;
    }

    constructor(value: i64) {
        __self.value = value;
        __self.value = __self.hidden(2);
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }
}

fn main() -> i64 {
    var c: Counter = Counter(5);
    return c.read();
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_private_field_access_outside_class() -> None:
    source = """
class Counter {
    private value: i64;

    static fn make(value: i64) -> Counter {
        return Counter(value);
    }
}

fn main() -> i64 {
    var c: Counter = Counter.make(7);
    return c.value;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_private_instance_method_call_outside_class() -> None:
    source = """
class Counter {
    private fn hidden() -> i64 {
        return 1;
    }
}

fn main() -> i64 {
    var c: Counter = Counter();
    return c.hidden();
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.hidden' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_private_static_method_call_outside_class() -> None:
    source = """
class Counter {
    private static fn hidden() -> i64 {
        return 1;
    }
}

fn main() -> i64 {
    return Counter.hidden();
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.hidden' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_inherited_private_field_access_inside_subclass() -> None:
    source = """
class Base {
    private value: i64;
}

class Derived extends Base {
    fn bad() -> i64 {
        return __self.value;
    }
}

fn main() -> i64 {
    return 0;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Base.value' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_inherited_private_method_call_inside_subclass() -> None:
    source = """
class Base {
    private fn hidden() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    fn bad() -> i64 {
        return __self.hidden();
    }
}

fn main() -> i64 {
    return 0;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Base.hidden' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_private_field_access_from_other_class_same_module() -> None:
    source = """
class Counter {
    private value: i64;

    static fn make(value: i64) -> Counter {
        return Counter(value);
    }
}

class Reader {
    fn read(c: Counter) -> i64 {
        return c.value;
    }
}

fn main() -> i64 {
    var c: Counter = Counter.make(7);
    var r: Reader = Reader();
    return r.read(c);
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assignment_to_final_field_inside_class() -> None:
    source = """
class Counter {
    final value: i64;

    fn bump() -> unit {
        __self.value = __self.value + 1;
        return;
    }
}

fn main() -> unit {
    var c: Counter = Counter(1);
    c.bump();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Field 'Counter.value' is final"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assignment_to_final_field_outside_class() -> None:
    source = """
class Counter {
    final value: i64;
}

fn main() -> unit {
    var c: Counter = Counter(1);
    c.value = 2;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Field 'Counter.value' is final"):
        parse_and_typecheck(source)


def test_typecheck_rejects_private_implicit_constructor_call_outside_class() -> None:
    source = """
class Counter {
    private value: i64;

    static fn make(value: i64) -> Counter {
        return Counter(value);
    }
}

fn main() -> unit {
    var a: Counter = Counter(1);
    var b: Counter = Counter.make(2);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Constructor for class 'Counter' is private"):
        parse_and_typecheck(source)


def test_typecheck_allows_public_explicit_constructor_on_class_with_private_field() -> None:
    source = """
class Counter {
    private value: i64;

    constructor(value: i64) {
        __self.value = value;
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }
}

fn main() -> i64 {
    var c: Counter = Counter(1);
    return c.read();
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_public_constructor_overload_when_selected() -> None:
    source = """
class Key {
}

class Sink {
    private constructor(value: Obj) {
        return;
    }

    constructor(value: Key) {
        return;
    }
}

fn main() -> unit {
    var s: Sink = Sink(Key());
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_private_explicit_constructor_call_outside_class() -> None:
    source = """
class Counter {
    private value: i64;

    private constructor(value: i64) {
        __self.value = value;
        return;
    }

    static fn make(value: i64) -> Counter {
        return Counter(value);
    }
}

fn main() -> unit {
    var a: Counter = Counter.make(1);
    var b: Counter = Counter(2);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Constructor for class 'Counter' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_private_constructor_overload_when_selected() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}

class Sink {
    constructor(value: Obj) {
        return;
    }

    private constructor(value: Hashable) {
        return;
    }
}

fn main() -> unit {
    var s: Sink = Sink(Key());
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Constructor for class 'Sink' is private"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assignment_to_box_final_field() -> None:
    source = """
class BoxI64 {
    final _value: i64;

    fn value() -> i64 {
        return __self._value;
    }
}

fn main() -> unit {
    var a: BoxI64 = BoxI64(7);
    a._value = 9;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Field 'BoxI64._value' is final"):
        parse_and_typecheck(source)
