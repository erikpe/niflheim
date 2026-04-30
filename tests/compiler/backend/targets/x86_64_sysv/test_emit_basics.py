from __future__ import annotations

import pytest

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import X86_64_SYSV_ABI, X86_64SysVFrameError, plan_callable_frame_layout
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.ir.helpers import FIXTURE_ENTRY_FUNCTION_ID, callable_by_id, one_function_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import (
    compile_and_run_source,
    emit_program,
    emit_source_asm,
    make_target_input,
    unit_function_backend_program,
    with_root_slot,
)


def _body_for_label(asm: str, label: str) -> str:
    return asm[asm.index(f"{label}:") : asm.index(f"{epilogue_label(label)}:")]


def test_plan_callable_frame_layout_assigns_deterministic_offsets_from_stack_homes(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn keep(x: i64, y: i64) -> unit {
            var z: i64 = x;
            return;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="keep",
        skip_optimize=True,
    )
    target_input = make_target_input(fixture.program)

    first_layout = plan_callable_frame_layout(target_input, fixture.callable_decl)
    second_layout = plan_callable_frame_layout(target_input, fixture.callable_decl)
    expected_home_names = tuple(
        target_input.analysis_for_callable(fixture.callable_decl.callable_id).stack_homes.stack_home_by_reg.values()
    )

    assert first_layout == second_layout
    assert tuple(slot.home_name for slot in first_layout.slots) == expected_home_names
    assert tuple(slot.byte_offset for slot in first_layout.slots) == tuple(-8 * index for index in range(1, len(first_layout.slots) + 1))
    assert first_layout.stack_size == X86_64_SYSV_ABI.align_stack_size(first_layout.home_count * 8)

    for reg_id, home_name in target_input.analysis_for_callable(fixture.callable_decl.callable_id).stack_homes.stack_home_by_reg.items():
        slot = first_layout.for_reg(reg_id)
        assert slot is not None
        assert slot.home_name == home_name
        assert first_layout.for_home_name(home_name) == slot


def test_plan_callable_frame_layout_allocates_inline_root_frame_for_root_slots() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    layout = plan_callable_frame_layout(
        with_root_slot(
            target_input,
            callable_id=FIXTURE_ENTRY_FUNCTION_ID,
            reg_id=callable_decl.registers[0].reg_id,
        ),
        callable_decl,
    )

    home_slot = layout.for_reg(callable_decl.registers[0].reg_id)
    root_slot = layout.root_slot_for_reg(callable_decl.registers[0].reg_id)

    assert home_slot is not None
    assert layout.has_root_frame is True
    assert layout.root_slot_count == 1
    assert layout.thread_state_offset is not None
    assert layout.root_frame_offset is not None
    assert root_slot is not None
    assert layout.thread_state_offset < home_slot.byte_offset
    assert layout.root_frame_offset < layout.thread_state_offset
    assert root_slot.byte_offset < layout.root_frame_offset
    assert layout.stack_size % 16 == 0


def test_emit_program_emits_prologue_epilogue_and_param_spills_for_unit_function() -> None:
    program = unit_function_backend_program(function_name="keep", param_type_names=("i64", "u64"), param_debug_names=("x", "y"))

    asm = emit_program(program)
    keep_label = mangle_function_symbol(("fixture", "backend_target"), "keep")

    assert ".intel_syntax noprefix" in asm
    assert ".text" in asm
    assert f"{keep_label}:" in asm
    assert "    push rbp" in asm
    assert "    mov rbp, rsp" in asm
    assert "    sub rsp, 16" in asm
    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rsi" in asm
    assert f"    jmp {epilogue_label(keep_label)}" in asm
    assert f"{epilogue_label(keep_label)}:" in asm
    assert "    mov rsp, rbp" in asm
    assert "    pop rbp" in asm
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

    assert "    sub rsp" not in asm


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

    assert "    mov rax, 8" in asm
    assert "    mov qword ptr [rbp - 8], rax" in asm
    assert "    mov rax, qword ptr [rbp - 8]" in asm
    assert "    neg rax" in asm
    assert "    mov rcx, 50" in asm
    assert "    add rax, rcx" in asm
    assert "    mov qword ptr [rbp - 32], rax" in asm
    assert "    mov rax, qword ptr [rbp - 32]" in asm
    assert "    jmp .Lmain_epilogue" in asm


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

    assert "    cmp rax, rcx" in compare_body
    assert "    sete al" in compare_body
    assert "    setl al" in compare_body
    assert "    movzx rax, al" in compare_body


def test_emit_source_asm_emits_integer_divide_and_remainder_sequences(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sdiv(a: i64, b: i64) -> i64 {
            return a / b;
        }

        fn smod(a: i64, b: i64) -> i64 {
            return a % b;
        }

        fn udiv(a: u64, b: u64) -> u64 {
            return a / b;
        }

        fn umod(a: u64, b: u64) -> u64 {
            return a % b;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    sdiv_body = _body_for_label(asm, mangle_function_symbol(("main",), "sdiv"))
    smod_body = _body_for_label(asm, mangle_function_symbol(("main",), "smod"))
    udiv_body = _body_for_label(asm, mangle_function_symbol(("main",), "udiv"))
    umod_body = _body_for_label(asm, mangle_function_symbol(("main",), "umod"))

    assert "    cqo" in sdiv_body
    assert "    idiv rcx" in sdiv_body
    assert "    shr r8, 63" in sdiv_body
    assert "    setne r9b" in sdiv_body
    assert "    sub rax, r8" in sdiv_body

    assert "    cqo" in smod_body
    assert "    idiv rcx" in smod_body
    assert "    imul r8, rcx" in smod_body
    assert "    add rdx, r8" in smod_body
    assert "    mov rax, rdx" in smod_body

    assert "    xor rdx, rdx" in udiv_body
    assert "    div rcx" in udiv_body
    assert "    mov rax, rdx" not in udiv_body

    assert "    xor rdx, rdx" in umod_body
    assert "    div rcx" in umod_body
    assert "    mov rax, rdx" in umod_body


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

    assert "    cmp rcx, 64" in lshift_body
    assert "    call rt_panic_invalid_shift_count" in lshift_body
    assert "    shl rax, cl" in lshift_body

    assert "    cmp rcx, 64" in urshift_body
    assert "    shr rax, cl" in urshift_body


def test_emit_source_asm_can_execute_shift_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn main() -> i64 {
            var left: u64 = 3u << 4u;
            var right: u64 = 240u >> 4u;

            if (i64)left != 48 {
                return 1;
            }
            if (i64)right != 15 {
                return 2;
            }
            return 7;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 7


def test_emit_source_asm_is_byte_stable_across_repeated_runs(tmp_path) -> None:
    source = """
    fn main() -> i64 {
        var value: i64 = 5;
        value = value * 3;
        return value;
    }
    """

    first_asm = emit_source_asm(tmp_path / "run_a", source, skip_optimize=True)
    second_asm = emit_source_asm(tmp_path / "run_b", source, skip_optimize=True)

    assert first_asm == second_asm


def test_emit_source_asm_can_execute_straight_line_arithmetic_program(tmp_path) -> None:
    run = compile_and_run_source(
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

    assert run.returncode == 142


def test_emit_source_asm_can_execute_integer_divide_and_remainder_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn sdiv(a: i64, b: i64) -> i64 {
            return a / b;
        }

        fn smod(a: i64, b: i64) -> i64 {
            return a % b;
        }

        fn udiv(a: u64, b: u64) -> u64 {
            return a / b;
        }

        fn umod(a: u64, b: u64) -> u64 {
            return a % b;
        }

        fn main() -> i64 {
            if sdiv(-7, 3) != -3 {
                return 1;
            }
            if smod(-7, 3) != 2 {
                return 2;
            }
            if (i64)udiv(17u, 5u) != 3 {
                return 3;
            }
            if (i64)umod(17u, 5u) != 2 {
                return 4;
            }
            return 9;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 9