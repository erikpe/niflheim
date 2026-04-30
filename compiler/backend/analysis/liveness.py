from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.cfg import index_callable_cfg
from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlockId,
    BackendBoundsCheckInst,
    BackendBranchTerminator,
    BackendCallInst,
    BackendCallTarget,
    BackendCallableDecl,
    BackendCastInst,
    BackendConstInst,
    BackendCopyInst,
    BackendFieldLoadInst,
    BackendFieldStoreInst,
    BackendCallableOperand,
    BackendIndirectCallTarget,
    BackendInstruction,
    BackendInstId,
    BackendJumpTerminator,
    BackendNullCheckInst,
    BackendOperand,
    BackendRegId,
    BackendRegOperand,
    BackendReturnTerminator,
    BackendTerminator,
    BackendTrapTerminator,
    BackendTypeTestInst,
    BackendUnaryInst,
    BackendAllocObjectInst,
    BackendArrayAllocInst,
    BackendArrayLengthInst,
    BackendArrayLoadInst,
    BackendArraySliceInst,
    BackendArraySliceStoreInst,
    BackendArrayStoreInst,
)
from compiler.backend.ir._ordering import block_id_sort_key, inst_id_sort_key, reg_id_sort_key


@dataclass(frozen=True)
class BackendCallableLiveness:
    callable_decl: BackendCallableDecl
    live_in_by_block: dict[BackendBlockId, tuple[BackendRegId, ...]]
    live_out_by_block: dict[BackendBlockId, tuple[BackendRegId, ...]]
    live_before_instruction: dict[BackendInstId, tuple[BackendRegId, ...]]
    live_after_instruction: dict[BackendInstId, tuple[BackendRegId, ...]]
    live_before_terminator_by_block: dict[BackendBlockId, tuple[BackendRegId, ...]]

    def block_live_in(self, block_id: BackendBlockId) -> tuple[BackendRegId, ...]:
        return self.live_in_by_block.get(block_id, ())

    def block_live_out(self, block_id: BackendBlockId) -> tuple[BackendRegId, ...]:
        return self.live_out_by_block.get(block_id, ())

    def instruction_live_before(self, inst_id: BackendInstId) -> tuple[BackendRegId, ...]:
        return self.live_before_instruction.get(inst_id, ())

    def instruction_live_after(self, inst_id: BackendInstId) -> tuple[BackendRegId, ...]:
        return self.live_after_instruction.get(inst_id, ())

    def block_terminator_live_in(self, block_id: BackendBlockId) -> tuple[BackendRegId, ...]:
        return self.live_before_terminator_by_block.get(block_id, ())


