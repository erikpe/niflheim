from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.backend.analysis import (
    analyze_callable_liveness,
    instruction_def_reg,
)
from compiler.backend.ir import (
    BackendArrayAllocInst,
    BackendArrayLengthInst,
    BackendArrayLoadInst,
    BackendArraySliceInst,
    BackendArraySliceStoreInst,
    BackendArrayStoreInst,
    BackendBinaryInst,
    BackendBlock,
    BackendBoundsCheckInst,
    BackendBranchTerminator,
    BackendCallInst,
    BackendCastInst,
    BackendCopyInst,
    BackendFieldLoadInst,
    BackendFieldStoreInst,
    BackendIndirectCallTarget,
    BackendInstruction,
    BackendJumpTerminator,
    BackendNullCheckInst,
    BackendOperand,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendReturnTerminator,
    BackendTerminator,
    BackendTypeTestInst,
    BackendUnaryInst,
)
from compiler.common.logging import get_logger


@dataclass
class _TrivialCopyStats:
    removed_self_copies: int = 0
    removed_dead_copies: int = 0
    propagated_operands: int = 0
    optimized_callables: int = 0


def trivial_copy_elimination(program: BackendProgram) -> BackendProgram:
    logger = get_logger(__name__)
    stats = _TrivialCopyStats()
    optimized_callables = tuple(_eliminate_callable(callable_decl, stats) for callable_decl in program.callables)
    optimized_program = replace(program, callables=optimized_callables)
    logger.debugv(
        1,
        "Backend optimization pass trivial_copy_elimination removed %d self copies, %d dead copies, propagated %d operands across %d callables",
        stats.removed_self_copies,
        stats.removed_dead_copies,
        stats.propagated_operands,
        stats.optimized_callables,
    )
    return optimized_program


def _eliminate_callable(callable_decl, stats: _TrivialCopyStats):
    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    rewritten_blocks: list[BackendBlock] = []
    callable_changed = False
    for block in callable_decl.blocks:
        rewritten_block, block_changed = _rewrite_block(block, stats=stats)
        rewritten_blocks.append(rewritten_block)
        callable_changed = callable_changed or block_changed
    rewritten_callable = replace(callable_decl, blocks=tuple(rewritten_blocks)) if callable_changed else callable_decl
    rewritten_callable, removed_dead_copy_count = _remove_dead_copies(rewritten_callable)
    if removed_dead_copy_count:
        stats.removed_dead_copies += removed_dead_copy_count
        callable_changed = True
    if callable_changed:
        stats.optimized_callables += 1
        return rewritten_callable
    return callable_decl


def _rewrite_block(block: BackendBlock, *, stats: _TrivialCopyStats) -> tuple[BackendBlock, bool]:
    copy_by_reg: dict[BackendRegId, BackendOperand] = {}
    rewritten_instructions: list[BackendInstruction] = []
    changed = False

    for instruction in block.instructions:
        rewritten_instruction, propagated_count = _rewrite_instruction_operands(instruction, copy_by_reg)
        if propagated_count:
            stats.propagated_operands += propagated_count
            changed = True

        destination = instruction_def_reg(rewritten_instruction)
        if destination is not None:
            _invalidate_copy_facts_for_definition(copy_by_reg, destination)

        if isinstance(rewritten_instruction, BackendCopyInst):
            if isinstance(rewritten_instruction.source, BackendRegOperand) and rewritten_instruction.source.reg_id == rewritten_instruction.dest:
                stats.removed_self_copies += 1
                changed = True
                continue
            copy_by_reg[rewritten_instruction.dest] = rewritten_instruction.source

        rewritten_instructions.append(rewritten_instruction)

    rewritten_terminator, propagated_count = _rewrite_terminator_operands(block.terminator, copy_by_reg)
    if propagated_count:
        stats.propagated_operands += propagated_count
        changed = True

    if not changed:
        return block, False
    return replace(block, instructions=tuple(rewritten_instructions), terminator=rewritten_terminator), True


def _remove_dead_copies(callable_decl) -> tuple[object, int]:
    liveness = analyze_callable_liveness(callable_decl)
    rewritten_blocks: list[BackendBlock] = []
    removed_count = 0
    for block in callable_decl.blocks:
        rewritten_instructions: list[BackendInstruction] = []
        for instruction in block.instructions:
            if isinstance(instruction, BackendCopyInst) and instruction.dest not in liveness.instruction_live_after(instruction.inst_id):
                removed_count += 1
                continue
            rewritten_instructions.append(instruction)
        rewritten_blocks.append(replace(block, instructions=tuple(rewritten_instructions)))
    if removed_count == 0:
        return callable_decl, 0
    return replace(callable_decl, blocks=tuple(rewritten_blocks)), removed_count


