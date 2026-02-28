import pytest

from compiler.lexer import lex
from compiler.parser import parse
from compiler.typecheck import typecheck
from compiler.typecheck_model import TypeCheckError


def _parse_and_typecheck(source: str) -> None:
    tokens = lex(source)
    module = parse(tokens)
    typecheck(module)


def test_typecheck_primitives_and_references_ok() -> None:
    source = """
class Str {
}

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
    _parse_and_typecheck(source)


def test_typecheck_rejects_private_field_access_outside_class() -> None:
    source = """
class Counter {
    private value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    return c.value;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
        _parse_and_typecheck(source)


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
        _parse_and_typecheck(source)


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
        _parse_and_typecheck(source)


def test_typecheck_rejects_private_field_access_from_other_class_same_module() -> None:
    source = """
class Counter {
    private value: i64;
}

class Reader {
    fn read(c: Counter) -> i64 {
        return c.value;
    }
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    var r: Reader = Reader();
    return r.read(c);
}
"""
    with pytest.raises(TypeCheckError, match="Member 'Counter.value' is private"):
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


def test_typecheck_rejects_u64_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 18446744073709551616u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="u64 literal out of range"):
        _parse_and_typecheck(source)


def test_typecheck_allows_u64_max_literal() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 18446744073709551615u;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_u8_suffix_and_char_literals_are_u8() -> None:
    source = """
fn main() -> unit {
    var a: u8 = 113u8;
    var b: u8 = 'q';
    var c: u8 = '\\x71';
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_u8_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: u8 = 256u8;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="u8 literal out of range"):
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


def test_typecheck_rejects_i64_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 9223372036854775808;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="i64 literal out of range"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_i64_literal_out_of_range_negative() -> None:
    source = """
fn main() -> unit {
    var x: i64 = -9223372036854775809;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="i64 literal out of range"):
        _parse_and_typecheck(source)


def test_typecheck_allows_i64_max_literal() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 9223372036854775807;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_allows_i64_min_literal_via_unary_minus() -> None:
    source = """
fn main() -> unit {
    var x: i64 = -9223372036854775808;
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
class Str {
}

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
    var nums: i64[] = null;
    var x: i64 = nums[0];

    var m: Map = null;
    var y: Obj = m[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_allows_structural_index_sugar_for_user_class() -> None:
    source = """
class Bag {
    values: i64[];

    static fn new() -> Bag {
        return Bag(i64[](2u));
    }

    fn get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn set(index: i64, value: i64) -> unit {
        __self.values[index] = value;
        return;
    }
}

