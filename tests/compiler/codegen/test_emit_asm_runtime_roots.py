from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_runtime_call_has_safepoint_hooks() -> None:
    source = """
fn f(ts: Obj) -> unit {
    rt_gc_collect(ts);
    return;
}
"""
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

    push_roots_i = asm.index("    call rt_push_roots")
    trace_push_i = asm.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_keeps_trace_push_for_functions_without_roots() -> None:
    source = """
fn f(a: i64) -> i64 {
    return a;
}
"""
    asm = emit_source_asm(source)

    assert "    call rt_trace_push" in asm
    assert "    call rt_trace_pop" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_constructors() -> None:
    source = """
class Boxed {
    final value: Obj;
}
"""
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

    assert "rt_root_frame_init" not in asm
    assert "rt_push_roots" not in asm
    assert "rt_pop_roots" not in asm


def test_emit_asm_preserves_rax_across_rt_pop_roots() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

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
    asm = emit_source_asm(source)

    caller_start = asm.index("caller:")
    caller_end = asm.index(".Lcaller_epilogue:")
    caller_body = asm[caller_start:caller_end]
    assert "    call takes_two" in caller_body
    assert caller_body.count("    call rt_root_slot_store") >= 2