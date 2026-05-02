from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.liveness import instruction_def_reg, instruction_use_regs, terminator_use_regs
from compiler.backend.analysis.safepoints import instruction_is_safepoint, register_is_gc_reference
from compiler.backend.ir import (
    BackendBlockId,
    BackendCallInst,
    BackendCallableDecl,
    BackendInstId,
    BackendRegId,
)
from compiler.backend.ir._ordering import reg_id_sort_key
from compiler.backend.targets.x86_64_sysv.locations import X86_64SysVRegisterClass, register_class_for_type
from compiler.backend.targets.x86_64_sysv.pipeline import X86_64SysVCallablePlan


@dataclass(frozen=True, slots=True)
class X86_64SysVInstructionPositions:
    instruction_position_by_id: dict[BackendInstId, int]
    terminator_position_by_block_id: dict[BackendBlockId, int]

    def instruction_position(self, inst_id: BackendInstId) -> int:
        return self.instruction_position_by_id[inst_id]

    def terminator_position(self, block_id: BackendBlockId) -> int:
        return self.terminator_position_by_block_id[block_id]


@dataclass(frozen=True, slots=True)
class X86_64SysVLiveInterval:
    reg_id: BackendRegId
    start_position: int
    end_position: int
    register_class: X86_64SysVRegisterClass
    crosses_call: bool
    is_gc_reference: bool
    live_at_safepoint: bool


def build_instruction_positions(callable_plan: X86_64SysVCallablePlan) -> X86_64SysVInstructionPositions:
    callable_decl = callable_plan.callable_decl
    if callable_decl.is_extern or not callable_decl.blocks:
        return X86_64SysVInstructionPositions(
            instruction_position_by_id={},
            terminator_position_by_block_id={},
        )

    block_by_id = {block.block_id: block for block in callable_decl.blocks}
    next_position = 0
    instruction_position_by_id: dict[BackendInstId, int] = {}
    terminator_position_by_block_id: dict[BackendBlockId, int] = {}
    for block_id in callable_plan.ordered_block_ids:
        block = block_by_id[block_id]
        for instruction in block.instructions:
            instruction_position_by_id[instruction.inst_id] = next_position
            next_position += 1
        terminator_position_by_block_id[block.block_id] = next_position
        next_position += 1

    return X86_64SysVInstructionPositions(
        instruction_position_by_id=instruction_position_by_id,
        terminator_position_by_block_id=terminator_position_by_block_id,
    )


def build_live_intervals(callable_plan: X86_64SysVCallablePlan) -> tuple[X86_64SysVLiveInterval, ...]:
    callable_decl = callable_plan.callable_decl
    if callable_decl.is_extern or not callable_decl.blocks:
        return ()

    positions = build_instruction_positions(callable_plan)
    register_by_id = {register.reg_id: register for register in callable_decl.registers}
    interval_bounds: dict[BackendRegId, tuple[int, int]] = {}

    def touch(reg_id: BackendRegId, position: int) -> None:
        if reg_id not in register_by_id:
            return
        current_bounds = interval_bounds.get(reg_id)
        if current_bounds is None:
            interval_bounds[reg_id] = (position, position)
            return
        start_position, end_position = current_bounds
        interval_bounds[reg_id] = (min(start_position, position), max(end_position, position))

    block_by_id = {block.block_id: block for block in callable_decl.blocks}

    for reg_id in callable_decl.param_regs:
        touch(reg_id, 0)
    if callable_decl.receiver_reg is not None:
        touch(callable_decl.receiver_reg, 0)

    for block_id in callable_plan.ordered_block_ids:
        block = block_by_id[block_id]
        terminator_position = positions.terminator_position(block_id)
        for reg_id in callable_plan.analysis.liveness.block_live_in(block_id):
            first_block_position = (
                terminator_position
                if not block.instructions
                else positions.instruction_position(block.instructions[0].inst_id)
            )
            touch(reg_id, first_block_position)
        for reg_id in callable_plan.analysis.liveness.block_live_out(block_id):
            touch(reg_id, terminator_position)

        for instruction in block.instructions:
            position = positions.instruction_position(instruction.inst_id)
            definition = instruction_def_reg(instruction)
            if definition is not None:
                touch(definition, position)
            for reg_id in instruction_use_regs(instruction):
                touch(reg_id, position)
            for reg_id in callable_plan.analysis.liveness.instruction_live_before(instruction.inst_id):
                touch(reg_id, position)
            for reg_id in callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id):
                touch(reg_id, position)

        for reg_id in terminator_use_regs(block.terminator):
            touch(reg_id, terminator_position)

    call_crossing_reg_ids = _call_crossing_reg_ids(callable_plan)
    safepoint_live_reg_ids = _safepoint_live_reg_ids(callable_plan)

    intervals = tuple(
        X86_64SysVLiveInterval(
            reg_id=reg_id,
            start_position=start_position,
            end_position=end_position,
            register_class=register_class_for_type(register_by_id[reg_id].type_ref),
            crosses_call=reg_id in call_crossing_reg_ids,
            is_gc_reference=register_is_gc_reference(register_by_id[reg_id]),
            live_at_safepoint=reg_id in safepoint_live_reg_ids,
        )
        for reg_id, (start_position, end_position) in interval_bounds.items()
    )
    return tuple(
        sorted(
            intervals,
            key=lambda interval: (
                interval.start_position,
                interval.end_position,
                reg_id_sort_key(interval.reg_id),
            ),
        )
    )


def _call_crossing_reg_ids(callable_plan: X86_64SysVCallablePlan) -> frozenset[BackendRegId]:
    call_crossing: set[BackendRegId] = set()
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if instruction.dest is not None:
                live_after.discard(instruction.dest)
            call_crossing.update(live_after)
    return frozenset(call_crossing)


def _safepoint_live_reg_ids(callable_plan: X86_64SysVCallablePlan) -> frozenset[BackendRegId]:
    safepoint_live: set[BackendRegId] = set()
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not instruction_is_safepoint(instruction):
                continue
            live_regs = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            live_regs.update(instruction_use_regs(instruction))
            destination = instruction_def_reg(instruction)
            if destination is not None:
                live_regs.discard(destination)
            safepoint_live.update(live_regs)
    return frozenset(safepoint_live)


__all__ = [
    "X86_64SysVInstructionPositions",
    "X86_64SysVLiveInterval",
    "build_instruction_positions",
    "build_live_intervals",
]
