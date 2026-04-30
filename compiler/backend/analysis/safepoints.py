from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.cfg import iter_callable_instructions
from compiler.backend.analysis.liveness import (
    BackendCallableLiveness,
    analyze_callable_liveness,
    instruction_def_reg,
    instruction_use_regs,
)
from compiler.backend.ir import (
    BackendAllocObjectInst,
    BackendArrayAllocInst,
    BackendArraySliceInst,
    BackendCallInst,
    BackendCallableDecl,
    BackendEffects,
    BackendFunctionAnalysisDump,
    BackendInstruction,
    BackendInstId,
    BackendRegId,
    BackendRegister,
)
from compiler.backend.ir._ordering import inst_id_sort_key, reg_id_sort_key
from compiler.codegen.types import is_reference_type_ref


@dataclass(frozen=True)
class BackendCallableSafepoints:
    callable_decl: BackendCallableDecl
    safepoint_live_regs: dict[BackendInstId, tuple[BackendRegId, ...]]

    def live_regs_for_instruction(self, inst_id: BackendInstId) -> tuple[BackendRegId, ...]:
        return self.safepoint_live_regs.get(inst_id, ())

    def safepoint_instruction_ids(self) -> tuple[BackendInstId, ...]:
        return tuple(sorted(self.safepoint_live_regs, key=inst_id_sort_key))

    def all_safepoint_live_reg_sets(self) -> tuple[tuple[BackendRegId, ...], ...]:
        return tuple(self.safepoint_live_regs[inst_id] for inst_id in self.safepoint_instruction_ids())

    def gc_reference_regs_needing_slots(self) -> frozenset[BackendRegId]:
        return frozenset(reg_id for live_regs in self.safepoint_live_regs.values() for reg_id in live_regs)

    def to_analysis_dump(self) -> BackendFunctionAnalysisDump:
        return BackendFunctionAnalysisDump(
            predecessors={},
            successors={},
            live_in={},
            live_out={},
            safepoint_live_regs=dict(self.safepoint_live_regs),
            root_slot_by_reg={},
            stack_home_by_reg={},
        )


def analyze_callable_safepoints(
    callable_decl: BackendCallableDecl,
    *,
    liveness: BackendCallableLiveness | None = None,
) -> BackendCallableSafepoints:
    if callable_decl.is_extern or not callable_decl.blocks:
        return BackendCallableSafepoints(callable_decl=callable_decl, safepoint_live_regs={})

    resolved_liveness = analyze_callable_liveness(callable_decl) if liveness is None else liveness
    register_by_id = {register.reg_id: register for register in callable_decl.registers}
    safepoint_live_regs: dict[BackendInstId, tuple[BackendRegId, ...]] = {}
    for instruction in iter_callable_instructions(callable_decl):
        if not instruction_is_safepoint(instruction):
            continue
        safepoint_live_regs[instruction.inst_id] = safepoint_live_regs_for_instruction(
            instruction,
            liveness=resolved_liveness,
            register_by_id=register_by_id,
        )

    return BackendCallableSafepoints(
        callable_decl=callable_decl,
        safepoint_live_regs={
            inst_id: safepoint_live_regs[inst_id]
            for inst_id in sorted(safepoint_live_regs, key=inst_id_sort_key)
        },
    )


def safepoint_live_regs_for_instruction(
    instruction: BackendInstruction,
    *,
    liveness: BackendCallableLiveness,
    register_by_id: dict[BackendRegId, BackendRegister],
) -> tuple[BackendRegId, ...]:
    live_regs = set(liveness.instruction_live_after(instruction.inst_id))
    live_regs.update(instruction_use_regs(instruction))
    destination = instruction_def_reg(instruction)
    if destination is not None:
        live_regs.discard(destination)
    return tuple(
        reg_id
        for reg_id in sorted(live_regs, key=reg_id_sort_key)
        if register_is_gc_reference(register_by_id[reg_id])
    )


def instruction_is_safepoint(instruction: BackendInstruction) -> bool:
    effects = instruction_effects(instruction)
    if effects is None:
        return False
    return effects.may_gc or effects.needs_safepoint_hooks


def instruction_effects(instruction: BackendInstruction) -> BackendEffects | None:
    if isinstance(instruction, (BackendCallInst, BackendAllocObjectInst, BackendArrayAllocInst, BackendArraySliceInst)):
        return instruction.effects
    return None


def register_is_gc_reference(register: BackendRegister) -> bool:
    return is_reference_type_ref(register.type_ref)