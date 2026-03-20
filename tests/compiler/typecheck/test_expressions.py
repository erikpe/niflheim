import pytest

from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


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
    parse_and_typecheck(source)


def test_typecheck_allows_str_plus_str() -> None:
    source = """
class Str {
}

fn main() -> unit {
    var a: Str = null;
    var b: Str = null;
    var c: Str = a + b;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_str_plus_non_str() -> None:
    source = """
class Str {
}

fn main() -> unit {
    var a: Str = null;
    var b: i64 = 1;
    var c: Str = a + b;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Operator '\\+' requires numeric operands or Str operands"):
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


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
        parse_and_typecheck(source)


def test_typecheck_u_suffix_integer_literal_is_u64() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 42u;
    var y: u64 = x + 1u;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_u64_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 18446744073709551616u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="u64 literal out of range"):
        parse_and_typecheck(source)


def test_typecheck_allows_u64_max_literal() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 18446744073709551615u;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_u8_suffix_and_char_literals_are_u8() -> None:
    source = """
fn main() -> unit {
    var a: u8 = 113u8;
    var b: u8 = 'q';
    var c: u8 = '\\x71';
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_u8_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: u8 = 256u8;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="u8 literal out of range"):
        parse_and_typecheck(source)


def test_typecheck_rejects_assigning_u_suffix_literal_to_i64() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 42u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'u64' to 'i64'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_i64_literal_out_of_range() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 9223372036854775808;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="i64 literal out of range"):
        parse_and_typecheck(source)


def test_typecheck_rejects_i64_literal_out_of_range_negative() -> None:
    source = """
fn main() -> unit {
    var x: i64 = -9223372036854775809;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="i64 literal out of range"):
        parse_and_typecheck(source)


def test_typecheck_allows_i64_max_literal() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 9223372036854775807;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_i64_min_literal_via_unary_minus() -> None:
    source = """
fn main() -> unit {
    var x: i64 = -9223372036854775808;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_unary_minus_on_u64() -> None:
    source = """
