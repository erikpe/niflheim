from compiler.codegen import emit_asm
from compiler.lexer import lex
from compiler.parser import parse


def test_emit_asm_emits_array_type_metadata_symbols_for_reference_casts() -> None:
    source = """
class Person {
    age: i64;
}

fn f(value: Obj) -> Person[] {
    return (Person[])value;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Person__:" in asm
    assert '.asciz "Person[]"' in asm
    assert "__nif_type_Person__:" in asm


def test_emit_asm_runtime_call_has_safepoint_hooks() -> None:
    source = """
fn f(ts: Obj) -> unit {
    rt_gc_collect(ts);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lf_rt_safepoint_before_" in asm
    assert ".Lf_rt_safepoint_after_" in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_skips_extern_declaration_body_emission() -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn main() -> i64 {
    var root: Obj = null;
    rt_gc_collect(root);
    return 0;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_gc_collect:" not in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_runtime_call_spills_named_slots_to_root_slots() -> None:
    source = """
fn f(ts: Obj) -> unit {
    var local: Obj = ts;
    rt_gc_collect(local);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rax" in asm
    assert "    call rt_root_slot_store" in asm
    assert "    mov esi, 0" in asm
    assert "    mov esi, 1" in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_initializes_value_and_root_slots_to_zero() -> None:
    source = """
fn f(a: i64) -> i64 {
    var x: i64;
    return a;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], 0" in asm
    assert "    mov qword ptr [rbp - 16], 0" in asm
    assert "    mov qword ptr [rbp - 24], 0" not in asm
    assert "    mov qword ptr [rbp - 32], 0" not in asm


def test_emit_asm_wires_shadow_stack_abi_calls_in_prologue_and_epilogue() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_thread_state" in asm
    assert "    call rt_root_frame_init" in asm
    assert "    call rt_push_roots" in asm
    assert "    call rt_pop_roots" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_reference_functions() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    push_roots_i = asm.index("    call rt_push_roots")
    trace_push_i = asm.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_keeps_trace_push_for_functions_without_roots() -> None:
    source = """
fn f(a: i64) -> i64 {
    return a;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_trace_push" in asm
    assert "    call rt_trace_pop" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_constructors() -> None:
    source = """
class Boxed {
    final value: Obj;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    ctor_label = "__nif_ctor_Boxed:"
    assert ctor_label in asm
    ctor_start = asm.index(ctor_label)
    ctor_body = asm[ctor_start:]
    push_roots_i = ctor_body.index("    call rt_push_roots")
    trace_push_i = ctor_body.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_omits_shadow_stack_abi_when_no_named_slots() -> None:
    source = """
fn f() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_root_frame_init" not in asm
    assert "rt_push_roots" not in asm
    assert "rt_pop_roots" not in asm


def test_emit_asm_roots_only_reference_typed_bindings() -> None:
    source = """
fn f(ts: Obj, n: i64) -> unit {
    var local_ref: Obj = ts;
    var local_i: i64 = n;
    rt_gc_collect(local_ref);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov esi, 0" in asm
    assert "    mov esi, 1" in asm
    assert "    mov edx, 2" in asm
    assert asm.count("    call rt_root_slot_store") >= 2


def test_emit_asm_no_runtime_root_frame_for_primitive_only_function() -> None:
    source = """
fn sum(a: i64, b: i64) -> i64 {
    var c: i64 = a + b;
    return c;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_root_frame_init" not in asm
    assert "rt_push_roots" not in asm
    assert "rt_pop_roots" not in asm


def test_emit_asm_preserves_rax_across_rt_pop_roots() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    push_i = asm.index("    push rax")
    pop_call_i = asm.index("    call rt_pop_roots")
    pop_i = asm.index("    pop rax")
    assert push_i < pop_call_i < pop_i


def test_emit_asm_non_runtime_call_has_no_runtime_hooks() -> None:
    source = """
fn callee(x: i64) -> i64 {
    return x;
}

fn f() -> i64 {
    return callee(1);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call callee" in asm
    assert "rt_safepoint_before" not in asm
    assert "rt_safepoint_after" not in asm


def test_emit_asm_ordinary_call_still_spills_root_slots() -> None:
    source = """
fn callee(x: Obj) -> Obj {
    return x;
}

fn caller(x: Obj) -> Obj {
    var y: Obj = x;
    return callee(y);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call callee" in asm
    assert "    call rt_root_slot_store" in asm
    assert "rt_safepoint_before" not in asm


def test_emit_asm_roots_temporary_reference_args_for_non_runtime_call() -> None:
    source = """
fn takes_two(a: Obj[], b: Obj[]) -> u64 {
    return a.len();
}

fn caller() -> u64 {
    return takes_two(Obj[](1u), Obj[](2u));
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    caller_start = asm.index("caller:")
    caller_end = asm.index(".Lcaller_epilogue:")
    caller_body = asm[caller_start:caller_end]
    assert "    call takes_two" in caller_body
    assert caller_body.count("    call rt_root_slot_store") >= 2


def test_emit_asm_reference_cast_calls_rt_checked_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn f(o: Obj) -> Person {
    return (Person)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_checked_cast" in asm
    assert "    lea rsi, [rip + __nif_type_Person]" in asm


def test_emit_asm_reference_upcast_to_obj_does_not_call_rt_checked_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn f(p: Person, nums: u64[]) -> Obj {
    var a: Obj = (Obj)p;
    var b: Obj = (Obj)nums;
    return b;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_checked_cast" not in asm


def test_emit_asm_obj_to_array_cast_calls_rt_checked_cast_array_kind() -> None:
    source = """
fn f(o: Obj) -> u64[] {
    return (u64[])o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_checked_cast_array_kind" in asm
    assert "    mov rsi, 2" in asm


def test_emit_asm_primitive_cast_does_not_call_rt_checked_cast() -> None:
    source = """
fn f(x: i64) -> i64 {
    return (i64)x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_checked_cast" not in asm


def test_emit_asm_emits_type_metadata_symbols_for_reference_casts() -> None:
    source = """
fn f(o: Obj) -> Obj {
    return (Obj)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".section .rodata" in asm
    assert "__nif_type_name_Obj:" in asm
    assert '.asciz "Obj"' in asm
    assert ".data" in asm
    assert "__nif_type_Obj:" in asm


def test_emit_asm_class_type_metadata_includes_pointer_offsets_for_reference_fields() -> None:
    source = """
class Holder {
    value: Obj;
    count: i64;
}

fn f(o: Obj) -> Holder {
    return (Holder)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Holder__ptr_offsets:" in asm
    assert "__nif_type_name_Holder__ptr_offsets:\n    .long 24" in asm
    assert (
        "__nif_type_Holder:\n"
        "    .long 0\n"
        "    .long 1\n"
        "    .long 1\n"
        "    .long 8\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Holder\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Holder__ptr_offsets\n"
        "    .long 1\n"
        "    .long 0"
    ) in asm


def test_emit_asm_class_type_metadata_omits_pointer_offsets_for_primitive_fields() -> None:
    source = """
class Counter {
    value: i64;
}

fn f(o: Obj) -> Counter {
    return (Counter)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Counter__ptr_offsets:" not in asm
    assert (
        "__nif_type_Counter:\n"
        "    .long 0\n"
        "    .long 0\n"
        "    .long 1\n"
        "    .long 8\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Counter\n"
        "    .quad 0\n"
        "    .quad 0\n"
        "    .long 0\n"
        "    .long 0"
    ) in asm


def test_emit_asm_emits_class_type_metadata_even_without_casts() -> None:
    source = """
class Holder {
    value: Obj;
}

fn main() -> i64 {
    var h: Holder = Holder(null);
    if h == null {
        return 1;
    }
    return 0;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Holder:" in asm
    assert "__nif_type_Holder:" in asm
    assert "__nif_type_name_Holder__ptr_offsets:" in asm
