from compiler.codegen.abi.runtime import ARRAY_CONSTRUCTOR_RUNTIME_CALLS, ARRAY_LEN_RUNTIME_CALL
from tests.compiler.codegen.helpers import emit_source_asm


def _assert_named_root_store_block(asm: str, *, expected_store_count: int) -> None:
    if expected_store_count == 0:
        assert "# mirror named reference slots into shadow-stack slots" not in asm
        return

    pattern = (
        r"# mirror named reference slots into shadow-stack slots\n"
        + (r"\s+mov rax, qword ptr \[rbp - \d+\]\n\s+mov qword ptr \[rbp - \d+\], rax\n" * expected_store_count)
    )
    assert pattern is not None
    import re

    assert re.search(pattern, asm)


def test_emit_asm_runtime_call_has_safepoint_hooks(tmp_path) -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn f(ts: Obj) -> unit {
    rt_gc_collect(ts);
    return;
}

fn main() -> i64 {
    f(null);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})

    assert ".Lf_rt_safepoint_before_" in asm
    assert ".Lf_rt_safepoint_after_" in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_gc_capable_runtime_helper_keeps_root_sync_and_safepoint_hooks(tmp_path) -> None:
    source = """
fn make(seed: Obj, len: u64) -> Obj[] {
    var local: Obj = seed;
    return Obj[](len);
}

fn main() -> i64 {
    if make(null, 1u) == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})
    make_body = asm[asm.index("make:") : asm.index(".Lmake_epilogue:")]

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in make_body
    assert ".Lmake_rt_safepoint_before_" in make_body
    assert ".Lmake_rt_safepoint_after_" in make_body
    assert "    call rt_root_slot_store" not in make_body
    _assert_named_root_store_block(make_body, expected_store_count=0)


def test_emit_asm_skips_extern_declaration_body_emission(tmp_path) -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn main() -> i64 {
    var root: Obj = null;
    rt_gc_collect(root);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "rt_gc_collect:" not in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_runtime_call_spills_named_slots_to_root_slots(tmp_path) -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn f(ts: Obj) -> unit {
    var local: Obj = ts;
    rt_gc_collect(local);
    return;
}

fn main() -> i64 {
    f(null);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})
    f_body = asm[asm.index("f:") : asm.index(".Lf_epilogue:")]

    assert "    mov qword ptr [rbp - 8], rdi" in f_body
    assert "    mov qword ptr [rbp - 16], rax" in f_body
    assert "    call rt_root_slot_store" in f_body
    _assert_named_root_store_block(f_body, expected_store_count=0)
    assert "    call rt_gc_collect" in f_body


def test_emit_asm_initializes_value_and_root_slots_to_zero(tmp_path) -> None:
    source = """
fn f(a: i64) -> i64 {
    var x: i64;
    return a;
}

fn main() -> i64 {
    return f(7);
}
"""
    asm = emit_source_asm(tmp_path, source)
    f_body = asm[asm.index("f:") : asm.index(".Lf_epilogue:")]

    assert "    mov qword ptr [rbp - 8], 0" in f_body
    assert "    mov qword ptr [rbp - 16], 0" in f_body
    assert "    mov qword ptr [rbp - 24], 0" not in f_body
    assert "    mov qword ptr [rbp - 32], 0" not in f_body


def test_emit_asm_wires_shadow_stack_abi_calls_in_prologue_and_epilogue(tmp_path) -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_thread_state" in asm
    assert "    call rt_root_frame_init" in asm
    assert "    call rt_push_roots" in asm
    assert "    call rt_pop_roots" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_reference_functions(tmp_path) -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    source += "\nfn main() -> i64 { if f(null) == null { return 0; } return 1; }\n"
    asm = emit_source_asm(tmp_path, source)

    push_roots_i = asm.index("    call rt_push_roots")
    trace_push_i = asm.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_keeps_trace_push_for_functions_without_roots(tmp_path) -> None:
    source = """
fn f(a: i64) -> i64 {
    return a;
}
"""
    source += "\nfn main() -> i64 { return f(7); }\n"
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_trace_push" in asm
    assert "    call rt_trace_pop" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_constructors(tmp_path) -> None:
    source = """
class Boxed {
    final value: Obj;
}