def analyze_callable_liveness(callable_decl: BackendCallableDecl) -> BackendCallableLiveness:
    if callable_decl.is_extern or not callable_decl.blocks:
        return BackendCallableLiveness(
            callable_decl=callable_decl,
            live_in_by_block={},
            live_out_by_block={},
            live_before_instruction={},
            live_after_instruction={},
            live_before_terminator_by_block={},
        )

    cfg = index_callable_cfg(callable_decl)
    ordered_block_ids = tuple(cfg.reverse_postorder_block_ids)
    reverse_iteration_order = tuple(reversed(ordered_block_ids))
    live_in: dict[BackendBlockId, frozenset[BackendRegId]] = {
        block_id: frozenset() for block_id in ordered_block_ids
    }
    live_out: dict[BackendBlockId, frozenset[BackendRegId]] = {
        block_id: frozenset() for block_id in ordered_block_ids
    }

    changed = True
    while changed:
        changed = False
        for block_id in reverse_iteration_order:
            block = cfg.block_by_id[block_id]
            next_live_out = frozenset(
                reg_id
                for successor_block_id in cfg.successor_by_block[block_id]
                for reg_id in live_in[successor_block_id]
            )
            next_live_in = _block_live_in(block.instructions, block.terminator, next_live_out)
            if live_out[block_id] != next_live_out:
                live_out[block_id] = next_live_out
                changed = True
            if live_in[block_id] != next_live_in:
                live_in[block_id] = next_live_in
                changed = True

    live_before_instruction: dict[BackendInstId, tuple[BackendRegId, ...]] = {}
    live_after_instruction: dict[BackendInstId, tuple[BackendRegId, ...]] = {}
    live_before_terminator_by_block: dict[BackendBlockId, tuple[BackendRegId, ...]] = {}
    for block_id in ordered_block_ids:
        block = cfg.block_by_id[block_id]
        block_before_instructions, block_after_instructions, terminator_live_in = _block_instruction_liveness(
            block.instructions,
            block.terminator,
            live_out[block_id],
        )
        live_before_instruction.update(block_before_instructions)
        live_after_instruction.update(block_after_instructions)
        live_before_terminator_by_block[block_id] = _sorted_reg_tuple(terminator_live_in)

    return BackendCallableLiveness(
        callable_decl=callable_decl,
        live_in_by_block={
            block_id: _sorted_reg_tuple(live_in[block_id])
            for block_id in sorted(ordered_block_ids, key=block_id_sort_key)
        },
        live_out_by_block={
            block_id: _sorted_reg_tuple(live_out[block_id])
            for block_id in sorted(ordered_block_ids, key=block_id_sort_key)
        },
        live_before_instruction={
            inst_id: live_before_instruction[inst_id]
            for inst_id in sorted(live_before_instruction, key=inst_id_sort_key)
        },
        live_after_instruction={
            inst_id: live_after_instruction[inst_id]
            for inst_id in sorted(live_after_instruction, key=inst_id_sort_key)
        },
        live_before_terminator_by_block={
            block_id: live_before_terminator_by_block[block_id]
            for block_id in sorted(live_before_terminator_by_block, key=block_id_sort_key)
        },
    )


def operand_use_regs(operand: BackendOperand) -> tuple[BackendRegId, ...]:
    if isinstance(operand, BackendRegOperand):
        return (operand.reg_id,)
    if isinstance(operand, BackendCallableOperand):
        return ()
    return ()


def instruction_def_reg(instruction: BackendInstruction) -> BackendRegId | None:
    if isinstance(
        instruction,
        (
            BackendConstInst,
            BackendCopyInst,
            BackendUnaryInst,
            BackendBinaryInst,
            BackendCastInst,
            BackendTypeTestInst,
            BackendAllocObjectInst,
            BackendFieldLoadInst,
            BackendArrayAllocInst,
            BackendArrayLengthInst,
            BackendArrayLoadInst,
            BackendArraySliceInst,
        ),
    ):
        return instruction.dest
    if isinstance(instruction, BackendCallInst):
        return instruction.dest
    return None


def instruction_use_regs(instruction: BackendInstruction) -> tuple[BackendRegId, ...]:
    if isinstance(instruction, BackendConstInst):
        return ()
    if isinstance(instruction, BackendCopyInst):
        return operand_use_regs(instruction.source)
    if isinstance(instruction, (BackendUnaryInst, BackendCastInst, BackendTypeTestInst)):
        return operand_use_regs(instruction.operand)
    if isinstance(instruction, BackendBinaryInst):
        return _merge_reg_uses(instruction.left, instruction.right)
    if isinstance(instruction, BackendAllocObjectInst):
        return ()
    if isinstance(instruction, BackendFieldLoadInst):
        return operand_use_regs(instruction.object_ref)
    if isinstance(instruction, BackendFieldStoreInst):
        return _merge_reg_uses(instruction.object_ref, instruction.value)
    if isinstance(instruction, BackendArrayAllocInst):
        return operand_use_regs(instruction.length)
    if isinstance(instruction, BackendArrayLengthInst):
        return operand_use_regs(instruction.array_ref)
    if isinstance(instruction, BackendArrayLoadInst):
        return _merge_reg_uses(instruction.array_ref, instruction.index)
    if isinstance(instruction, BackendArrayStoreInst):
        return _merge_reg_uses(instruction.array_ref, instruction.index, instruction.value)
    if isinstance(instruction, BackendArraySliceInst):
        return _merge_reg_uses(instruction.array_ref, instruction.begin, instruction.end)
    if isinstance(instruction, BackendArraySliceStoreInst):
        return _merge_reg_uses(instruction.array_ref, instruction.begin, instruction.end, instruction.value)
    if isinstance(instruction, BackendNullCheckInst):
        return operand_use_regs(instruction.value)
    if isinstance(instruction, BackendBoundsCheckInst):
        return _merge_reg_uses(instruction.array_ref, instruction.index)
    if isinstance(instruction, BackendCallInst):
        return _merge_reg_uses(*instruction.args, *_call_target_operands(instruction.target))
    raise TypeError(f"Unsupported backend instruction type '{type(instruction).__name__}'")


