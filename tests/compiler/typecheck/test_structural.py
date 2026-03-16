import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


def test_typecheck_allows_for_in_with_iter_protocol() -> None:
    source = """
class Seq {
    values: i64[];

    fn iter_len() -> u64 {
        return __self.values.len();
    }

    fn iter_get(index: i64) -> i64 {
        return __self.values[index];
    }
}

fn main() -> i64 {
    var s: Seq = Seq(i64[](2u));
    s.values[0] = 7;
    s.values[1] = 9;
    var out: i64 = 0;
    for elem in s {
        out = out + elem;
    }
    return out;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_for_in_over_primitive_array() -> None:
    source = """
fn main() -> i64 {
    var values: i64[] = i64[](3u);
    values[0] = 4;
    values[1] = -1;
    values[2] = 7;

    var sum: i64 = 0;
    for value in values {
        sum = sum + value;
    }

    return sum;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_for_in_over_reference_array() -> None:
    source = """
class Box {
    value: i64;
}

fn main() -> i64 {
    var values: Box[] = Box[](2u);
    values[0] = Box(9);
    values[1] = Box(11);

    var sum: i64 = 0;
    for item in values {
        sum = sum + item.value;
    }

    return sum;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_for_in_on_len_get_only_map_like_type() -> None:
    source = """
class MapLike {
    fn len() -> u64 {
        return 0u;
    }

    fn index_get(key: u64) -> i64 {
        return 0;
    }
}

fn main() -> unit {
    var m: MapLike = MapLike();
    for value in m {
        return;
    }
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"not iterable \(missing method 'iter_len\(\)'\)"):
        parse_and_typecheck(source)


def test_typecheck_rejects_for_in_when_iter_len_return_type_is_not_u64() -> None:
    source = """
class Seq {
    fn iter_len() -> i64 {
        return 0;
    }

    fn iter_get(index: i64) -> i64 {
        return index;
    }
}

fn main() -> unit {
    var s: Seq = Seq();
    for elem in s {
        return;
    }
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"not iterable \(method 'iter_len' must return u64\)"):
        parse_and_typecheck(source)


def test_typecheck_rejects_for_in_when_iter_get_arity_is_wrong() -> None:
    source = """
class Seq {
    fn iter_len() -> u64 {
        return 0u;
    }

    fn iter_get(index: i64, other: i64) -> i64 {
        return index + other;
    }
}

fn main() -> unit {
    var s: Seq = Seq();
    for elem in s {
        return;
    }
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"not iterable \(method 'iter_get' must be instance method with 1 arg\)"):
        parse_and_typecheck(source)


def test_typecheck_allows_structural_index_sugar_for_user_class() -> None:
    source = """
class Bag {
    values: i64[];

    static fn new() -> Bag {
        return Bag(i64[](2u));
    }

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn index_set(index: i64, value: i64) -> unit {
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
    parse_and_typecheck(source)


def test_typecheck_rejects_structural_index_sugar_for_wrong_get_signature() -> None:
    source = """
class BadBag {
    values: i64[];

    static fn new() -> BadBag {
        return BadBag(i64[](1u));
    }

    fn index_get(index: u64) -> i64 {
        return 0;
    }
}

fn main() -> unit {
    var b: BadBag = BadBag.new();
    var v: i64 = b[0];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'u64'"):
        parse_and_typecheck(source)


def test_typecheck_allows_structural_index_sugar_with_non_i64_key_type() -> None:
    source = """
class FlagMap {
    yes: i64;
    no: i64;

    fn index_get(key: bool) -> i64 {
        if key {
            return __self.yes;
        }
        return __self.no;
    }

    fn index_set(key: bool, value: i64) -> unit {
        if key {
            __self.yes = value;
            return;
        }
        __self.no = value;
    }
}

fn main() -> unit {
    var m: FlagMap = FlagMap(10, 20);
    var a: i64 = m[true];
    m[false] = 99;
    var b: i64 = m[false];
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_mismatched_get_and_set_value_types_for_index_sugar() -> None:
    source = """
class WeirdStore {
    stored: bool;

    fn index_get(index: i64) -> bool {
        return __self.stored;
    }

    fn index_set(index: i64, value: i64) -> unit {
        __self.stored = value > 0;
    }
}

fn main() -> unit {
    var w: WeirdStore = WeirdStore(false);
    w[0] = 7;
    var flag: bool = w[0];
    return;
}
"""
    parse_and_typecheck(source)


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

    fn slice_get(begin: i64, end: i64) -> Window {
        return Window(__self.values[begin:end]);
    }
}

fn main() -> unit {
    var w: Window = Window.new();
    var part: Window = w[0:2];
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_structural_slice_sugar_for_wrong_slice_signature() -> None:
    source = """
class BadWindow {
    values: i64[];

    static fn new() -> BadWindow {
        return BadWindow(i64[](1u));
    }

    fn slice_get(begin: u64, end: u64) -> BadWindow {
        return __self;
    }
}

fn main() -> unit {
    var w: BadWindow = BadWindow.new();
    var part: BadWindow = w[0:1];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="slice_get' parameters must be i64"):
        parse_and_typecheck(source)


def test_typecheck_allows_structural_slice_write_sugar_for_user_class() -> None:
    source = """
class Window {
    values: i64[];

    static fn from_three(a: i64, b: i64, c: i64) -> Window {
        var seed: i64[] = i64[](3u);
        seed[0] = a;
        seed[1] = b;
        seed[2] = c;
        return Window(seed);
    }

    fn len() -> u64 {
        return __self.values.len();
    }

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn slice_set(begin: i64, end: i64, value: Window) -> unit {
        var i: i64 = 0;
        while begin + i < end {
            __self.values[begin + i] = value.values[i];
            i = i + 1;
        }
    }
}

fn main() -> unit {
    var w: Window = Window.from_three(1, 2, 3);
    var repl: Window = Window.from_three(9, 8, 7);
    w[1:3] = repl;
    var x: i64 = w[1];
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_structural_slice_write_sugar_for_wrong_set_slice_signature() -> None:
    source = """
class BadWindow {
    values: i64[];

    static fn new() -> BadWindow {
        return BadWindow(i64[](2u));
    }

    fn len() -> u64 {
        return __self.values.len();
    }

    fn slice_set(begin: u64, end: i64, value: BadWindow) -> unit {
        return;
    }
}

fn main() -> unit {
    var w: BadWindow = BadWindow.new();
    w[0:1] = BadWindow.new();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="slice_set' first two parameters must be i64"):
        parse_and_typecheck(source)


def test_typecheck_rejects_structural_index_and_slice_sugar_for_private_methods() -> None:
    source_get = """
class HiddenGet {
    values: i64[];

    static fn new() -> HiddenGet {
        return HiddenGet(i64[](1u));
    }

    private fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }
}

fn main() -> unit {
    var b: HiddenGet = HiddenGet.new();
    var v: i64 = b[0];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'HiddenGet.index_get' is private"):
        parse_and_typecheck(source_get)

    source_set = """
class HiddenSet {
    values: i64[];

    static fn new() -> HiddenSet {
        return HiddenSet(i64[](1u));
    }

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    private fn index_set(index: i64, value: i64) -> unit {
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
    with pytest.raises(TypeCheckError, match="Member 'HiddenSet.index_set' is private"):
        parse_and_typecheck(source_set)

    source_slice = """
class HiddenSlice {
    values: i64[];

    static fn new() -> HiddenSlice {
        return HiddenSlice(i64[](2u));
    }

    private fn slice_get(begin: i64, end: i64) -> HiddenSlice {
        return __self;
    }
}

fn main() -> unit {
    var w: HiddenSlice = HiddenSlice.new();
    var part: HiddenSlice = w[0:1];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Member 'HiddenSlice.slice_get' is private"):
        parse_and_typecheck(source_slice)


def test_typecheck_rejects_structural_index_assignment_when_index_set_returns_non_unit() -> None:
    source = """
class BadBag {
    values: i64[];

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn index_set(index: i64, value: i64) -> i64 {
        __self.values[index] = value;
        return value;
    }
}

fn main() -> unit {
    var b: BadBag = BadBag(i64[](1u));
    b[0] = 1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"index-assignable \(method 'index_set' must return unit\)"):
        parse_and_typecheck(source)


def test_typecheck_rejects_structural_slice_assignment_when_slice_set_returns_non_unit() -> None:
    source = """
class BadWindow {
    values: i64[];

    fn len() -> u64 {
        return __self.values.len();
    }

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn slice_set(begin: i64, end: i64, value: BadWindow) -> i64 {
        return 0;
    }
}

fn main() -> unit {
    var w: BadWindow = BadWindow(i64[](2u));
    w[0:1] = BadWindow(i64[](1u));
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"slice-assignable \(method 'slice_set' must return unit\)"):
        parse_and_typecheck(source)


def test_typecheck_str_index_returns_u8() -> None:
    source = """
class Str {
    fn index_get(index: i64) -> u8 {
        return 0u8;
    }
}

fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s[0];
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_str_slice_syntax_desugars_and_typechecks() -> None:
    source = """
class Str {
    fn len() -> u64 {
        return 0u;
    }

    fn slice_get(begin: i64, end: i64) -> Str {
        return __self;
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
    parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_str_index() -> None:
    source = """
class Str {
    fn index_get(index: i64) -> u8 {
        return 0u8;
    }
}

fn main() -> unit {
    var s: Str = "A";
    var b: u8 = s[true];
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'bool' to 'i64'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assignment_through_str_index() -> None:
    source = """
class Str {
    fn index_get(index: i64) -> u8 {
        return 0u8;
    }
}

fn main() -> unit {
    var s: Str = "A";
    s[0] = (u8)66;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="missing method 'index_set\\(K, V\\)'"):
        parse_and_typecheck(source)


def test_typecheck_arrays_construct_get_set_slice_len_for_primitive_and_class_elements() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var nums: u8[] = u8[](4u);
    nums[0] = 1u8;
    nums.index_set(1, (u8)2);
    var a: u8 = nums[0];
    var b: u8 = nums.index_get(1);
    var n: u64 = nums.len();
    var part: u8[] = nums[0:2];
    nums[1:3] = part;

    var people: Person[] = Person[](2u);
    people[0] = Person(7);
    people.index_set(1, null);
    var p0: Person = people.index_get(0);
    var ps: Person[] = people.slice_get(0, 1);
    people[0:1] = ps;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_nested_arrays_as_jagged_arrays() -> None:
    source = """
fn main() -> unit {
    var mat: i64[][] = i64[][](2u);
    mat[0] = i64[](3u);
    mat[1] = i64[](1u);

    mat[0][1] = 7;
    var x: i64 = mat[0][1];
    var row: i64[] = mat.index_get(1);
    var n: u64 = mat.len();
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_array_set_slice_value_type_mismatch() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](4u);
    nums[1:3] = true;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Cannot assign 'bool' to 'u8\[\]'"):
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


def test_typecheck_rejects_wrong_array_element_assignment_type() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    nums[0] = 1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'i64' to 'u8'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_u64_array_constructor_length() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'u64', got 'bool'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_get_index() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var x: u8 = nums.index_get(true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_set_index() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    nums.index_set(true, (u8)1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_i64_array_slice_end() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var s: u8[] = nums.slice_get(0, true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 'i64', got 'bool'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_array_method_wrong_arity() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var a: u64 = nums.len(1);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 0 arguments, got 1"):
        parse_and_typecheck(source)


def test_typecheck_rejects_array_get_missing_index_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var x: u8 = nums.index_get();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 1 arguments, got 0"):
        parse_and_typecheck(source)


def test_typecheck_rejects_array_set_missing_value_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    nums.index_set(0);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 2 arguments, got 1"):
        parse_and_typecheck(source)


def test_typecheck_rejects_array_slice_missing_end_argument() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](3u);
    var s: u8[] = nums.slice_get(0);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 2 arguments, got 1"):
        parse_and_typecheck(source)


def test_typecheck_rejects_unknown_array_member_access() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var n: u64 = nums.foo();
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Array type 'u8\[\]' has no method 'foo'"):
        parse_and_typecheck(source)