fn main() -> i64 {
    if Boxed(null) == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    ctor_label = "__nif_ctor_Boxed:"
    assert ctor_label in asm
    ctor_start = asm.index(ctor_label)
    ctor_body = asm[ctor_start:]
    push_roots_i = ctor_body.index("    call rt_push_roots")
    trace_push_i = ctor_body.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_constructor_with_only_primitive_params_still_roots_allocated_object(tmp_path) -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    if Counter(7) == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    ctor_start = asm.index("__nif_ctor_Counter:")
    ctor_end = asm.index(".L__nif_ctor_Counter_epilogue:")
    ctor_body = asm[ctor_start:ctor_end]

    assert "    call rt_root_frame_init" in ctor_body
    assert "    call rt_push_roots" in ctor_body
    assert "    call rt_pop_roots" not in ctor_body


def test_emit_asm_omits_shadow_stack_abi_when_no_named_slots(tmp_path) -> None:
    source = """
fn f() -> unit {
    return;
}

fn main() -> i64 {
    f();
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    f_body = asm[asm.index("f:") : asm.index(".Lf_epilogue:")]

    assert "rt_root_frame_init" not in f_body
    assert "rt_push_roots" not in f_body
    assert "rt_pop_roots" not in f_body


def test_emit_asm_roots_only_reference_typed_bindings(tmp_path) -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn f(ts: Obj, n: i64) -> unit {
    var local_ref: Obj = ts;
    var local_i: i64 = n;
    rt_gc_collect(local_ref);
    return;
}

fn main() -> i64 {
    f(null, 7);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    f_body = asm[asm.index("f:") : asm.index(".Lf_epilogue:")]

    _assert_named_root_store_block(f_body, expected_store_count=0)
    assert "    mov rax, qword ptr [rbp - 16]" not in f_body


def test_emit_asm_no_runtime_root_frame_for_primitive_only_function(tmp_path) -> None:
    source = """
fn sum(a: i64, b: i64) -> i64 {
    var c: i64 = a + b;
    return c;
}
"""
    source += "\nfn main() -> i64 { return sum(20, 22); }\n"
    asm = emit_source_asm(tmp_path, source)
    sum_body = asm[asm.index("sum:") : asm.index(".Lsum_epilogue:")]

    assert "rt_root_frame_init" not in sum_body
    assert "rt_push_roots" not in sum_body
    assert "rt_pop_roots" not in sum_body


def test_emit_asm_preserves_rax_across_rt_pop_roots(tmp_path) -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    source += "\nfn main() -> i64 { if f(null) == null { return 0; } return 1; }\n"
    asm = emit_source_asm(tmp_path, source)

    push_i = asm.index("    push rax")
    pop_call_i = asm.index("    call rt_pop_roots")
    pop_i = asm.index("    pop rax")
    assert push_i < pop_call_i < pop_i


def test_emit_asm_non_runtime_call_has_no_runtime_hooks(tmp_path) -> None:
    source = """
fn callee(x: i64) -> i64 {
    return x;
}

fn f() -> i64 {
    return callee(1);
}

fn main() -> i64 {
    return f();
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call callee" in asm
    assert "rt_safepoint_before" not in asm
    assert "rt_safepoint_after" not in asm


def test_emit_asm_non_gc_runtime_helper_skips_gc_barrier_scaffolding(tmp_path) -> None:
    source = """
fn measure(values: Obj[]) -> u64 {
    return values.len();
}

fn main() -> i64 {
    return (i64)measure(null);
}
"""
    asm = emit_source_asm(tmp_path, source)
    measure_body = asm[asm.index("measure:") : asm.index(".Lmeasure_epilogue:")]

    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" in measure_body
    assert "    call rt_root_slot_store" not in measure_body
    assert "rt_safepoint_before" not in measure_body
    assert "rt_safepoint_after" not in measure_body


def test_emit_asm_ordinary_call_still_spills_root_slots(tmp_path) -> None:
    source = """
fn callee(x: Obj) -> Obj {
    return x;
}

fn caller(x: Obj) -> Obj {
    var y: Obj = x;
    return callee(y);
}

fn main() -> i64 {
    if caller(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    caller_body = asm[asm.index("caller:") : asm.index(".Lcaller_epilogue:")]

    assert "    call callee" in caller_body
    _assert_named_root_store_block(caller_body, expected_store_count=0)
    assert "rt_safepoint_before" not in caller_body


def test_emit_asm_gc_capable_call_syncs_only_live_named_roots(tmp_path) -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn f(a: Obj, b: Obj) -> Obj {
    var keep: Obj = a;
    var dead: Obj = b;
    rt_gc_collect(keep);
    return keep;
}

fn main() -> i64 {
    if f(null, null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(
        tmp_path,
        source,
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )
    f_body = asm[asm.index("f:") : asm.index(".Lf_epilogue:")]

    _assert_named_root_store_block(f_body, expected_store_count=1)


def test_emit_asm_roots_temporary_reference_args_for_non_runtime_call(tmp_path) -> None:
    source = """
fn takes_two(a: Obj[], b: Obj[]) -> u64 {
    return a.len();
}

fn caller() -> u64 {
    return takes_two(Obj[](1u), Obj[](2u));
}

fn main() -> i64 {
    return (i64)caller();
}
"""
    asm = emit_source_asm(tmp_path, source)

    caller_start = asm.index("caller:")
    caller_end = asm.index(".Lcaller_epilogue:")
    caller_body = asm[caller_start:caller_end]
    assert "    call takes_two" in caller_body
    assert caller_body.count("    call rt_root_slot_store") >= 2
