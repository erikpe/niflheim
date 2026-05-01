from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.backend.analysis import (
    analyze_callable_liveness,
    instruction_def_reg,
    instruction_use_regs,
    terminator_use_regs,
    transfer_instruction_live_set,
    transfer_terminator_live_set,
)
from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBoolConst,
    BackendCallableDecl,
    BackendCastInst,
    BackendConstOperand,
    BackendConstInst,
    BackendCopyInst,
    BackendDoubleConst,
    BackendIntConst,
    BackendInstruction,
    BackendNullConst,
    BackendProgram,
    BackendRegOperand,
    BackendTypeTestInst,
    BackendUnitConst,
    BackendUnaryInst,
)
from compiler.backend.ir._ordering import reg_id_sort_key
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_NULL, TYPE_NAME_UNIT
from compiler.common.logging import get_logger
from compiler.semantic.operations import BinaryOpKind, CastSemanticsKind
from compiler.semantic.types import semantic_type_canonical_name


@dataclass
class _DeadPureDefinitionStats:
    removed_instructions: int = 0
    removed_registers: int = 0
    optimized_callables: int = 0


def dead_pure_definition_elimination(program: BackendProgram) -> BackendProgram:
    logger = get_logger(__name__)
    stats = _DeadPureDefinitionStats()
    optimized_callables = tuple(_eliminate_callable(callable_decl, stats) for callable_decl in program.callables)
    optimized_program = replace(program, callables=optimized_callables)
    logger.debugv(
        1,
        "Backend optimization pass dead_pure_definition_elimination removed %d instructions, %d registers across %d callables",
        stats.removed_instructions,
        stats.removed_registers,
        stats.optimized_callables,
    )
    return optimized_program


def instruction_is_dead_eliminable(
    instruction: BackendInstruction,
    *,
    register_type_name_by_reg_id: dict | None = None,
) -> bool:
    if isinstance(instruction, (BackendConstInst, BackendCopyInst, BackendUnaryInst, BackendTypeTestInst)):
        return True
    if isinstance(instruction, BackendCastInst):
        return not _cast_can_have_observable_effect(
            instruction,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
    if isinstance(instruction, BackendBinaryInst):
        return instruction.op.kind not in {
            BinaryOpKind.DIVIDE,
            BinaryOpKind.REMAINDER,
            BinaryOpKind.POWER,
            BinaryOpKind.SHIFT_LEFT,
            BinaryOpKind.SHIFT_RIGHT,
        }
    return False


def _eliminate_callable(
    callable_decl: BackendCallableDecl,
    stats: _DeadPureDefinitionStats,
) -> BackendCallableDecl:
    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    current = callable_decl
    callable_removed_instructions = 0
    while True:
        next_callable, removed_count = _eliminate_callable_once(current)
        callable_removed_instructions += removed_count
        if removed_count == 0:
            break
        current = next_callable

    trimmed_callable, removed_register_count = _remove_unreferenced_registers(current)
    if callable_removed_instructions or removed_register_count:
        stats.optimized_callables += 1
        stats.removed_instructions += callable_removed_instructions
        stats.removed_registers += removed_register_count
    return trimmed_callable


def _eliminate_callable_once(callable_decl: BackendCallableDecl) -> tuple[BackendCallableDecl, int]:
    liveness = analyze_callable_liveness(callable_decl)
    register_type_name_by_reg_id = {
        register.reg_id: semantic_type_canonical_name(register.type_ref)
        for register in callable_decl.registers
    }
    rewritten_blocks: list[BackendBlock] = []
    removed_count = 0
    for block in callable_decl.blocks:
        kept_reversed: list[BackendInstruction] = []
        live = set(transfer_terminator_live_set(block.terminator, liveness.block_live_out(block.block_id)))
        for instruction in reversed(block.instructions):
            destination = instruction_def_reg(instruction)
            if (
                destination is not None
                and destination not in live
                and instruction_is_dead_eliminable(
                    instruction,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                )
            ):
                removed_count += 1
                continue
            kept_reversed.append(instruction)
            live = set(transfer_instruction_live_set(instruction, live))
        rewritten_blocks.append(replace(block, instructions=tuple(reversed(kept_reversed))))

    if removed_count == 0:
        return callable_decl, 0
    return replace(callable_decl, blocks=tuple(rewritten_blocks)), removed_count


def _remove_unreferenced_registers(callable_decl: BackendCallableDecl) -> tuple[BackendCallableDecl, int]:
    referenced_reg_ids = set(callable_decl.param_regs)
    if callable_decl.receiver_reg is not None:
        referenced_reg_ids.add(callable_decl.receiver_reg)
    for block in callable_decl.blocks:
        for instruction in block.instructions:
            destination = instruction_def_reg(instruction)
            if destination is not None:
                referenced_reg_ids.add(destination)
            referenced_reg_ids.update(instruction_use_regs(instruction))
        referenced_reg_ids.update(terminator_use_regs(block.terminator))

    kept_registers = tuple(
        register
        for register in callable_decl.registers
        if register.reg_id in referenced_reg_ids
    )
    removed_count = len(callable_decl.registers) - len(kept_registers)
    if removed_count == 0:
        return callable_decl, 0
    return replace(
        callable_decl,
        registers=tuple(sorted(kept_registers, key=lambda register: reg_id_sort_key(register.reg_id))),
    ), removed_count


def _cast_can_have_observable_effect(
    instruction: BackendCastInst,
    *,
    register_type_name_by_reg_id: dict | None,
) -> bool:
    if instruction.trap_on_failure:
        return True
    source_type_name = _operand_type_name(instruction.operand, register_type_name_by_reg_id)
    return instruction.cast_kind is CastSemanticsKind.TO_INTEGER and source_type_name == TYPE_NAME_DOUBLE


def _operand_type_name(operand, register_type_name_by_reg_id: dict | None) -> str | None:
    if isinstance(operand, BackendRegOperand):
        if register_type_name_by_reg_id is None:
            return None
        return register_type_name_by_reg_id.get(operand.reg_id)
    if isinstance(operand, BackendConstOperand):
        constant = operand.constant
        if isinstance(constant, BackendDoubleConst):
            return TYPE_NAME_DOUBLE
        if isinstance(constant, BackendIntConst):
            return constant.type_name
        if isinstance(constant, BackendBoolConst):
            return TYPE_NAME_BOOL
        if isinstance(constant, BackendNullConst):
            return TYPE_NAME_NULL
        if isinstance(constant, BackendUnitConst):
            return TYPE_NAME_UNIT
    return None


__all__ = [
    "dead_pure_definition_elimination",
    "instruction_is_dead_eliminable",
]
