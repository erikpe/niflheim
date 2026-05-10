from __future__ import annotations

import re

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


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

    assert "    movz x0, #20" in main_body
    assert "    movz x1, #22" in main_body
    assert f"    bl {mangle_function_symbol(('main',), 'add')}" in main_body
    assert re.search(r"^\s+str x0, \[x29, #-\d+\]$", main_body, re.MULTILINE)


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

    assert "    bl ext_add" in main_body
    assert "    bl __nif_fn_main__ext_add" not in main_body


def test_emit_source_asm_uses_aligned_outgoing_stack_space_beyond_register_budget(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sum9(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64, h: i64, i: i64) -> i64 {
            return a + b + c + d + e + f + g + h + i;
        }

        fn main() -> i64 {
            return sum9(1, 2, 3, 4, 5, 6, 7, 8, 9);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    sub sp, sp, #16" in main_body
    assert "    str x9, [sp]" in main_body
    assert f"    bl {mangle_function_symbol(('main',), 'sum9')}" in main_body
    assert "    add sp, sp, #16" in main_body


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

    assert f"    bl {mangle_function_symbol(('main',), 'callee')}" in main_body
    assert main_body.count("    sub sp, sp, #16") == 1
    assert main_body.count("    add sp, sp, #16") == 0


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

    assert re.search(r"\s+ldr x16, \[x29, #-\d+\]", apply_body)
    assert "    blr x16" in apply_body


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

    assert f"    adrp x0, {mangle_function_symbol(('main',), 'inc')}" in main_body
    assert f"    add x0, x0, :lo12:{mangle_function_symbol(('main',), 'inc')}" in main_body
    assert "    blr x16" in main_body