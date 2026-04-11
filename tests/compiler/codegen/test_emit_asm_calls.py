import re

from compiler.codegen.abi import runtime_layout
from compiler.codegen.abi.runtime import ARRAY_CONSTRUCTOR_RUNTIME_CALLS
from compiler.codegen.symbols import mangle_function_symbol
from tests.compiler.codegen.helpers import assert_no_shadow_stack_runtime_helpers, emit_source_asm
from tests.compiler.integration.stdlib_fixtures import install_std_io_fixture


def _main_function_body(asm: str, name: str) -> str:
    label = mangle_function_symbol(("main",), name)
    return asm[asm.index(f"{label}:") : asm.index(f".L{label}_epilogue:")]


def test_emit_asm_direct_call_no_args(tmp_path) -> None:
    source = """
fn callee() -> i64 {
    return 7;
}

fn caller() -> i64 {
    return callee();
}

fn main() -> i64 {
    return caller();
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'    call {mangle_function_symbol(("main",), "callee")}' in asm
    assert "    test rsp, 8" not in asm


def test_emit_asm_direct_call_argument_register_order(tmp_path) -> None:
    source = """
fn sum3(a: i64, b: i64, c: i64) -> i64 {
    return a + b + c;
}

fn main() -> i64 {
    return sum3(1, 2, 3);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    mov rax, 3" in asm
    assert "    mov rax, 2" in asm
    assert "    mov rax, 1" in asm
    assert "    mov qword ptr [rbp - 8], rax" in asm
    assert "    mov qword ptr [rbp - 16], rax" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm
    assert "    mov rdi, qword ptr [rbp - 24]" in asm
    assert "    mov rsi, qword ptr [rbp - 16]" in asm
    assert "    mov rdx, qword ptr [rbp - 8]" in asm
    assert "qword ptr [rsp]" not in asm
    assert f'    call {mangle_function_symbol(("main",), "sum3")}' in asm


def test_emit_asm_direct_call_with_integer_stack_args(tmp_path) -> None:
    source = """
fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
    return a + b + c + d + e + f + g;
}

fn main() -> i64 {
    return sum7(1, 2, 3, 4, 5, 6, 7);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'    call {mangle_function_symbol(("main",), "sum7")}' in asm
    assert "    mov rax, qword ptr [r10 + 48]" in asm
    assert "    push rax" in asm
    assert "    add rsp, 64" in asm


def test_emit_asm_callee_spills_integer_stack_param_to_local_slot(tmp_path) -> None:
    source = """
fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
    return g;
}

