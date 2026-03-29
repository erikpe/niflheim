from compiler.codegen.abi.array import array_length_operand
from compiler.codegen.abi.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_array_constructor_lowers_to_runtime_symbol_by_element_kind(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var a: u8[] = u8[](4u);
    var b: i64[] = i64[](2u);
    var c: Person[] = Person[](3u);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_U8]}" in asm
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_I64]}" in asm
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in asm


def test_emit_asm_array_index_reads_use_direct_loads_and_writes_stay_on_runtime_calls(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var nums: u8[] = u8[](2u);
    nums[0] = (u8)1;
    var x: u8 = nums[0];

    var people: Person[] = Person[](1u);
    people[0] = Person(7);
    var p: Person = people[0];
    if p == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" in asm
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm


def test_emit_asm_array_len_uses_direct_load_and_slice_stays_on_runtime_path(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var nums: u8[] = u8[](4u);
    var n: u64 = nums.len();
    var s: u8[] = nums[1:3];

    var people: Person[] = Person[](2u);
    var t: Person[] = people.slice_get(0, 1);
    if n == 4u && s == null && t == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" not in asm
    assert "    call rt_panic" in asm
    assert f"    mov rax, {array_length_operand('rax')}" in asm
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" in asm
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm


def test_emit_asm_array_constructor_dispatch_covers_remaining_primitive_kinds(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var a: u64[] = u64[](1u);
    var b: bool[] = bool[](1u);
    var c: double[] = double[](1u);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_U64]}" in asm
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_BOOL]}" in asm
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_DOUBLE]}" in asm


def test_emit_asm_nested_array_uses_reference_array_runtime_paths(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var mat: i64[][] = i64[][](2u);
    var row: i64[] = i64[](3u);
    mat[0] = row;
    var x: i64 = mat[0][1];
    return x;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in asm
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_I64]}" in asm
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in asm


def test_emit_asm_nested_array_chained_field_access_lowers(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var teams: Person[][] = Person[][](1u);
    teams[0] = Person[](1u);
    teams[0][0] = Person(42);
    return teams[0][0].age;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_asm_nested_index_assignment_target_lowers_to_array_set(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var cube: u8[][][][] = u8[][][][](1u);
    cube[0] = u8[][][](1u);
    cube[0][0] = u8[][](1u);
    cube[0][0][0] = u8[](2u);
    cube[0][0][0][1] = (u8)9;
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm


def test_emit_asm_array_method_form_get_uses_direct_load_while_set_and_slice_stay_runtime_backed(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var nums: u64[] = u64[](4u);
    nums.index_set(1, 42u);
    var x: u64 = nums.index_get(1);
    var s: u64[] = nums.slice_get(0, 2);
    nums.slice_set(1, 3, s);
    return (i64)x;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" not in asm
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in asm
    assert f"    call {ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in asm


def test_emit_asm_for_in_over_array_uses_direct_iteration(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var values: i64[] = i64[](2u);
    values[0] = 4;
    values[1] = 6;

    var sum: i64 = 0;
    for value in values {
        sum = sum + value;
    }

    return sum;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in asm


def test_emit_asm_for_in_over_reference_array_uses_direct_iteration(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var people: Person[] = Person[](2u);
    people[0] = Person(4);
    people[1] = Person(6);

    var sum: i64 = 0;
    for person in people {
        sum = sum + person.age;
    }

    return sum;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm


def test_emit_asm_array_reference_set_avoids_named_root_helper_calls(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var people: Person[] = Person[](1u);
    var p: Person = Person(7);
    people.index_set(0, p);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm
    assert "    call rt_root_slot_store" not in main_body


def test_emit_asm_array_index_assignment_roots_runtime_value_argument(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var people: Person[] = Person[](1u);
    var p: Person = Person(7);
    people[0] = p;
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm


def test_emit_asm_array_ctor_runtime_call_dynamic_aligns_with_prior_pushed_arg(tmp_path) -> None:
    source = """
fn consume(a: Obj[], b: i64) -> u64 {
    return a.len();
}

fn caller() -> u64 {
    return consume(Obj[](1u), 7);
}

fn main() -> i64 {
    return (i64)caller();
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in asm
    assert "    test rsp, 8" in asm
    assert "    sub rsp, 8" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_non_gc_runtime_helper_on_temporary_ref_omits_temp_root_scaffolding(tmp_path) -> None:
    source = """
extern fn rt_array_len(values: Obj[]) -> u64;

fn main() -> i64 {
    return (i64)rt_array_len(Obj[](1u));
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in main_body
    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" in main_body
    assert "rt_root_frame_init" not in main_body
    assert "rt_push_roots" not in main_body
    assert "rt_root_slot_store" not in main_body
