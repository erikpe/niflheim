from dataclasses import replace

from compiler.codegen.generator import emit_asm
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, SemanticOptimizationPass, optimize_semantic_program
from compiler.semantic.ir import MethodDispatch, SemanticForIn
from compiler.semantic.symbols import MethodId
from compiler.resolver import resolve_program

from compiler.codegen.abi.array import (
    array_length_operand,
    direct_primitive_array_store_operand,
    direct_ref_array_store_operand,
)
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


def _erased_array_method_dispatch(method_name: str) -> MethodDispatch:
    return MethodDispatch(method_id=MethodId(module_path=("main",), class_name="ErasedArray", name=method_name))


def _erase_array_for_in_dispatches(program):
    module = program.modules[("main",)]
    fn = module.functions[0]
    statements = list(fn.body.statements)
    loop_stmt = next(stmt for stmt in statements if isinstance(stmt, SemanticForIn))
    loop_index = statements.index(loop_stmt)
    statements[loop_index] = replace(
        loop_stmt,
        iter_len_dispatch=_erased_array_method_dispatch("iter_len"),
        iter_get_dispatch=_erased_array_method_dispatch("iter_get"),
    )
    rewritten_fn = replace(fn, body=replace(fn.body, statements=statements))
    rewritten_module = replace(module, functions=[rewritten_fn])
    return replace(program, modules={**program.modules, ("main",): rewritten_module})


def _emit_source_asm_with_erased_array_for_in_dispatches(tmp_path, source: str) -> str:
    entry_path = tmp_path / "main.nif"
    entry_path.write_text(source.strip() + "\n", encoding="utf-8")
    program = resolve_program(entry_path, project_root=tmp_path)
    optimized = optimize_semantic_program(
        lower_program(program),
        passes=(
            SemanticOptimizationPass(name="erase_array_dispatches", transform=_erase_array_for_in_dispatches),
            *DEFAULT_SEMANTIC_OPTIMIZATION_PASSES,
        ),
    )
    return emit_asm(lower_linked_semantic_program(link_semantic_program(optimized)))


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


def test_emit_asm_array_index_reads_use_direct_loads_and_only_ref_writes_stay_on_runtime_calls(tmp_path) -> None:
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

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" not in asm
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.U8)}, dl" in asm
    assert f"    mov {direct_ref_array_store_operand('rax', 'rcx')}, rdx" in asm


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
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in asm
    assert f"    mov {direct_ref_array_store_operand('rax', 'rcx')}, rdx" in asm


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

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.U8)}, dl" in asm


def test_emit_asm_array_method_form_get_uses_direct_load_while_primitive_set_bypasses_runtime_and_slice_stays_runtime_backed(tmp_path) -> None:
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

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" not in asm
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in asm
    assert f"    call {ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in asm
    assert f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.U64)}, rdx" in asm


def test_emit_asm_primitive_array_direct_stores_cover_bool_and_double(tmp_path) -> None:
    source = """
fn main() -> i64 {
    var flags: bool[] = bool[](2u);
    var values: double[] = double[](2u);
    flags[0] = (bool)7;
    values.index_set(1, 2.5);
    if flags[0] {
        return (i64)values[1];
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.BOOL]}" not in asm
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.DOUBLE]}" not in asm
    assert "    setne dl" in asm
    assert "    movzx edx, dl" in asm
    assert f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.BOOL)}, rdx" in asm
    assert f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.DOUBLE)}, rdx" in asm


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


def test_emit_asm_recovers_array_direct_for_in_after_dispatch_erasure(tmp_path) -> None:
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
    asm = _emit_source_asm_with_erased_array_for_in_dispatches(tmp_path, source)

    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" not in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in asm


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

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert "    call rt_root_slot_store" not in main_body
    assert f"    mov {direct_ref_array_store_operand('rax', 'rcx')}, rdx" in main_body


def test_emit_asm_array_index_assignment_uses_direct_ref_store(tmp_path) -> None:
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

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert f"    mov {direct_ref_array_store_operand('rax', 'rcx')}, rdx" in asm


def test_emit_asm_ref_array_fast_write_keeps_temporary_value_alive_across_target_call(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn choose(values: Person[]) -> Person[] {
    return values;
}

fn main() -> i64 {
    var people: Person[] = Person[](1u);
    choose(people)[0] = Person(7);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in asm
    assert "    call choose" in main_body
    assert f"    mov {direct_ref_array_store_operand('rax', 'rcx')}, rdx" in main_body
    assert "    mov qword ptr [rbp -" in main_body


def test_emit_asm_array_ctor_runtime_call_no_longer_needs_direct_call_alignment_pad(tmp_path) -> None:
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
    caller_body = asm[asm.index("caller:") : asm.index(".Lcaller_epilogue:")]

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in caller_body
    assert "    call consume" in caller_body
    assert "    test rsp, 8" not in caller_body
    assert "    sub rsp, 8" not in caller_body
    assert "    add rsp, 8" not in caller_body


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
