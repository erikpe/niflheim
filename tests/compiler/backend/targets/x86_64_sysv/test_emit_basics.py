from __future__ import annotations

import re

import pytest

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import (
    X86_64_SYSV_ABI,
    X86AsmBuilder,
    X86_64SysVFrameError,
    X86_64SysVLiveInterval,
    allocate_x86_64_sysv_registers,
    emit_block_instructions,
    plan_callable_frame_layout,
    plan_x86_64_sysv_target,
    register_type_name_by_reg_id,
)
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


def _reg_id_by_debug_name(callable_decl, debug_name: str):
    for register in callable_decl.registers:
        if register.debug_name == debug_name:
            return register.reg_id
    raise KeyError(debug_name)


def _test_interval(callable_decl, debug_name: str, *, start: int, end: int) -> X86_64SysVLiveInterval:
    return X86_64SysVLiveInterval(
        reg_id=_reg_id_by_debug_name(callable_decl, debug_name),
        start_position=start,
        end_position=end,
        register_class="gpr",
        crosses_call=False,
        is_gc_reference=False,
        live_at_safepoint=False,
    )


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


def test_plan_callable_frame_layout_reserves_callee_saved_register_slots(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn keep(x: i64, y: i64) -> unit {
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
    preliminary_plan = plan_x86_64_sysv_target(target_input, options=BackendTargetOptions()).plan_for_callable(
        fixture.callable_decl.callable_id
    )
    allocation = allocate_x86_64_sysv_registers(preliminary_plan)

    layout = plan_callable_frame_layout(target_input, fixture.callable_decl, allocation=allocation)

    assert layout.callee_saved_slots == ()
    assert layout.callee_saved_count == 0
    assert layout.stack_size == X86_64_SYSV_ABI.align_stack_size(
        (layout.home_count + layout.callee_saved_count) * X86_64_SYSV_ABI.stack_slot_size_bytes
    )
    assert layout.allocation == allocation


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
    assert "    mov qword ptr [rbp - 24], rbx" not in asm
    assert "    mov qword ptr [rbp - 32], r12" not in asm
    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rsi" in asm
    assert "    mov r10, qword ptr [rbp - 8]" in asm
    assert "    mov r11, qword ptr [rbp - 16]" in asm
    assert f"    jmp {epilogue_label(keep_label)}" in asm
    assert f"{epilogue_label(keep_label)}:" in asm
    assert "    mov r12, qword ptr [rbp - 32]" not in asm
    assert "    mov rbx, qword ptr [rbp - 24]" not in asm
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
    assert "    mov r10, rax" in asm
    assert "    mov r11, r10" in asm
    assert "    neg r11" in asm
    assert "    mov rax, qword ptr [rbp - 8]" not in asm
    assert "    mov qword ptr [rbp - 8], rbx" not in asm
    assert "    mov rcx, 50" not in asm
    assert "    add rax, 50" in asm
    assert "    mov qword ptr [rbp - 32], r12" not in asm
    assert "    add r10, 100" in asm
    assert "    mov rax, r10" in asm
    assert "    jmp .Lmain_epilogue" in asm


def test_emit_source_asm_selects_simple_integer_ops_into_allocated_destinations(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var a: i64 = 6;
            var b: i64 = a * 7;
            var c: i64 = b - 5;
            var d: i64 = ~c;
            var e: i64 = d & 15;
            var f: i64 = e | 2;
            var g: i64 = f ^ 3;
            return g;
        }
        """,
        skip_optimize=True,
    )

    assert "    mov rcx, 7" in asm
    assert "    imul r11, rcx" in asm
    assert "    sub r10, 5" in asm
    assert "    not r11" in asm
    assert "    and r10, 15" in asm
    assert "    or r11, 2" in asm
    assert "    xor rax, 3" in asm
    assert "    mov rcx, 5" not in asm
    assert "    mov rcx, 15" not in asm
    assert "    mov rcx, 2" not in asm
    assert "    mov rcx, 3" not in asm


def test_emit_block_rematerializes_spilled_integer_constants_without_stack_traffic(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn sample(a: i64, b: i64, c: i64, d: i64, e: i64) -> i64 {
            var cheap: i64 = 7;
            return a + cheap;
        }

        fn main() -> i64 {
            return sample(1, 2, 3, 4, 5);
        }
        """,
        callable_name="sample",
        skip_optimize=True,
    )
    target_input = make_target_input(fixture.program)
    preliminary_plan = plan_x86_64_sysv_target(
        target_input,
        options=BackendTargetOptions(register_allocation_enabled=False),
    ).plan_for_callable(fixture.callable_decl.callable_id)
    allocation = allocate_x86_64_sysv_registers(
        preliminary_plan,
        intervals=(
            _test_interval(fixture.callable_decl, "cheap", start=0, end=100),
            _test_interval(fixture.callable_decl, "a", start=0, end=100),
            _test_interval(fixture.callable_decl, "b", start=0, end=100),
            _test_interval(fixture.callable_decl, "c", start=0, end=100),
            _test_interval(fixture.callable_decl, "d", start=0, end=100),
            _test_interval(fixture.callable_decl, "e", start=1, end=90),
        ),
        call_free_allocatable_gprs=(),
    )
    frame_layout = plan_callable_frame_layout(target_input, fixture.callable_decl, allocation=allocation)
    cheap_slot = frame_layout.for_reg(_reg_id_by_debug_name(fixture.callable_decl, "cheap"))
    assert cheap_slot is not None

    builder = X86AsmBuilder()
    emit_block_instructions(
        builder,
        fixture.callable_decl.blocks[0],
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id(fixture.callable_decl),
    )
    asm = builder.build()

    assert f"[rbp - {abs(cheap_slot.byte_offset)}]" not in asm
    assert re.search(r"^\s+mov [a-z0-9]+, 7$", asm, re.MULTILINE)


def test_emit_source_asm_omits_coalesced_non_overlapping_copy(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sample(a: i64) -> i64 {
            var b: i64 = a;
            return b;
        }

        fn main() -> i64 {
            return sample(7);
        }
        """,
        skip_optimize=True,
    )
    sample_body = _body_for_label(asm, mangle_function_symbol(("main",), "sample"))

    assert "    mov r10, qword ptr [rbp - 8]" in sample_body
    assert "    mov r11, r10" not in sample_body
    assert "    mov rax, r10" in sample_body


def test_emit_source_asm_merges_return_register_across_copy_group(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn sample() -> i64 {
            var a: i64 = 7;
            var b: i64 = a;
            return b;
        }

        fn main() -> i64 {
            return sample();
        }
        """,
        skip_optimize=True,
    )
    sample_body = _body_for_label(asm, mangle_function_symbol(("main",), "sample"))

    assert "    mov rax, 7" in sample_body
    assert "    mov r10, rax" not in sample_body
    assert "    mov rax, r10" not in sample_body


def test_emit_source_asm_uses_scratch_for_large_integer_operands(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn calc() -> u64 {
            var a: u64 = 1u;
            var b: u64 = a + 18446744073709551615u;
            return b;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )
    calc_label = mangle_function_symbol(("main",), "calc")
    calc_body = _body_for_label(asm, calc_label)

    assert "    mov rcx, 18446744073709551615" in calc_body
    assert "    add rax, rcx" in calc_body
    assert "    add rax, 18446744073709551615" not in calc_body


def test_emit_source_asm_can_disable_register_allocation_for_all_stack_fallback(tmp_path) -> None:
    source = """
        fn main() -> i64 {
            var base: i64 = 8;
            var neg: i64 = -base;
            return neg;
        }
        """

    allocated_asm = emit_source_asm(tmp_path, source, skip_optimize=True)
    stack_asm = emit_source_asm(
        tmp_path,
        source,
        skip_optimize=True,
        options=BackendTargetOptions(register_allocation_enabled=False),
    )

    assert allocated_asm != stack_asm
    assert "    mov rax, r10" in allocated_asm
    assert "    neg rax" in allocated_asm
    assert "    mov qword ptr [rbp - 8], r10" not in allocated_asm
    assert "    mov qword ptr [rbp - 16], r12" not in allocated_asm

    assert "    mov qword ptr [rbp - 8], rax" in stack_asm
    assert "    mov rax, qword ptr [rbp - 8]" in stack_asm
    assert "    mov qword ptr [rbp - 16], r12" not in stack_asm
    assert "    mov rax, rbx" not in stack_asm


def test_emit_source_asm_debug_comments_include_physical_register_assignments(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var value: i64 = 7;
            return value;
        }
        """,
        skip_optimize=True,
        options=BackendTargetOptions(emit_debug_comments=True),
    )

    assert "    # r0 -> rax" in asm


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

    assert "    cmp r11, rbx" in compare_body
    assert "    sete r10b" in compare_body
    assert "    setl r10b" in compare_body
    assert "    movzx r10, r10b" in compare_body
    assert "    cmp rax, rcx" not in compare_body


def test_emit_source_asm_selects_bool_comparison_into_allocated_destination(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn bool_eq(a: bool, b: bool) -> bool {
            var same: bool = a == b;
            return same;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )
    bool_eq_body = _body_for_label(asm, mangle_function_symbol(("main",), "bool_eq"))

    assert "    cmp rax, rcx" in bool_eq_body
    assert "    sete al" in bool_eq_body
    assert "    movzx rax, al" in bool_eq_body


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
