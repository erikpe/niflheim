from __future__ import annotations

import re

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    return asm[asm.index(f"{label}:") : asm.index(f"{epilogue_label(label)}:")]


def test_emit_source_asm_emits_register_argument_moves_call_and_return_store(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn main() -> i64 {
            return add(20, 22);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    mov rdi, 20" in main_body
    assert "    mov rsi, 22" in main_body
    call_text = f"    call {mangle_function_symbol(('main',), 'add')}"
    assert call_text in main_body
    after_call_body = main_body[main_body.index(call_text) :]
    assert re.search(r"^\s+mov rbx, rax$", main_body, re.MULTILINE)
    assert not re.search(r"^\s+mov qword ptr \[rbp - \d+\], rbx$", after_call_body, re.MULTILINE)


def test_emit_source_asm_loads_call_arguments_from_allocated_registers(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn callee(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn caller(a: i64, b: i64) -> i64 {
            return callee(a, b);
        }

        fn main() -> i64 {
            return caller(20, 22);
        }
        """,
        skip_optimize=True,
    )

    caller_body = _body_for_label(asm, mangle_function_symbol(("main",), "caller"))

    assert "    mov rbx, qword ptr [rbp - 8]" in caller_body
    assert "    mov r12, qword ptr [rbp - 16]" in caller_body
    assert "    mov rdi, rbx" in caller_body
    assert "    mov rsi, r12" in caller_body
    assert f"    call {mangle_function_symbol(('main',), 'callee')}" in caller_body
    assert re.search(r"^\s+mov r13, rax$", caller_body, re.MULTILINE)


def test_emit_source_asm_emits_extern_direct_calls_to_bare_symbols(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        extern fn ext_add(value: i64) -> i64;

        fn main() -> i64 {
            return ext_add(7);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call ext_add" in main_body
    assert "    call __nif_fn_main__ext_add" not in main_body


def test_emit_source_asm_uses_aligned_outgoing_stack_space_beyond_register_budget(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
            return a + b + c + d + e + f + g;
        }

        fn main() -> i64 {
            return sum7(1, 2, 3, 4, 5, 6, 7);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    sub rsp, 16" in main_body
    assert "    mov qword ptr [rsp], rax" in main_body
    assert f"    call {mangle_function_symbol(('main',), 'sum7')}" in main_body
    assert "    add rsp, 16" in main_body
    assert "    push rax" not in main_body


def test_emit_source_asm_loads_mixed_register_and_stack_call_arguments_from_locations(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
            return a;
        }

        fn caller(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
            return sum7(a, b, c, d, e, f, g);
        }

        fn main() -> i64 {
            return caller(1, 2, 3, 4, 5, 6, 7);
        }
        """,
        skip_optimize=True,
    )

    caller_body = _body_for_label(asm, mangle_function_symbol(("main",), "caller"))

    assert "    mov rdi, rbx" in caller_body
    assert "    mov rsi, r12" in caller_body
    assert "    mov rdx, r13" in caller_body
    assert "    mov rcx, r14" in caller_body
    assert "    mov r8, r15" in caller_body
    assert "    mov r9, qword ptr [rbp - 48]" in caller_body
    assert "    mov rax, qword ptr [rbp - 56]" in caller_body
    assert "    mov qword ptr [rsp], rax" in caller_body


def test_emit_source_asm_omits_stack_adjustment_for_register_only_calls(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn callee() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            return callee();
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert f"    call {mangle_function_symbol(('main',), 'callee')}" in main_body
    assert "    sub rsp, 8" not in main_body
    assert "    add rsp, 8" not in main_body


def test_emit_source_asm_can_execute_reduced_scope_multi_function_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn sum7(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64) -> i64 {
            return a + b + c + d + e + f + g;
        }

        fn main() -> i64 {
            return sum7(1, 2, 3, 4, 5, 6, 7);
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 28


def test_emit_source_asm_preserves_allocated_values_across_calls(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn callee(value: i64) -> i64 {
            return value + 1;
        }

        fn caller(value: i64) -> i64 {
            var keep: i64 = value;
            var result: i64 = callee(10);
            return keep + result;
        }

        fn main() -> i64 {
            return caller(31);
        }
        """,
        skip_optimize=True,
    )

    caller_body = _body_for_label(asm, mangle_function_symbol(("main",), "caller"))

    assert f"    call {mangle_function_symbol(('main',), 'callee')}" in caller_body
    assert "    mov rax, r12" in caller_body
    assert "    mov rcx, rbx" in caller_body


def test_emit_source_asm_can_execute_allocated_value_live_across_call(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn callee(value: i64) -> i64 {
            return value + 1;
        }

        fn caller(value: i64) -> i64 {
            var keep: i64 = value;
            var result: i64 = callee(10);
            return keep + result;
        }

        fn main() -> i64 {
            return caller(31);
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 42


def test_emit_source_asm_emits_indirect_call_for_callable_parameter(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn apply(f: fn(i64) -> i64, value: i64) -> i64 {
            return f(value);
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    apply_body = _body_for_label(asm, mangle_function_symbol(("main",), "apply"))

    assert "    mov rdi, r12" in apply_body
    assert "    mov r11, rbx" in apply_body
    assert "    call r11" in apply_body


def test_emit_source_asm_materializes_function_refs_as_callable_values(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = inc;
            return func(41);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert f"    lea rbx, [rip + {mangle_function_symbol(('main',), 'inc')}]" in main_body
    assert "    call r11" in main_body


def test_emit_source_asm_can_execute_function_ref_callable_value_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = inc;
            return func(41);
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 42


def test_emit_source_asm_materializes_static_method_refs_as_callable_values(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Math {
            static fn twice(value: i64) -> i64 {
                return value * 2;
            }
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = Math.twice;
            return func(21);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    lea rbx, [rip + __nif_method_main__Math_twice]" in main_body
    assert "    call r11" in main_body


def test_emit_source_asm_can_execute_static_method_ref_callable_value_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        class Math {
            static fn twice(value: i64) -> i64 {
                return value * 2;
            }
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = Math.twice;
            return func(21);
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 42
