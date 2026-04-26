from __future__ import annotations

import pytest

from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import X86_64_SYSV_ABI, X86_64SysVFrameError, plan_callable_frame_layout
from compiler.codegen.symbols import epilogue_label, mangle_function_symbol
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.ir.helpers import FIXTURE_ENTRY_FUNCTION_ID, callable_by_id, one_function_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import emit_program, make_target_input, unit_function_backend_program, with_root_slot


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


def test_plan_callable_frame_layout_rejects_root_slot_requirements() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    with pytest.raises(X86_64SysVFrameError, match="does not yet support GC root-slot setup"):
        plan_callable_frame_layout(
            with_root_slot(
                target_input,
                callable_id=FIXTURE_ENTRY_FUNCTION_ID,
                reg_id=callable_decl.registers[0].reg_id,
            ),
            callable_decl,
        )


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


def test_emit_program_rejects_nonempty_body_before_instruction_selection() -> None:
    with pytest.raises(RuntimeError, match="straight-line instruction emission lands in later phase-4 slices"):
        emit_program(one_function_backend_program(), options=BackendTargetOptions())