def terminator_use_regs(terminator: BackendTerminator) -> tuple[BackendRegId, ...]:
    if isinstance(terminator, BackendJumpTerminator):
        return ()
    if isinstance(terminator, BackendBranchTerminator):
        return operand_use_regs(terminator.condition)
    if isinstance(terminator, BackendReturnTerminator):
        return () if terminator.value is None else operand_use_regs(terminator.value)
    if isinstance(terminator, BackendTrapTerminator):
        return ()
    raise TypeError(f"Unsupported backend terminator type '{type(terminator).__name__}'")


def transfer_instruction_live_set(
    instruction: BackendInstruction,
    live_after: frozenset[BackendRegId] | set[BackendRegId] | tuple[BackendRegId, ...],
) -> frozenset[BackendRegId]:
    live_before = set(live_after)
    destination = instruction_def_reg(instruction)
    if destination is not None and destination in live_before:
        live_before.remove(destination)
    live_before.update(instruction_use_regs(instruction))
    return frozenset(live_before)


def transfer_terminator_live_set(
    terminator: BackendTerminator,
    live_out: frozenset[BackendRegId] | set[BackendRegId] | tuple[BackendRegId, ...],
) -> frozenset[BackendRegId]:
    live_before = set(live_out)
    live_before.update(terminator_use_regs(terminator))
    return frozenset(live_before)


def _block_live_in(
    instructions: tuple[BackendInstruction, ...],
    terminator: BackendTerminator,
    live_out: frozenset[BackendRegId],
) -> frozenset[BackendRegId]:
    live = transfer_terminator_live_set(terminator, live_out)
    for instruction in reversed(instructions):
        live = transfer_instruction_live_set(instruction, live)
    return live


def _block_instruction_liveness(
    instructions: tuple[BackendInstruction, ...],
    terminator: BackendTerminator,
    live_out: frozenset[BackendRegId],
) -> tuple[
    dict[BackendInstId, tuple[BackendRegId, ...]],
    dict[BackendInstId, tuple[BackendRegId, ...]],
    frozenset[BackendRegId],
]:
    live = transfer_terminator_live_set(terminator, live_out)
    live_before_instruction: dict[BackendInstId, tuple[BackendRegId, ...]] = {}
    live_after_instruction: dict[BackendInstId, tuple[BackendRegId, ...]] = {}
    for instruction in reversed(instructions):
        live_after_instruction[instruction.inst_id] = _sorted_reg_tuple(live)
        live = transfer_instruction_live_set(instruction, live)
        live_before_instruction[instruction.inst_id] = _sorted_reg_tuple(live)
    return live_before_instruction, live_after_instruction, live


def _call_target_operands(target: BackendCallTarget) -> tuple[BackendOperand, ...]:
    if isinstance(target, BackendIndirectCallTarget):
        return (target.callee,)
    return ()


def _merge_reg_uses(*operands: BackendOperand) -> tuple[BackendRegId, ...]:
    used_regs: set[BackendRegId] = set()
    for operand in operands:
        used_regs.update(operand_use_regs(operand))
    return _sorted_reg_tuple(used_regs)


def _sorted_reg_tuple(reg_ids: set[BackendRegId] | frozenset[BackendRegId] | tuple[BackendRegId, ...]) -> tuple[BackendRegId, ...]:
    return tuple(sorted(reg_ids, key=reg_id_sort_key))