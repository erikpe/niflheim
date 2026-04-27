from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.backend.ir import BackendBlock, BackendCastInst, BackendConstInst, BackendDoubleConst, BackendInstId
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import (
    TARGET_NAME,
    X86_64_SYSV_ABI,
    X86_64_SYSV_TARGET,
    X86AsmBuilder,
    X86_64SysVLegalityError,
    check_x86_64_sysv_legality,
    emit_x86_64_sysv_asm,
    format_stack_slot_operand,
)
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.operations import CastSemanticsKind
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import (
    FIXTURE_ENTRY_FUNCTION_ID,
    callable_by_id,
    make_source_span,
    one_constructor_backend_program,
    one_function_backend_program,
    one_method_backend_program,
)
from tests.compiler.backend.targets.x86_64_sysv.helpers import make_target_input, with_root_slot


def test_x86_64_sysv_exports_explicit_target_surface() -> None:
    assert TARGET_NAME == "x86_64_sysv"
    assert X86_64_SYSV_TARGET.name == TARGET_NAME
    assert callable(emit_x86_64_sysv_asm)
    assert callable(check_x86_64_sysv_legality)


def test_reduced_sysv_abi_plans_integer_like_arguments_and_returns() -> None:
    param_types = tuple(
        semantic_primitive_type_ref(type_name)
        for type_name in (TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_BOOL, TYPE_NAME_U8, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_BOOL)
    )

    locations = X86_64_SYSV_ABI.plan_argument_locations(param_types)

    assert tuple(location.kind for location in locations) == (
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "stack",
    )
    assert tuple(location.register_name for location in locations[:6]) == ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
    assert locations[6].stack_slot_index == 0
    assert X86_64_SYSV_ABI.return_register_for_type(semantic_primitive_type_ref(TYPE_NAME_BOOL)) == "rax"
    assert X86_64_SYSV_ABI.return_register_for_type(None) is None


def test_reduced_sysv_alignment_helpers_are_stable() -> None:
    assert X86_64_SYSV_ABI.stack_alignment_bytes == 16
    assert X86_64_SYSV_ABI.stack_size_is_aligned(0) is True
    assert X86_64_SYSV_ABI.stack_size_is_aligned(16) is True
    assert X86_64_SYSV_ABI.stack_size_is_aligned(8) is False
    assert X86_64_SYSV_ABI.align_stack_size(1) == 16
    assert X86_64_SYSV_ABI.align_stack_size(16) == 16
    assert X86_64_SYSV_ABI.align_stack_size(17) == 32


def test_reduced_sysv_call_stack_helpers_are_stable() -> None:
    assert X86_64_SYSV_ABI.outgoing_stack_arg_slot_count(0) == 0
    assert X86_64_SYSV_ABI.outgoing_stack_arg_slot_count(6) == 0
    assert X86_64_SYSV_ABI.outgoing_stack_arg_slot_count(7) == 1
    assert X86_64_SYSV_ABI.outgoing_stack_arg_slot_count(8) == 2
    assert X86_64_SYSV_ABI.call_stack_reservation_bytes(0) == 0
    assert X86_64_SYSV_ABI.call_stack_reservation_bytes(1) == 16
    assert X86_64_SYSV_ABI.call_stack_reservation_bytes(2) == 16
    assert X86_64_SYSV_ABI.call_stack_reservation_bytes(3) == 32


@pytest.mark.parametrize("builder", [one_method_backend_program, one_constructor_backend_program])
def test_legality_checker_rejects_receiver_aware_callables(builder) -> None:
    with pytest.raises(X86_64SysVLegalityError, match="only supports plain functions"):
        check_x86_64_sysv_legality(make_target_input(builder()))


def test_legality_checker_rejects_double_types() -> None:
    program = one_function_backend_program()
    callable_decl = callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID)
    double_reg = replace(
        callable_decl.registers[0],
        type_ref=semantic_primitive_type_ref(TYPE_NAME_DOUBLE),
    )
    double_instruction = replace(
        callable_decl.blocks[0].instructions[0],
        constant=BackendDoubleConst(value=1.5),
    )
    updated_callable = replace(
        callable_decl,
        signature=replace(
            callable_decl.signature,
            return_type=semantic_primitive_type_ref(TYPE_NAME_DOUBLE),
        ),
        registers=(double_reg,),
        blocks=(
            replace(
                callable_decl.blocks[0],
                instructions=(double_instruction,),
            ),
        ),
    )
    updated_program = replace(program, callables=(updated_callable,))

    with pytest.raises(X86_64SysVLegalityError, match="unsupported reduced-scope return type 'double'"):
        check_x86_64_sysv_legality(make_target_input(updated_program))


def test_legality_checker_rejects_unsupported_instruction_families() -> None:
    program = one_function_backend_program()
    callable_decl = callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID)
    bool_reg = replace(
        callable_decl.registers[0],
        reg_id=replace(callable_decl.registers[0].reg_id, ordinal=1),
        type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        debug_name="flag0",
    )
    cast_instruction = BackendCastInst(
        inst_id=BackendInstId(owner_id=callable_decl.callable_id, ordinal=1),
        dest=bool_reg.reg_id,
        cast_kind=CastSemanticsKind.TO_BOOL,
        operand=callable_decl.blocks[0].terminator.value,
        target_type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        trap_on_failure=False,
        span=make_source_span(path="fixtures/cast.nif", start_offset=8, end_offset=12, start_column=9),
    )
    updated_callable = replace(
        callable_decl,
        registers=(*callable_decl.registers, bool_reg),
        blocks=(
            replace(
                callable_decl.blocks[0],
                instructions=(*callable_decl.blocks[0].instructions, cast_instruction),
            ),
        ),
    )
    updated_program = replace(program, callables=(updated_callable,))

    with pytest.raises(X86_64SysVLegalityError, match="instruction 'BackendCastInst' is not supported"):
        check_x86_64_sysv_legality(make_target_input(updated_program))


def test_legality_checker_rejects_root_slot_requirements() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    with pytest.raises(X86_64SysVLegalityError, match="does not yet support GC root-slot setup"):
        check_x86_64_sysv_legality(
            with_root_slot(
                target_input,
                callable_id=FIXTURE_ENTRY_FUNCTION_ID,
                reg_id=callable_decl.registers[0].reg_id,
            )
        )


def test_asm_helpers_render_stable_text() -> None:
    builder = X86AsmBuilder(emit_debug_comments=True)
    builder.section(".text")
    builder.global_symbol("demo")
    builder.blank()
    builder.label("demo")
    builder.comment("entry")
    builder.instruction("mov", "rax", format_stack_slot_operand("rbp", -16))

    assert builder.build() == "\n".join(
        [
            ".intel_syntax noprefix",
            ".section .text",
            ".globl demo",
            "",
            "demo:",
            "    # entry",
            "    mov rax, qword ptr [rbp - 16]",
        ]
    )


def test_entrypoint_validates_legality_before_emission() -> None:
    asm = emit_x86_64_sysv_asm(make_target_input(one_function_backend_program()), options=BackendTargetOptions()).assembly_text

    assert ".globl main" in asm
    assert "    mov rax, 0" in asm
    assert "    jmp .Lmain_epilogue" in asm