fn main() -> unit {
    var x: u64 = 1u;
    var y: u64 = -x;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Unary '-' requires signed numeric operand"):
        parse_and_typecheck(source)


def test_typecheck_rejects_unary_minus_on_u8() -> None:
    source = """
fn main() -> unit {
    var x: u8 = 1u8;
    var y: u8 = -x;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Unary '-' requires signed numeric operand"):
        parse_and_typecheck(source)


def test_typecheck_allows_bitwise_ops_for_matching_integer_types() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 1u;
    var b: u64 = 2u;
    var c: u64 = (a & b) | (a ^ b);

    var x: i64 = 7;
    var y: i64 = ~x;

    var p: u8 = 200u8;
    var q: u8 = ~p;
    var r: u8 = p ^ (u8)255;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_bitwise_mixed_integer_types() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 1u;
    var b: i64 = 2;
    var c: u64 = a & b;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '&' requires matching operand types"):
        parse_and_typecheck(source)


def test_typecheck_rejects_bitwise_on_double() -> None:
    source = """
fn main() -> unit {
    var x: double = 1.5;
    var y: double = 2.0;
    var z: double = x | y;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '\\|' requires integer operands"):
        parse_and_typecheck(source)


def test_typecheck_rejects_unary_bitwise_not_on_double() -> None:
    source = """
fn main() -> unit {
    var x: double = 1.5;
    var y: double = ~x;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Unary '~' requires integer operand"):
        parse_and_typecheck(source)


def test_typecheck_allows_shift_ops_with_u64_count() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 1u;
    var b: u64 = a << 3u;
    var c: u64 = b >> 1u;

    var x: i64 = -8;
    var y: i64 = x >> 1u;

    var p: u8 = 200u8;
    var q: u8 = p << 2u;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_shift_non_u64_count() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 1u;
    var b: u64 = a << (u8)3;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '<<' requires 'u64' shift count"):
        parse_and_typecheck(source)


def test_typecheck_rejects_shift_non_integer_left_operand() -> None:
    source = """
fn main() -> unit {
    var d: double = 1.5;
    var x: double = d >> 1u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '>>' requires integer left operand"):
        parse_and_typecheck(source)


def test_typecheck_allows_integer_power_with_u64_exponent() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 2u ** 10u;
    var b: i64 = (-2) ** 3u;
    var c: u8 = (u8)5 ** 3u;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_power_non_u64_exponent() -> None:
    source = """
fn main() -> unit {
    var a: u64 = 2u ** (u8)3;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '\*\*' requires 'u64' exponent"):
        parse_and_typecheck(source)


def test_typecheck_rejects_power_non_integer_left_operand() -> None:
    source = """
fn main() -> unit {
    var x: double = 2.0 ** 3u;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Operator '\*\*' requires integer left operand"):
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


def test_typecheck_allows_class_to_interface_assignment_and_obj_to_interface_cast() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    var direct: Hashable = Key();
    var obj: Obj = Key();
    var casted: Hashable = (Hashable)obj;
    var null_hashable: Hashable = (Hashable)null;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_assigning_non_implementing_class_to_interface() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key {
}

fn main() -> unit {
    var value: Hashable = Key();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Cannot assign 'Key' to 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_allows_interface_to_interface_and_interface_to_class_casts() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

interface Comparable {
    fn equals(other: Obj) -> bool;
}

class Key implements Hashable, Comparable {
    fn hash_code() -> u64 {
        return 1u;
    }

    fn equals(other: Obj) -> bool {
        return false;
    }
}

fn main() -> unit {
    var hashable: Hashable = Key();
    var comparable: Comparable = (Comparable)hashable;
    var key: Key = (Key)hashable;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_invalid_primitive_interface_cast() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

fn main() -> unit {
    var value: Hashable = (Hashable)1;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'i64' to 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_direct_class_expr_cast_to_unimplemented_interface() -> None:
    source = """
interface Metric {
    fn score() -> u64;
}

interface Doubler {
    fn twice() -> u64;
}

class Gauge implements Metric {
    fn score() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    var doubler: Doubler = (Doubler)Gauge();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'Gauge' to 'Doubler'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_direct_class_local_cast_to_unimplemented_interface() -> None:
    source = """
interface Metric {
    fn score() -> u64;
}

interface Doubler {
    fn twice() -> u64;
}

class Gauge implements Metric {
    fn score() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    var gauge: Gauge = Gauge();
    var doubler: Doubler = (Doubler)gauge;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'Gauge' to 'Doubler'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_direct_class_cast_to_different_unimplemented_interface() -> None:
    source = """
interface Metric {
    fn score() -> u64;
}

interface Hashable {
    fn hash_code() -> u64;
}

class Gauge implements Metric {
    fn score() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    var hashable: Hashable = (Hashable)Gauge();
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Invalid cast from 'Gauge' to 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_interface_to_array_cast() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    var value: Hashable = Key();
    var items: i64[] = (i64[])value;
    return;
}
"""
    with pytest.raises(TypeCheckError, match=r"Invalid cast from 'Hashable' to 'i64\[\]'"):
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


def test_typecheck_rejects_casts_involving_unit() -> None:
    source = """
fn main() -> unit {
    var x: i64 = (i64)(unit)0;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Casts involving 'unit' are not allowed"):
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)


def test_typecheck_allows_provably_null_index_deref_at_compile_time() -> None:
    source = """
fn main() -> unit {
    var nums: i64[] = null;
    var x: i64 = nums[0];
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_allows_identity_cast_for_array_type() -> None:
    source = """
fn main() -> unit {
    var nums: u8[] = u8[](2u);
    var same: u8[] = (u8[])nums;
    return;
}
"""
    parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
        parse_and_typecheck(source)


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
    parse_and_typecheck(source)