fn main() -> unit {
    var b: Bag = Bag.new();
    b[0] = 42;
    var v: i64 = b[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_structural_index_sugar_for_wrong_get_signature() -> None:
    source = """
class BadBag {
    values: i64[];

    static fn new() -> BadBag {
        return BadBag(i64[](1u));
    }

    fn get(index: u64) -> i64 {
        return 0;
    }
}

fn main() -> unit {
    var b: BadBag = BadBag.new();
    var v: i64 = b[0];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="get' first parameter must be i64"):
        _parse_and_typecheck(source)


def test_typecheck_allows_structural_slice_sugar_for_user_class() -> None:
    source = """
class Window {
    values: i64[];

    static fn new() -> Window {
        var seed: i64[] = i64[](3u);
        seed[0] = 10;
        seed[1] = 20;
        seed[2] = 30;
        return Window(seed);
    }

    fn slice(begin: i64, end: i64) -> Window {
        return Window(__self.values[begin:end]);
    }
}

fn main() -> unit {
    var w: Window = Window.new();
    var part: Window = w[0:2];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_structural_slice_sugar_for_wrong_slice_signature() -> None:
    source = """
class BadWindow {
    values: i64[];

    static fn new() -> BadWindow {
        return BadWindow(i64[](1u));
    }

    fn slice(begin: u64, end: u64) -> BadWindow {
        return __self;
    }
}

fn main() -> unit {
    var w: BadWindow = BadWindow.new();
    var part: BadWindow = w[0:1];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="slice' parameters must be i64"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_structural_index_and_slice_sugar_for_private_methods() -> None:
    source_get = """
class HiddenGet {
    values: i64[];

    static fn new() -> HiddenGet {
        return HiddenGet(i64[](1u));
    }

    private fn get(index: i64) -> i64 {
        return __self.values[index];
    }
}

fn main() -> unit {
    var b: HiddenGet = HiddenGet.new();
    var v: i64 = b[0];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'HiddenGet.get' is private"):
        _parse_and_typecheck(source_get)

    source_set = """
class HiddenSet {
    values: i64[];

    static fn new() -> HiddenSet {
        return HiddenSet(i64[](1u));
    }

    fn get(index: i64) -> i64 {
        return __self.values[index];
    }

    private fn set(index: i64, value: i64) -> unit {
        __self.values[index] = value;
        return;
    }
}

fn main() -> unit {
    var b: HiddenSet = HiddenSet.new();
    b[0] = 1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'HiddenSet.set' is private"):
        _parse_and_typecheck(source_set)

    source_slice = """
class HiddenSlice {
    values: i64[];

    static fn new() -> HiddenSlice {
        return HiddenSlice(i64[](2u));
    }

    private fn slice(begin: i64, end: i64) -> HiddenSlice {
        return __self;
    }
}

fn main() -> unit {
    var w: HiddenSlice = HiddenSlice.new();
    var part: HiddenSlice = w[0:1];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'HiddenSlice.slice' is private"):
        _parse_and_typecheck(source_slice)


def test_typecheck_str_index_returns_u8() -> None:
    source = """
class Str {
}

fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s[0];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_str_slice_syntax_desugars_and_typechecks() -> None:
    source = """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_slice(value: Str, begin: i64, end: i64) -> Str;

class Str {
    fn len() -> i64 {
        return rt_str_len(__self);
    }

    fn slice(begin: i64, end: i64) -> Str {
        return rt_str_slice(__self, begin, end);
    }
}

fn main() -> unit {
    var v: Str = "Hello world!";
    var s1: Str = v[3:5];
    var s2: Str = v[:7];
    var s3: Str = v[4:];
    var s4: Str = v[:];
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_allows_implicit___self_in_method_body() -> None:
    source = """
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;

class Str {
    fn get_u8(index: i64) -> u8 {
        return rt_str_get_u8(__self, index);
    }
}

fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s.get_u8(0);
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_str_index() -> None:
    source = """
class Str {
}

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
class Str {
}

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


def test_typecheck_arrays_construct_get_set_slice_len_for_primitive_and_class_elements() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var nums: u8[] = u8[](4u);
    nums[0] = 1u8;
    nums.set(1, (u8)2);
    var a: u8 = nums[0];
    var b: u8 = nums.get(1);
    var n: u64 = nums.len();
    var part: u8[] = nums[0:2];

    var people: Person[] = Person[](2u);
    people[0] = Person(7);
    people.set(1, null);
    var p0: Person = people.get(0);
    var ps: Person[] = people.slice(0, 1);
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_arrays_are_invariant() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var objs: Obj[] = people;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Cannot assign 'Person\[\]' to 'Obj\[\]'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_wrong_array_element_assignment_type() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    nums[0] = 1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'u8'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_non_u64_array_constructor_length() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'u64', got 'bool'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_get_index() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var x: u8 = nums.get(true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_set_index() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    nums.set(true, (u8)1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_slice_end() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var s: u8[] = nums.slice(0, true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_array_method_wrong_arity() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var a: u64 = nums.len(1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 0 arguments, got 1"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_array_get_missing_index_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var x: u8 = nums.get();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 1 arguments, got 0"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_array_set_missing_value_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    nums.set(0);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 2 arguments, got 1"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_array_slice_missing_end_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var s: u8[] = nums.slice(0);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 2 arguments, got 1"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_unknown_array_member_access() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var n: u64 = nums.foo();
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Array type 'u8\[\]' has no method 'foo'"):
        _parse_and_typecheck(source)


def test_typecheck_allows_identity_cast_for_array_type() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var same: u8[] = (u8[])nums;
    return;
}
"""
    _parse_and_typecheck(source)


def test_typecheck_rejects_cross_element_array_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var objs: Obj[] = (Obj[])people;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Invalid cast from 'Person\[\]' to 'Obj\[\]'"):
        _parse_and_typecheck(source)


def test_typecheck_rejects_array_equality_for_different_element_types() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var objs: Obj[] = Obj[](1u);
    var same: bool = people == objs;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Operator '==' has incompatible operand types"):
        _parse_and_typecheck(source)


def test_typecheck_allows_array_equality_with_null() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var is_null: bool = people == null;
    var not_null: bool = null != people;
    return;
}
"""
    _parse_and_typecheck(source)
