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
    assert f"    call {mangle_function_symbol(('main',), 'add')}" in main_body
    assert re.search(r"^\s+mov qword ptr \[rbp - \d+\], rax$", main_body, re.MULTILINE)


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

    assert "    mov rdi, qword ptr [rbp - 16]" in apply_body or "    mov rdi, qword ptr [rbp - 24]" in apply_body
    assert "    call r11" in apply_body