def _rewrite_instruction_operands(
    instruction: BackendInstruction,
    copy_by_reg: dict[BackendRegId, BackendOperand],
) -> tuple[BackendInstruction, int]:
    if isinstance(instruction, BackendCopyInst):
        source, count = _rewrite_operand(instruction.source, copy_by_reg)
        return replace(instruction, source=source), count
    if isinstance(instruction, BackendUnaryInst):
        operand, count = _rewrite_operand(instruction.operand, copy_by_reg)
        return replace(instruction, operand=operand), count
    if isinstance(instruction, BackendBinaryInst):
        left, left_count = _rewrite_operand(instruction.left, copy_by_reg)
        right, right_count = _rewrite_operand(instruction.right, copy_by_reg)
        return replace(instruction, left=left, right=right), left_count + right_count
    if isinstance(instruction, BackendCastInst):
        operand, count = _rewrite_operand(instruction.operand, copy_by_reg)
        return replace(instruction, operand=operand), count
    if isinstance(instruction, BackendTypeTestInst):
        operand, count = _rewrite_operand(instruction.operand, copy_by_reg)
        return replace(instruction, operand=operand), count
    if isinstance(instruction, BackendFieldLoadInst):
        object_ref, count = _rewrite_operand(instruction.object_ref, copy_by_reg)
        return replace(instruction, object_ref=object_ref), count
    if isinstance(instruction, BackendFieldStoreInst):
        object_ref, object_count = _rewrite_operand(instruction.object_ref, copy_by_reg)
        value, value_count = _rewrite_operand(instruction.value, copy_by_reg)
        return replace(instruction, object_ref=object_ref, value=value), object_count + value_count
    if isinstance(instruction, BackendArrayAllocInst):
        length, count = _rewrite_operand(instruction.length, copy_by_reg)
        return replace(instruction, length=length), count
    if isinstance(instruction, BackendArrayLengthInst):
        array_ref, count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        return replace(instruction, array_ref=array_ref), count
    if isinstance(instruction, BackendArrayLoadInst):
        array_ref, array_count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        index, index_count = _rewrite_operand(instruction.index, copy_by_reg)
        return replace(instruction, array_ref=array_ref, index=index), array_count + index_count
    if isinstance(instruction, BackendArrayStoreInst):
        array_ref, array_count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        index, index_count = _rewrite_operand(instruction.index, copy_by_reg)
        value, value_count = _rewrite_operand(instruction.value, copy_by_reg)
        return replace(instruction, array_ref=array_ref, index=index, value=value), array_count + index_count + value_count
    if isinstance(instruction, BackendArraySliceInst):
        array_ref, array_count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        begin, begin_count = _rewrite_operand(instruction.begin, copy_by_reg)
        end, end_count = _rewrite_operand(instruction.end, copy_by_reg)
        return replace(instruction, array_ref=array_ref, begin=begin, end=end), array_count + begin_count + end_count
    if isinstance(instruction, BackendArraySliceStoreInst):
        array_ref, array_count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        begin, begin_count = _rewrite_operand(instruction.begin, copy_by_reg)
        end, end_count = _rewrite_operand(instruction.end, copy_by_reg)
        value, value_count = _rewrite_operand(instruction.value, copy_by_reg)
        return (
            replace(instruction, array_ref=array_ref, begin=begin, end=end, value=value),
            array_count + begin_count + end_count + value_count,
        )
    if isinstance(instruction, BackendNullCheckInst):
        value, count = _rewrite_operand(instruction.value, copy_by_reg)
        return replace(instruction, value=value), count
    if isinstance(instruction, BackendBoundsCheckInst):
        array_ref, array_count = _rewrite_operand(instruction.array_ref, copy_by_reg)
        index, index_count = _rewrite_operand(instruction.index, copy_by_reg)
        return replace(instruction, array_ref=array_ref, index=index), array_count + index_count
    if isinstance(instruction, BackendCallInst):
        args, arg_count = _rewrite_operands(instruction.args, copy_by_reg)
        target, target_count = _rewrite_call_target(instruction.target, copy_by_reg)
        return replace(instruction, args=args, target=target), arg_count + target_count
    return instruction, 0


def _rewrite_terminator_operands(
    terminator: BackendTerminator,
    copy_by_reg: dict[BackendRegId, BackendOperand],
) -> tuple[BackendTerminator, int]:
    if isinstance(terminator, BackendBranchTerminator):
        condition, count = _rewrite_operand(terminator.condition, copy_by_reg)
        return replace(terminator, condition=condition), count
    if isinstance(terminator, BackendReturnTerminator) and terminator.value is not None:
        value, count = _rewrite_operand(terminator.value, copy_by_reg)
        return replace(terminator, value=value), count
    if isinstance(terminator, BackendJumpTerminator):
        return terminator, 0
    return terminator, 0


def _rewrite_call_target(target, copy_by_reg: dict[BackendRegId, BackendOperand]):
    if isinstance(target, BackendIndirectCallTarget):
        callee, count = _rewrite_operand(target.callee, copy_by_reg)
        return replace(target, callee=callee), count
    return target, 0


def _rewrite_operands(
    operands: tuple[BackendOperand, ...],
    copy_by_reg: dict[BackendRegId, BackendOperand],
) -> tuple[tuple[BackendOperand, ...], int]:
    rewritten_operands: list[BackendOperand] = []
    propagated_count = 0
    for operand in operands:
        rewritten_operand, count = _rewrite_operand(operand, copy_by_reg)
        rewritten_operands.append(rewritten_operand)
        propagated_count += count
    return tuple(rewritten_operands), propagated_count


def _rewrite_operand(
    operand: BackendOperand,
    copy_by_reg: dict[BackendRegId, BackendOperand],
) -> tuple[BackendOperand, int]:
    if isinstance(operand, BackendRegOperand) and operand.reg_id in copy_by_reg:
        return copy_by_reg[operand.reg_id], 1
    return operand, 0


def _invalidate_copy_facts_for_definition(copy_by_reg: dict[BackendRegId, BackendOperand], reg_id: BackendRegId) -> None:
    stale_reg_ids = [
        copied_reg_id
        for copied_reg_id, source in copy_by_reg.items()
        if copied_reg_id == reg_id or _operand_mentions_reg(source, reg_id)
    ]
    for stale_reg_id in stale_reg_ids:
        del copy_by_reg[stale_reg_id]


def _operand_mentions_reg(operand: BackendOperand, reg_id: BackendRegId) -> bool:
    return isinstance(operand, BackendRegOperand) and operand.reg_id == reg_id


__all__ = ["trivial_copy_elimination"]
