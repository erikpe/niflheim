from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_direct_call_no_args() -> None:
    source = """
fn callee() -> i64 {
    return 7;
}

fn caller() -> i64 {
    return callee();
}
"""
    asm = emit_source_asm(source)

    assert "    call callee" in asm
    assert "    test rsp, 8" in asm
    assert "\n    sub rsp, 8\n" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_direct_call_argument_register_order() -> None:
    source = """
fn sum3(a: i64, b: i64, c: i64) -> i64 {
    return a + b + c;
}

fn main() -> i64 {
    return sum3(1, 2, 3);
}
"""
    asm = emit_source_asm(source)

    assert "    mov rax, 3" in asm
    assert "    mov rax, 2" in asm
    assert "    mov rax, 1" in asm
    assert "    mov rdi, qword ptr [r10]" in asm
    assert "    mov rsi, qword ptr [r10 + 8]" in asm
    assert "    mov rdx, qword ptr [r10 + 16]" in asm
    assert "    call sum3" in asm


def test_emit_asm_direct_call_with_integer_stack_args() -> None:
    source = """
fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
    return a + b + c + d + e + f + g;
}

fn main() -> i64 {
    return sum7(1, 2, 3, 4, 5, 6, 7);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_many_int_args.nif")

    assert "    call sum7" in asm
    assert "    mov rax, qword ptr [r10 + 48]" in asm
    assert "    push rax" in asm
    assert "    add rsp, 64" in asm


def test_emit_asm_callee_spills_integer_stack_param_to_local_slot() -> None:
    source = """
fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
    return g;
}

fn main() -> i64 {
    return sum7(1, 2, 3, 4, 5, 6, 7);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_many_int_args_spill.nif")

    assert "sum7:" in asm
    assert "    mov rax, qword ptr [rbp + 16]" in asm
    assert "    mov qword ptr [rbp - 56], rax" in asm


def test_emit_asm_direct_call_with_floating_stack_args() -> None:
    source = """
fn sum9(a0: double, a1: double, a2: double, a3: double, a4: double, a5: double, a6: double, a7: double, a8: double) -> double {
    return a8;
}

fn main() -> i64 {
    var out: double = sum9(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0);
    return (i64)out;
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_many_double_args.nif")

    assert "    call sum9" in asm
    assert "    movq xmm7, qword ptr [r10 + 56]" in asm
    assert "    mov rax, qword ptr [r10 + 64]" in asm
    assert "    push rax" in asm
    assert "    add rsp, 80" in asm


def test_emit_asm_direct_call_one_arg_inserts_alignment_pad() -> None:
    source = """
fn id(x: i64) -> i64 {
    return x;
}

fn main() -> i64 {
    return id(41);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_one_arg_call.nif")

    assert "    call id" in asm
    assert "    test rsp, 8" in asm
    assert "    sub rsp, 8" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_function_value_from_top_level_function_and_indirect_call() -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = add;
    return f(20, 22);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_fn_value_top_level.nif")

    assert "    lea rax, [rip + add]" in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_function_value_indirect_one_arg_inserts_alignment_pad() -> None:
    source = """
fn id(x: i64) -> i64 {
    return x;
}

fn main() -> i64 {
    var f: fn(i64) -> i64 = id;
    return f(41);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_fn_value_one_arg_indirect.nif")

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm
    assert "    test rsp, 8" in asm
    assert "    sub rsp, 8" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_function_value_from_static_method_and_indirect_call() -> None:
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
    asm = emit_source_asm(source, source_path="examples/codegen_fn_value_static_method.nif")

    assert "    lea rax, [rip + __nif_method_Math_add]" in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_function_value_indirect_call_with_mixed_int_and_double_args() -> None:
    source = """
fn mix(a: i64, b: double, c: u64, d: double) -> double {
    return (double)a + b + (double)c + d;
}

fn main() -> i64 {
    var f: fn(i64, double, u64, double) -> double = mix;
    var out: double = f(2, 0.5, 3u, 0.25);
    return (i64)(out * 4.0);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_fn_value_mixed_indirect.nif")

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm
    assert "    movq xmm0, qword ptr [r10 + 8]" in asm
    assert "    movq xmm1, qword ptr [r10 + 24]" in asm
    assert "    mov rdi, qword ptr [r10]" in asm
    assert "    mov rsi, qword ptr [r10 + 16]" in asm
    assert "    movq rax, xmm0" in asm


def test_emit_asm_direct_callable_field_invocation_uses_indirect_call() -> None:
    source = """
fn inc(v: i64) -> i64 {
    return v + 1;
}

class Holder {
    f: fn(i64) -> i64;
}

fn main() -> i64 {
    var h: Holder = Holder(inc);
    return h.f(41);
}
"""
    asm = emit_source_asm(source, source_path="examples/codegen_callable_field_direct.nif")

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_module_qualified_call_uses_member_symbol_name() -> None:
    source = """
fn main() -> i64 {
    return std.io.println_i64(23);
}
"""
    asm = emit_source_asm(source)

    assert "    call println_i64" in asm
