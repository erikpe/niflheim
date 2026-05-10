from __future__ import annotations

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from tests.compiler.backend.targets.aarch64.helpers import emit_program, emit_source_asm
from tests.compiler.backend.targets.support import unit_function_backend_program


def _body_for_label(asm: str, label: str) -> str:
    return asm[asm.index(f"{label}:") : asm.index(f"{epilogue_label(label)}:")]


def test_emit_program_emits_prologue_epilogue_and_param_spills_for_unit_function() -> None:
    program = unit_function_backend_program(function_name="keep", param_type_names=("i64", "u64"), param_debug_names=("x", "y"))

    asm = emit_program(program)
    keep_label = mangle_function_symbol(("fixture", "backend_target"), "keep")

    assert ".text" in asm
    assert f"{keep_label}:" in asm
    assert "    stp x29, x30, [sp, #-16]!" in asm
    assert "    mov x29, sp" in asm
    assert "    sub sp, sp, #16" in asm
    assert "    str x0, [x29, #-8]" in asm
    assert "    str x1, [x29, #-16]" in asm
    assert f"    b {epilogue_label(keep_label)}" in asm
    assert f"{epilogue_label(keep_label)}:" in asm
    assert "    mov sp, x29" in asm
    assert "    ldp x29, x30, [sp], #16" in asm
    assert "    ret" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm


def test_emit_program_marks_entry_main_global_and_keeps_mangled_alias() -> None:
    program = unit_function_backend_program(function_name="main")

    asm = emit_program(program)
    mangled_label = mangle_function_symbol(("fixture", "backend_target"), "main")

    assert ".globl main" in asm
    assert "main:" in asm
    assert f"{mangled_label}:" in asm


def test_emit_program_handles_empty_unit_callable_without_stack_reserve() -> None:
    asm = emit_program(unit_function_backend_program(function_name="noop"))

    assert "    sub sp, sp" not in asm


def test_emit_source_asm_emits_straight_line_scalar_sequences_and_return_register(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var base: i64 = 8;
            var neg: i64 = -base;
            var sum: i64 = neg + 50;
            var same: i64 = sum;
            same = same + 100;
            return same;
        }
        """,
        skip_optimize=True,
    )

    assert "    movz x0, #8" in asm
    assert "    str x0, [x29, #-8]" in asm
    assert "    ldr x0, [x29, #-8]" in asm
    assert "    neg x0, x0" in asm
    assert "    movz x1, #50" in asm
    assert "    add x0, x0, x1" in asm
    assert "    str x0, [x29, #-32]" in asm
    assert "    ldr x0, [x29, #-32]" in asm
    assert "    b .Lmain_epilogue" in asm


def test_emit_source_asm_emits_integer_comparison_sequences(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn compare(a: i64, b: i64) -> i64 {
            var same: bool = a == b;
            var less: bool = a < b;
            return 0;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )
    compare_label = mangle_function_symbol(("main",), "compare")
    compare_body = asm[asm.index(f"{compare_label}:") : asm.index(f"{epilogue_label(compare_label)}:")]

    assert "    cmp x0, x1" in compare_body
    assert "    cset w0, eq" in compare_body
    assert "    cset w0, lt" in compare_body


def test_emit_source_asm_emits_checked_shift_sequences(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn lshift(a: u64, n: u64) -> u64 {
            return a << n;
        }

        fn urshift(a: u64, n: u64) -> u64 {
            return a >> n;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    lshift_body = _body_for_label(asm, mangle_function_symbol(("main",), "lshift"))
    urshift_body = _body_for_label(asm, mangle_function_symbol(("main",), "urshift"))

    assert "    cmp x1, #64" in lshift_body
    assert "    bl rt_panic_invalid_shift_count" in lshift_body
    assert "    lslv x0, x0, x1" in lshift_body

    assert "    cmp x1, #64" in urshift_body
    assert "    lsrv x0, x0, x1" in urshift_body