fn main() -> i64 {
    return sum7(1, 2, 3, 4, 5, 6, 7);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'{mangle_function_symbol(("main",), "sum7")}:' in asm
    assert "    mov rax, qword ptr [rbp + 16]" in asm
    assert "    mov qword ptr [rbp - 56], rax" in asm


def test_emit_asm_function_prologue_omits_zeroing_immediately_spilled_param_slots(tmp_path) -> None:
    source = """
fn sum2(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> i64 {
    return sum2(20, 22);
}
"""
    asm = emit_source_asm(tmp_path, source)
    sum2_label = mangle_function_symbol(("main",), "sum2")
    sum2_body = asm[asm.index(f"{sum2_label}:") : asm.index(f".L{sum2_label}_epilogue:")]

    assert "    mov qword ptr [rbp - 8], 0" not in sum2_body
    assert "    mov qword ptr [rbp - 16], 0" not in sum2_body
    assert "    mov qword ptr [rbp - 8], rdi" in sum2_body
    assert "    mov qword ptr [rbp - 16], rsi" in sum2_body


def test_emit_asm_function_prologue_keeps_root_slot_zeroing_for_reference_params(tmp_path) -> None:
    source = """
fn keep(value: Obj) -> Obj {
    return value;
}

fn main() -> i64 {
    if keep(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)
    keep_label = mangle_function_symbol(("main",), "keep")
    keep_body = asm[asm.index(f"{keep_label}:") : asm.index(f".L{keep_label}_epilogue:")]

    assert "    mov qword ptr [rbp - 8], 0" not in keep_body
    assert "    mov qword ptr [rbp - 8], rdi" in keep_body
    assert_no_shadow_stack_runtime_helpers(keep_body)
    assert f"    mov dword ptr [rdi + {runtime_layout.RT_ROOT_FRAME_SLOT_COUNT_OFFSET}]," in keep_body
    assert "    mov qword ptr [rax], rdi" in keep_body
    assert re.search(r"^\s+mov qword ptr \[rbp - \d+\], 0$", keep_body, re.MULTILINE) is not None


def test_emit_asm_direct_call_with_floating_stack_args(tmp_path) -> None:
    source = """
fn sum9(a0: double, a1: double, a2: double, a3: double, a4: double, a5: double, a6: double, a7: double, a8: double) -> double {
    return a8;
}

fn main() -> i64 {
    var out: double = sum9(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0);
    return (i64)out;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'    call {mangle_function_symbol(("main",), "sum9")}' in asm
    assert "    movq xmm7, qword ptr [r10 + 56]" in asm
    assert "    mov rax, qword ptr [r10 + 64]" in asm
    assert "    push rax" in asm
    assert "    add rsp, 80" in asm


def test_emit_asm_direct_call_one_arg_uses_frame_scratch_without_alignment_pad(tmp_path) -> None:
    source = """
fn id(x: i64) -> i64 {
    return x;
}

fn main() -> i64 {
    return id(41);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'    call {mangle_function_symbol(("main",), "id")}' in asm
    assert "    test rsp, 8" not in asm
    assert "    mov qword ptr [rbp - 8], rax" in asm
    assert "    mov rdi, qword ptr [rbp - 8]" in asm
    assert "    sub rsp, 8" not in asm
    assert "    add rsp, 8" not in asm


def test_emit_asm_function_value_from_top_level_function_and_indirect_call(tmp_path) -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = add;
    return f(20, 22);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f'    lea rax, [rip + {mangle_function_symbol(("main",), "add")}]' in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_function_value_indirect_one_arg_inserts_alignment_pad(tmp_path) -> None:
    source = """
fn id(x: i64) -> i64 {
    return x;
}

fn main() -> i64 {
    var f: fn(i64) -> i64 = id;
    return f(41);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm
    assert "    test rsp, 8" not in asm
    assert "    sub rsp, 8" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_function_value_from_static_method_and_indirect_call(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "    lea rax, [rip + __nif_method_main__Math_add]" in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_function_value_indirect_call_with_mixed_int_and_double_args(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm
    assert "    movq xmm0, qword ptr [rsp + 8]" in asm
    assert "    movq xmm1, qword ptr [rsp + 24]" in asm
    assert "    mov rdi, qword ptr [rsp]" in asm
    assert "    mov rsi, qword ptr [rsp + 16]" in asm
    assert "    movq rax, xmm0" in asm


def test_emit_asm_direct_callable_field_invocation_uses_indirect_call(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_emit_asm_module_qualified_call_uses_member_symbol_name(tmp_path) -> None:
    install_std_io_fixture(tmp_path)
    source = """
import std.io as io;

fn main() -> i64 {
    io.println_i64(23);
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source, project_root=tmp_path)

    assert f'    call {mangle_function_symbol(("std", "io"), "println_i64")}' in asm


def test_emit_asm_interface_method_call_uses_inline_slot_lookup_and_indirect_call(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 7u;
    }
}

class Token implements Hashable {
    fn hash_code() -> u64 {
        return 9u;
    }
}

fn call_hash(value: Hashable) -> u64 {
    return value.hash_code();
}

fn main() -> i64 {
    return (i64)call_hash(Key());
}
"""
    asm = emit_source_asm(tmp_path, source)
    call_hash_body = _main_function_body(asm, "call_hash")

    assert "    call rt_lookup_interface_method" not in call_hash_body
    assert "    mov rax, qword ptr [rcx + 64]" in call_hash_body
    assert "    mov rax, qword ptr [rax]" in call_hash_body
    assert "    mov rdi, qword ptr [rcx + 24]" in call_hash_body
    assert "    lea rsi, [rip + __nif_interface_main__Hashable]" in call_hash_body
    assert "    mov rsi, qword ptr [rsi]" in call_hash_body
    assert "# mirror named reference slots into shadow-stack slots" not in call_hash_body
    load_index = call_hash_body.index("    mov rcx, qword ptr [rsp]")
    assert_no_shadow_stack_runtime_helpers(call_hash_body[:load_index])
    assert re.search(r"push rax\n\s+mov rcx, qword ptr \[rsp\]", call_hash_body)
    assert "    mov r11, rax" in call_hash_body
    assert "    call r11" in call_hash_body


def test_emit_asm_interface_method_call_preserves_receiver_and_arg_order(tmp_path) -> None:
    source = """
interface Combiner {
    fn mix(a: i64, b: i64, c: i64) -> i64;
}

class Key implements Combiner {
    fn mix(a: i64, b: i64, c: i64) -> i64 {
        return a + b + c;
    }
}

class Token implements Combiner {
    fn mix(a: i64, b: i64, c: i64) -> i64 {
        return a * b * c;
    }
}

fn call_mix(value: Combiner) -> i64 {
    return value.mix(1, 2, 3);
}

fn main() -> i64 {
    return call_mix(Key());
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    mov rdi, qword ptr [r10]" in asm or "    mov rdi, qword ptr [rsp]" in asm
    assert "    mov rsi, qword ptr [rsp + 8]" in asm
    assert "    mov rdx, qword ptr [rsp + 16]" in asm
    assert "    mov rcx, qword ptr [rsp + 24]" in asm
    assert "    call r11" in asm


def test_emit_asm_interface_method_call_supports_reference_returns_and_runtime_root_updates(tmp_path) -> None:
    source = """
interface Boxed {
    fn next(seed: Obj) -> Obj;
}

class Key implements Boxed {
    fn next(seed: Obj) -> Obj {
        return seed;
    }
}

class Token implements Boxed {
    fn next(seed: Obj) -> Obj {
        return null;
    }
}

fn call_next(value: Boxed, seed: Obj) -> Obj {
    return value.next(seed);
}

fn main() -> i64 {
    if call_next(Key(), Key()) == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    call_next_body = _main_function_body(asm, "call_next")

    assert "    call rt_lookup_interface_method" not in call_next_body
    assert "    mov rax, qword ptr [rcx + 64]" in call_next_body
    assert "    mov rax, qword ptr [rax]" in call_next_body
    assert_no_shadow_stack_runtime_helpers(call_next_body)
    assert "    mov qword ptr [rbp - 64], rax" in call_next_body
    assert "    mov qword ptr [rbp - 56], rax" in call_next_body
    assert "# mirror named reference slots into shadow-stack slots" not in call_next_body
    assert "    mov r11, rax" in call_next_body
    assert "    call r11" in call_next_body


def test_emit_asm_interface_method_call_with_stack_args_keeps_lookup_out_of_arg_stack_layout(tmp_path) -> None:
    source = """
interface Combiner {
    fn mix(a0: i64, a1: i64, a2: i64, a3: i64, a4: i64, a5: i64, a6: i64, a7: i64, a8: i64) -> i64;
}

class Key implements Combiner {
    fn mix(a0: i64, a1: i64, a2: i64, a3: i64, a4: i64, a5: i64, a6: i64, a7: i64, a8: i64) -> i64 {
        return a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8;
    }
}

class Token implements Combiner {
    fn mix(a0: i64, a1: i64, a2: i64, a3: i64, a4: i64, a5: i64, a6: i64, a7: i64, a8: i64) -> i64 {
        return a0 * a1 * a2 * a3 * a4 * a5 * a6 * a7 * a8;
    }
}

fn call_mix(value: Combiner) -> i64 {
    return value.mix(1, 2, 3, 4, 5, 6, 7, 8, 9);
}

fn main() -> i64 {
    return call_mix(Key());
}
"""
    asm = emit_source_asm(tmp_path, source)
    call_mix_body = _main_function_body(asm, "call_mix")

    assert "    call rt_lookup_interface_method" not in call_mix_body
    assert "    mov rax, qword ptr [rcx + 64]" in call_mix_body
    assert "    mov rax, qword ptr [rax]" in call_mix_body
    assert "    mov r11, rax" in call_mix_body
    assert "    mov rdi, qword ptr [r10]" in call_mix_body
    assert "    mov rsi, qword ptr [r10 + 8]" in call_mix_body
    assert "    mov rax, qword ptr [r10 + 72]" in call_mix_body
    assert "    call r11" in call_mix_body


def test_emit_asm_interface_method_call_specializes_to_direct_call_via_closed_world_monomorphism(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 7u;
    }
}

fn call_hash(value: Hashable) -> u64 {
    return value.hash_code();
}

fn main() -> i64 {
    return (i64)call_hash(Key());
}
"""
    asm = emit_source_asm(tmp_path, source)
    call_hash_body = _main_function_body(asm, "call_hash")

    assert "    call __nif_method_main__Key_hash_code" in call_hash_body
    assert "    mov rax, qword ptr [rcx + 64]" not in call_hash_body
    assert "    call r11" not in call_hash_body


def test_emit_asm_virtual_method_call_uses_class_vtable_and_indirect_call(tmp_path) -> None:
    source = """
class Base {
    fn head() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    override fn head() -> i64 {
        return 2;
    }
}

fn read(value: Base) -> i64 {
    return value.head();
}

fn main() -> i64 {
    return read(Derived());
}
"""
    asm = emit_source_asm(tmp_path, source)
    read_body = _main_function_body(asm, "read")

    assert "    call __nif_method_main__Base_head" not in read_body
    assert "    call __nif_method_main__Derived_head" not in read_body
    assert "    mov rcx, qword ptr [rcx]" in read_body
    assert "    mov rcx, qword ptr [rcx + 80]" in read_body
    assert "    mov rax, qword ptr [rcx]" in read_body
    assert "    mov r11, rax" in read_body
    assert "    call r11" in read_body


def test_emit_asm_virtual_method_call_specializes_to_direct_call_after_exact_constructor_fact(tmp_path) -> None:
    source = """
class Base {
    fn head() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    override fn head() -> i64 {
        return 2;
    }
}

fn main() -> i64 {
    var value: Derived = Derived();
    return value.head();
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Derived_head" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_virtual_method_call_specializes_to_direct_call_via_closed_world_monomorphism(tmp_path) -> None:
    source = """
class Base {
    fn head() -> i64 {
        return 1;
    }
}

class Derived extends Base {
}

fn read(value: Base) -> i64 {
    return value.head();
}

fn main() -> i64 {
    return read(Derived());
}
"""
    asm = emit_source_asm(tmp_path, source)
    read_body = _main_function_body(asm, "read")

    assert "    call __nif_method_main__Base_head" in read_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in read_body
    assert "    call r11" not in read_body


def test_emit_asm_non_local_exact_virtual_receiver_expression_specializes_to_direct_call(tmp_path) -> None:
    source = """
class Base {
    fn head() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    override fn head() -> i64 {
        return 2;
    }
}

fn main() -> i64 {
    return Derived().head();
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Derived_head" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_direct_non_gc_runtime_call_on_temporary_ref_omits_temp_root_scaffolding(tmp_path) -> None:
    source = """
extern fn rt_array_len(values: Obj[]) -> u64;

fn main() -> i64 {
    return (i64)rt_array_len(Obj[](1u));
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS['ref']}" in main_body
    assert "    call rt_array_len" in main_body
    assert_no_shadow_stack_runtime_helpers(main_body)
