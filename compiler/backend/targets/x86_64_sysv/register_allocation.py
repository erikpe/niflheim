from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.liveness import instruction_def_reg, instruction_use_regs, terminator_use_regs
from compiler.backend.analysis.safepoints import instruction_is_safepoint, register_is_gc_reference
from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlockId,
    BackendBoolConst,
    BackendCallInst,
    BackendCallableDecl,
    BackendCallableId,
    BackendCallableOperand,
    BackendConstInst,
    BackendConstant,
    BackendCopyInst,
    BackendIntConst,
    BackendInstId,
    BackendNullConst,
    BackendOperand,
    BackendRegOperand,
    BackendRegId,
    BackendReturnTerminator,
)
from compiler.backend.ir._ordering import reg_id_sort_key
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI, X86_64SysVAbi
from compiler.backend.targets.x86_64_sysv.locations import (
    X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS,
    X86_64_SYSV_ARGUMENT_ALLOCATABLE_XMMS,
    X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS,
    X86_64_SYSV_CALL_FREE_ALLOCATABLE_XMMS,
    X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS,
    X86_64_SYSV_RETURN_ALLOCATABLE_GPRS,
    X86_64_SYSV_RETURN_ALLOCATABLE_XMMS,
    X86_64SysVPhysicalRegister,
    X86_64SysVRegisterClass,
    X86_64SysVRegisterLocation,
    X86_64SysVStackLocation,
    register_class_for_type,
)
from compiler.backend.targets.x86_64_sysv.pipeline import X86_64SysVCallablePlan
from compiler.semantic.operations import BinaryOpKind


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


@dataclass(frozen=True, slots=True)
class X86_64SysVFixedRegisterConstraint:
    position: int
    register_name: str
    register_class: X86_64SysVRegisterClass
    kind: str
    reason: str
    reg_id: BackendRegId | None = None
    inst_id: BackendInstId | None = None
    block_id: BackendBlockId | None = None


@dataclass(frozen=True, slots=True)
class X86_64SysVAbiConstraintPlan:
    constraints: tuple[X86_64SysVFixedRegisterConstraint, ...]

    def constraints_at_position(self, position: int) -> tuple[X86_64SysVFixedRegisterConstraint, ...]:
        return tuple(constraint for constraint in self.constraints if constraint.position == position)

    def clobbers_at_position(self, position: int) -> tuple[X86_64SysVFixedRegisterConstraint, ...]:
        return tuple(
            constraint
            for constraint in self.constraints
            if constraint.position == position and constraint.kind == "clobber"
        )


@dataclass(frozen=True, slots=True)
class X86_64SysVCallerSavedSpill:
    reg_id: BackendRegId
    physical_register: X86_64SysVPhysicalRegister


@dataclass(frozen=True, slots=True)
class X86_64SysVCallerSavedSpillPoint:
    inst_id: BackendInstId
    spills: tuple[X86_64SysVCallerSavedSpill, ...]


@dataclass(frozen=True, slots=True)
class X86_64SysVCallArgumentReload:
    reg_id: BackendRegId
    physical_register: X86_64SysVPhysicalRegister


@dataclass(frozen=True, slots=True)
class X86_64SysVAllocationFragment:
    reg_id: BackendRegId
    start_position: int
    end_position: int
    physical_register: X86_64SysVPhysicalRegister | None
    stack_slot: X86_64SysVStackLocation | None
    kind: str


@dataclass(frozen=True, slots=True)
class X86_64SysVResolutionMove:
    reg_id: BackendRegId
    position: int
    kind: str
    physical_register: X86_64SysVPhysicalRegister
    stack_slot: X86_64SysVStackLocation
    inst_id: BackendInstId | None = None
    block_id: BackendBlockId | None = None


@dataclass(frozen=True, slots=True)
class X86_64SysVRematerializedValue:
    reg_id: BackendRegId
    kind: str
    constant: BackendConstant | None = None
    callable_id: BackendCallableId | None = None


@dataclass(frozen=True, slots=True)
class X86_64SysVRegisterAllocation:
    callable_decl: BackendCallableDecl
    location_by_reg: dict[BackendRegId, X86_64SysVRegisterLocation]
    used_callee_saved_registers: tuple[X86_64SysVPhysicalRegister, ...]
    spilled_reg_ids: tuple[BackendRegId, ...]
    abi_constraints: X86_64SysVAbiConstraintPlan
    caller_saved_spills_by_inst: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint]
    call_argument_reloads_by_inst: dict[BackendInstId, tuple[X86_64SysVCallArgumentReload, ...]]
    fragments_by_reg: dict[BackendRegId, tuple[X86_64SysVAllocationFragment, ...]]
    resolution_moves_by_inst: dict[BackendInstId, tuple[X86_64SysVResolutionMove, ...]]
    rematerialized_value_by_reg: dict[BackendRegId, X86_64SysVRematerializedValue]

    def location_for_reg(self, reg_id: BackendRegId) -> X86_64SysVRegisterLocation:
        return self.location_by_reg[reg_id]

    def caller_saved_spills_for_inst(self, inst_id: BackendInstId) -> tuple[X86_64SysVCallerSavedSpill, ...]:
        spill_point = self.caller_saved_spills_by_inst.get(inst_id)
        return () if spill_point is None else spill_point.spills

    def call_argument_reloads_for_inst(self, inst_id: BackendInstId) -> tuple[X86_64SysVCallArgumentReload, ...]:
        return self.call_argument_reloads_by_inst.get(inst_id, ())

    def fragments_for_reg(self, reg_id: BackendRegId) -> tuple[X86_64SysVAllocationFragment, ...]:
        return self.fragments_by_reg.get(reg_id, ())

    def resolution_moves_for_inst(self, inst_id: BackendInstId) -> tuple[X86_64SysVResolutionMove, ...]:
        return self.resolution_moves_by_inst.get(inst_id, ())

    def rematerialized_value_for_reg(self, reg_id: BackendRegId) -> X86_64SysVRematerializedValue | None:
        return self.rematerialized_value_by_reg.get(reg_id)


@dataclass(frozen=True, slots=True)
class _ActiveInterval:
    interval: X86_64SysVLiveInterval
    physical_register: X86_64SysVPhysicalRegister


@dataclass(frozen=True, slots=True)
class _CopyPreference:
    source_reg_id: BackendRegId
    dest_reg_id: BackendRegId
    position: int


@dataclass(frozen=True, slots=True)
class _CoalescingPlan:
    group_members_by_reg: dict[BackendRegId, tuple[BackendRegId, ...]]

    def group_members(self, reg_id: BackendRegId) -> tuple[BackendRegId, ...]:
        return self.group_members_by_reg.get(reg_id, (reg_id,))


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


def build_abi_constraints(
    callable_plan: X86_64SysVCallablePlan,
    *,
    abi: X86_64SysVAbi = X86_64_SYSV_ABI,
) -> X86_64SysVAbiConstraintPlan:
    callable_decl = callable_plan.callable_decl
    if callable_decl.is_extern or not callable_decl.blocks:
        return X86_64SysVAbiConstraintPlan(constraints=())

    positions = build_instruction_positions(callable_plan)
    constraints: list[X86_64SysVFixedRegisterConstraint] = []
    register_by_id = {register.reg_id: register for register in callable_decl.registers}

    incoming_regs = callable_decl.param_regs
    incoming_types = callable_decl.signature.param_types
    includes_receiver = callable_decl.receiver_reg is not None
    if includes_receiver:
        incoming_regs = (callable_decl.receiver_reg, *incoming_regs)
        incoming_types = (register_by_id[callable_decl.receiver_reg].type_ref, *incoming_types)

    for reg_id, arg_location in zip(
        incoming_regs,
        abi.plan_argument_locations(incoming_types, includes_receiver=False),
        strict=True,
    ):
        if arg_location.register_name is None:
            continue
        constraints.append(
            _fixed_register_constraint(
                position=0,
                register_name=arg_location.register_name,
                kind="definition",
                reason="incoming_argument",
                reg_id=reg_id,
            )
        )

    block_by_id = {block.block_id: block for block in callable_decl.blocks}
    for block_id in callable_plan.ordered_block_ids:
        block = block_by_id[block_id]
        for instruction in block.instructions:
            position = positions.instruction_position(instruction.inst_id)
            if isinstance(instruction, BackendCallInst):
                constraints.extend(
                    _call_fixed_register_constraints(
                        instruction,
                        position=position,
                        abi=abi,
                    )
                )
                continue
            if isinstance(instruction, BackendBinaryInst):
                constraints.extend(_binary_fixed_register_constraints(instruction, position=position))

        terminator_position = positions.terminator_position(block_id)
        terminator = block.terminator
        if isinstance(terminator, BackendReturnTerminator) and terminator.value is not None:
            return_register = abi.return_register_for_type(callable_decl.signature.return_type)
            if return_register is not None:
                constraints.append(
                    _fixed_register_constraint(
                        position=terminator_position,
                        register_name=return_register,
                        kind="use",
                        reason="return_value",
                        reg_id=_operand_reg_id(terminator.value),
                        block_id=block_id,
                    )
                )

    return X86_64SysVAbiConstraintPlan(constraints=tuple(constraints))


def allocate_x86_64_sysv_registers(
    callable_plan: X86_64SysVCallablePlan,
    *,
    intervals: tuple[X86_64SysVLiveInterval, ...] | None = None,
    allocatable_gprs: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS,
    call_free_allocatable_gprs: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS,
    call_free_allocatable_xmms: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_CALL_FREE_ALLOCATABLE_XMMS,
    call_argument_allocatable_gprs: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS,
    call_argument_allocatable_xmms: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_ARGUMENT_ALLOCATABLE_XMMS,
    return_allocatable_gprs: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_RETURN_ALLOCATABLE_GPRS,
    return_allocatable_xmms: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_RETURN_ALLOCATABLE_XMMS,
) -> X86_64SysVRegisterAllocation:
    resolved_intervals = build_live_intervals(callable_plan) if intervals is None else intervals
    abi_constraints = build_abi_constraints(callable_plan)
    interval_by_reg = {interval.reg_id: interval for interval in resolved_intervals}
    call_crossing_count_by_reg = _call_crossing_count_by_reg_id(callable_plan)
    safepoint_crossing_count_by_reg = _safepoint_crossing_count_by_reg_id(callable_plan)
    non_call_safepoint_crossing_count_by_reg = _non_call_safepoint_crossing_count_by_reg_id(callable_plan)
    call_argument_preferences_by_reg = _call_argument_preferences_by_reg_id(
        callable_plan,
        abi=X86_64_SYSV_ABI,
        argument_gprs=call_argument_allocatable_gprs,
        argument_xmms=call_argument_allocatable_xmms,
    )
    return_preferences_by_reg = (
        {}
        if intervals is not None
        else _return_preferences_by_reg_id(
            callable_plan,
            abi=X86_64_SYSV_ABI,
            return_gprs=return_allocatable_gprs,
            return_xmms=return_allocatable_xmms,
        )
    )
    copy_preference_by_dest = _copy_preferences_by_dest(
        callable_plan,
        positions=build_instruction_positions(callable_plan),
        interval_by_reg=interval_by_reg,
    )
    coalescing_plan = _build_copy_coalescing_plan(
        callable_plan,
        positions=build_instruction_positions(callable_plan),
        interval_by_reg=interval_by_reg,
        abi_constraints=abi_constraints,
    )
    rematerializable_value_by_reg = _rematerializable_values_by_reg(
        callable_plan,
        interval_by_reg=interval_by_reg,
    )
    rematerializable_reg_ids = frozenset(rematerializable_value_by_reg)
    physical_register_by_reg: dict[BackendRegId, X86_64SysVPhysicalRegister] = {}
    spilled_reg_ids: set[BackendRegId] = set()
    active: list[_ActiveInterval] = []

    for interval in resolved_intervals:
        active = _expire_inactive_intervals(active, current_start_position=interval.start_position)
        if interval.register_class == "gpr":
            interval_register_pool = _register_pool_for_interval(
                interval,
                abi_constraints=abi_constraints,
                callee_saved_gprs=allocatable_gprs,
                call_free_gprs=call_free_allocatable_gprs,
                call_crossing_count=call_crossing_count_by_reg.get(interval.reg_id, 0),
                safepoint_crossing_count=safepoint_crossing_count_by_reg.get(interval.reg_id, 0),
            )
        elif interval.register_class == "xmm":
            interval_register_pool = _xmm_register_pool_for_interval(
                interval,
                abi_constraints=abi_constraints,
                call_free_xmms=call_free_allocatable_xmms,
                non_call_safepoint_crossing_count=non_call_safepoint_crossing_count_by_reg.get(interval.reg_id, 0),
            )
        else:
            spilled_reg_ids.add(interval.reg_id)
            continue

        preferred_return_register, active_to_release = _preferred_return_register_for_interval(
            interval,
            active=active,
            preferences=_merged_physical_preferences(
                coalescing_plan.group_members(interval.reg_id),
                preferences_by_reg=return_preferences_by_reg,
            ),
            abi_constraints=abi_constraints,
            coalesced_reg_ids=coalescing_plan.group_members(interval.reg_id),
        )
        if preferred_return_register is not None:
            if active_to_release is not None:
                active = [
                    active_interval
                    for active_interval in active
                    if active_interval.interval.reg_id != active_to_release.interval.reg_id
                ]
            physical_register_by_reg[interval.reg_id] = preferred_return_register
            active.append(_ActiveInterval(interval=interval, physical_register=preferred_return_register))
            active = _sorted_active_intervals(active)
            continue

        if not interval_register_pool:
            spilled_reg_ids.add(interval.reg_id)
            continue

        preferred_arg_register, active_to_release = _preferred_call_argument_register_for_interval(
            interval,
            active=active,
            preferences=_merged_physical_preferences(
                coalescing_plan.group_members(interval.reg_id),
                preferences_by_reg=call_argument_preferences_by_reg,
            ),
            coalesced_reg_ids=coalescing_plan.group_members(interval.reg_id),
        )
        if preferred_arg_register is not None:
            if active_to_release is not None:
                active = [
                    active_interval
                    for active_interval in active
                    if active_interval.interval.reg_id != active_to_release.interval.reg_id
                ]
            physical_register_by_reg[interval.reg_id] = preferred_arg_register
            active.append(_ActiveInterval(interval=interval, physical_register=preferred_arg_register))
            active = _sorted_active_intervals(active)
            continue

        preferred_register, active_to_release = _preferred_register_for_interval(
            interval,
            active=active,
            copy_preferences=copy_preference_by_dest.get(interval.reg_id, ()),
            interval_by_reg=interval_by_reg,
            physical_register_by_reg=physical_register_by_reg,
            spilled_reg_ids=spilled_reg_ids,
            allowed_registers=interval_register_pool,
            coalescing_plan=coalescing_plan,
        )
        if preferred_register is not None:
            if active_to_release is not None:
                active = [
                    active_interval
                    for active_interval in active
                    if active_interval.interval.reg_id != active_to_release.interval.reg_id
                ]
            physical_register_by_reg[interval.reg_id] = preferred_register
            active.append(_ActiveInterval(interval=interval, physical_register=preferred_register))
            active = _sorted_active_intervals(active)
            continue

        used_register_names = {active_interval.physical_register.name for active_interval in active}
        available_register = next(
            (
                physical_register
                for physical_register in interval_register_pool
                if physical_register.name not in used_register_names
            ),
            None,
        )
        if available_register is not None:
            physical_register_by_reg[interval.reg_id] = available_register
            active.append(_ActiveInterval(interval=interval, physical_register=available_register))
            active = _sorted_active_intervals(active)
            continue

        spill_candidate = _spill_candidate(
            active,
            allowed_registers=interval_register_pool,
            rematerializable_reg_ids=rematerializable_reg_ids,
        )
        if spill_candidate is not None and spill_candidate.interval.end_position > interval.end_position:
            spilled_reg_ids.add(spill_candidate.interval.reg_id)
            physical_register_by_reg.pop(spill_candidate.interval.reg_id, None)
            physical_register_by_reg[interval.reg_id] = spill_candidate.physical_register
            active = [
                active_interval
                for active_interval in active
                if active_interval.interval.reg_id != spill_candidate.interval.reg_id
            ]
            active.append(_ActiveInterval(interval=interval, physical_register=spill_candidate.physical_register))
            active = _sorted_active_intervals(active)
            continue

        spilled_reg_ids.add(interval.reg_id)

    location_by_reg: dict[BackendRegId, X86_64SysVRegisterLocation] = {}
    for register in sorted(callable_plan.callable_decl.registers, key=lambda register: reg_id_sort_key(register.reg_id)):
        physical_register = physical_register_by_reg.get(register.reg_id)
        stack_location = None if physical_register is not None else _stack_location_for_reg(callable_plan, register.reg_id)
        if register.reg_id not in interval_by_reg:
            spilled_reg_ids.add(register.reg_id)
        location_by_reg[register.reg_id] = X86_64SysVRegisterLocation(
            reg_id=register.reg_id,
            physical_register=physical_register,
            stack_slot=stack_location,
        )

    used_callee_saved_registers = tuple(
        physical_register
        for physical_register in allocatable_gprs
        if physical_register.preserved_by_callee
        and any(assigned.name == physical_register.name for assigned in physical_register_by_reg.values())
    )

    caller_saved_spills_by_inst = _caller_saved_spills_by_inst(
        callable_plan,
        physical_register_by_reg=physical_register_by_reg,
        caller_saved_gprs=call_free_allocatable_gprs,
    )
    call_argument_reloads_by_inst = _call_argument_reloads_by_inst(
        callable_plan,
        physical_register_by_reg=physical_register_by_reg,
        argument_gprs=call_argument_allocatable_gprs,
        argument_xmms=call_argument_allocatable_xmms,
        abi=X86_64_SYSV_ABI,
    )
    fragments_by_reg = _allocation_fragments_by_reg(
        callable_plan,
        intervals=resolved_intervals,
        physical_register_by_reg=physical_register_by_reg,
        caller_saved_spills_by_inst=caller_saved_spills_by_inst,
        abi_constraints=abi_constraints,
    )
    resolution_moves_by_inst = _resolution_moves_by_inst(
        callable_plan,
        caller_saved_spills_by_inst=caller_saved_spills_by_inst,
    )
    rematerialized_value_by_reg = {
        reg_id: value
        for reg_id, value in rematerializable_value_by_reg.items()
        if reg_id in spilled_reg_ids and reg_id not in physical_register_by_reg
    }

    return X86_64SysVRegisterAllocation(
        callable_decl=callable_plan.callable_decl,
        location_by_reg=location_by_reg,
        used_callee_saved_registers=used_callee_saved_registers,
        spilled_reg_ids=tuple(sorted(spilled_reg_ids, key=reg_id_sort_key)),
        abi_constraints=abi_constraints,
        caller_saved_spills_by_inst=caller_saved_spills_by_inst,
        call_argument_reloads_by_inst=call_argument_reloads_by_inst,
        fragments_by_reg=fragments_by_reg,
        resolution_moves_by_inst=resolution_moves_by_inst,
        rematerialized_value_by_reg=rematerialized_value_by_reg,
    )


def _call_fixed_register_constraints(
    instruction: BackendCallInst,
    *,
    position: int,
    abi: X86_64SysVAbi,
) -> tuple[X86_64SysVFixedRegisterConstraint, ...]:
    constraints: list[X86_64SysVFixedRegisterConstraint] = []
    arg_locations = abi.plan_argument_locations(
        instruction.signature.param_types,
        includes_receiver=_call_includes_receiver(instruction),
    )
    for operand, arg_location in zip(instruction.args, arg_locations, strict=True):
        if arg_location.register_name is None:
            continue
        constraints.append(
            _fixed_register_constraint(
                position=position,
                register_name=arg_location.register_name,
                kind="use",
                reason="call_argument",
                reg_id=_operand_reg_id(operand),
                inst_id=instruction.inst_id,
            )
        )

    if instruction.dest is not None and instruction.signature.return_type is not None:
        constraints.append(
            _fixed_register_constraint(
                position=position,
                register_name=abi.return_register_for_type(instruction.signature.return_type),
                kind="definition",
                reason="call_return",
                reg_id=instruction.dest,
                inst_id=instruction.inst_id,
            )
        )

    for register_name in abi.all_caller_saved_registers:
        constraints.append(
            _fixed_register_constraint(
                position=position,
                register_name=register_name,
                kind="clobber",
                reason="call_clobber",
                inst_id=instruction.inst_id,
            )
        )

    for register_name in ("rax", "r10", "r11", "xmm15"):
        constraints.append(
            _fixed_register_constraint(
                position=position,
                register_name=register_name,
                kind="temporary",
                reason="call_lowering_scratch",
                inst_id=instruction.inst_id,
            )
        )

    return tuple(constraints)


def _register_pool_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    abi_constraints: X86_64SysVAbiConstraintPlan,
    callee_saved_gprs: tuple[X86_64SysVPhysicalRegister, ...],
    call_free_gprs: tuple[X86_64SysVPhysicalRegister, ...],
    call_crossing_count: int,
    safepoint_crossing_count: int,
) -> tuple[X86_64SysVPhysicalRegister, ...]:
    if _interval_can_use_caller_saved_registers(
        interval,
        abi_constraints=abi_constraints,
        call_crossing_count=call_crossing_count,
        safepoint_crossing_count=safepoint_crossing_count,
    ):
        if interval.crosses_call:
            return (*callee_saved_gprs, *call_free_gprs)
        return (*call_free_gprs, *callee_saved_gprs)
    return callee_saved_gprs


def _interval_can_use_caller_saved_registers(
    interval: X86_64SysVLiveInterval,
    *,
    abi_constraints: X86_64SysVAbiConstraintPlan,
    call_crossing_count: int,
    safepoint_crossing_count: int,
) -> bool:
    if interval.is_gc_reference:
        return False
    if interval.crosses_call:
        return (
            call_crossing_count == 1
            and safepoint_crossing_count <= call_crossing_count
            and not _has_unsaved_caller_saved_conflict(
                interval,
                abi_constraints=abi_constraints,
            )
        )
    if interval.live_at_safepoint:
        return False
    return not any(
        _constraint_overlaps_interval(constraint, interval)
        for constraint in abi_constraints.constraints
        if constraint.kind in {"clobber", "temporary"} or constraint.reason in {"call_argument", "call_return"}
    )


def _xmm_register_pool_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    abi_constraints: X86_64SysVAbiConstraintPlan,
    call_free_xmms: tuple[X86_64SysVPhysicalRegister, ...],
    non_call_safepoint_crossing_count: int,
) -> tuple[X86_64SysVPhysicalRegister, ...]:
    if interval.crosses_call or non_call_safepoint_crossing_count > 0:
        return ()
    call_free_xmm_names = {register.name for register in call_free_xmms}
    if any(
        _constraint_overlaps_interval(constraint, interval)
        for constraint in abi_constraints.constraints
        if constraint.register_class == "xmm"
        and constraint.register_name in call_free_xmm_names
        and (
            constraint.kind in {"clobber", "temporary"}
            and not (
                constraint.position == interval.end_position
                and constraint.reason in {"call_clobber", "call_lowering_scratch"}
            )
            or constraint.reason in {"call_return", "return_value"}
        )
    ):
        return ()
    return call_free_xmms


def _has_unsaved_caller_saved_conflict(
    interval: X86_64SysVLiveInterval,
    *,
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> bool:
    return any(
        _constraint_overlaps_interval(constraint, interval)
        for constraint in abi_constraints.constraints
        if constraint.kind == "temporary" and constraint.reason != "call_lowering_scratch"
    )


def _constraint_overlaps_interval(
    constraint: X86_64SysVFixedRegisterConstraint,
    interval: X86_64SysVLiveInterval,
) -> bool:
    return interval.start_position <= constraint.position <= interval.end_position


def _binary_fixed_register_constraints(
    instruction: BackendBinaryInst,
    *,
    position: int,
) -> tuple[X86_64SysVFixedRegisterConstraint, ...]:
    if instruction.op.kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
        return (
            _fixed_register_constraint(
                position=position,
                register_name="rcx",
                kind="temporary",
                reason="shift_count",
                reg_id=_operand_reg_id(instruction.right),
                inst_id=instruction.inst_id,
            ),
        )
    if instruction.op.kind in {BinaryOpKind.DIVIDE, BinaryOpKind.REMAINDER}:
        return (
            _fixed_register_constraint(
                position=position,
                register_name="rax",
                kind="temporary",
                reason="integer_division",
                reg_id=_operand_reg_id(instruction.left),
                inst_id=instruction.inst_id,
            ),
            _fixed_register_constraint(
                position=position,
                register_name="rdx",
                kind="temporary",
                reason="integer_division",
                inst_id=instruction.inst_id,
            ),
        )
    return ()


def _fixed_register_constraint(
    *,
    position: int,
    register_name: str | None,
    kind: str,
    reason: str,
    reg_id: BackendRegId | None = None,
    inst_id: BackendInstId | None = None,
    block_id: BackendBlockId | None = None,
) -> X86_64SysVFixedRegisterConstraint:
    if register_name is None:
        raise ValueError("x86_64 SysV fixed-register constraint requires a register name")
    return X86_64SysVFixedRegisterConstraint(
        position=position,
        register_name=register_name,
        register_class=_register_class_for_physical_name(register_name),
        kind=kind,
        reason=reason,
        reg_id=reg_id,
        inst_id=inst_id,
        block_id=block_id,
    )


def _register_class_for_physical_name(register_name: str) -> X86_64SysVRegisterClass:
    return "xmm" if register_name.startswith("xmm") else "gpr"


def _operand_reg_id(operand: BackendOperand) -> BackendRegId | None:
    return operand.reg_id if isinstance(operand, BackendRegOperand) else None


def _call_includes_receiver(instruction: BackendCallInst) -> bool:
    return len(instruction.args) == len(instruction.signature.param_types) + 1


def _call_argument_preferences_by_reg_id(
    callable_plan: X86_64SysVCallablePlan,
    *,
    abi: X86_64SysVAbi,
    argument_gprs: tuple[X86_64SysVPhysicalRegister, ...],
    argument_xmms: tuple[X86_64SysVPhysicalRegister, ...],
) -> dict[BackendRegId, tuple[X86_64SysVPhysicalRegister, ...]]:
    argument_register_by_name = {register.name: register for register in argument_gprs}
    argument_register_by_name.update({register.name: register for register in argument_xmms})
    register_by_id = {register.reg_id: register for register in callable_plan.callable_decl.registers}
    non_call_safepoint_count_by_reg = _non_call_safepoint_crossing_count_by_reg_id(callable_plan)
    preferences_by_reg: dict[BackendRegId, list[X86_64SysVPhysicalRegister]] = {}

    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if instruction.dest is not None:
                live_after.discard(instruction.dest)
            arg_locations = abi.plan_argument_locations(
                instruction.signature.param_types,
                includes_receiver=_call_includes_receiver(instruction),
            )
            for operand, arg_location in zip(instruction.args, arg_locations, strict=True):
                if arg_location.kind not in {"int_reg", "float_reg"} or arg_location.register_name is None:
                    continue
                if not isinstance(operand, BackendRegOperand):
                    continue
                if operand.reg_id in live_after:
                    continue
                if non_call_safepoint_count_by_reg.get(operand.reg_id, 0) > 0:
                    continue
                register = register_by_id.get(operand.reg_id)
                if register is None or register_is_gc_reference(register):
                    continue
                physical_register = argument_register_by_name.get(arg_location.register_name)
                if physical_register is None:
                    continue
                preferences_by_reg.setdefault(operand.reg_id, []).append(physical_register)

    return {
        reg_id: tuple(dict.fromkeys(preferences))
        for reg_id, preferences in preferences_by_reg.items()
    }


def _return_preferences_by_reg_id(
    callable_plan: X86_64SysVCallablePlan,
    *,
    abi: X86_64SysVAbi,
    return_gprs: tuple[X86_64SysVPhysicalRegister, ...],
    return_xmms: tuple[X86_64SysVPhysicalRegister, ...],
) -> dict[BackendRegId, tuple[X86_64SysVPhysicalRegister, ...]]:
    return_register_by_name = {register.name: register for register in (*return_gprs, *return_xmms)}
    preferences_by_reg: dict[BackendRegId, list[X86_64SysVPhysicalRegister]] = {}

    for block in callable_plan.callable_decl.blocks:
        terminator = block.terminator
        if not isinstance(terminator, BackendReturnTerminator) or not isinstance(terminator.value, BackendRegOperand):
            continue
        return_register_name = abi.return_register_for_type(callable_plan.callable_decl.signature.return_type)
        if return_register_name is None:
            continue
        physical_register = return_register_by_name.get(return_register_name)
        if physical_register is None:
            continue
        preferences_by_reg.setdefault(terminator.value.reg_id, []).append(physical_register)

    return {
        reg_id: tuple(dict.fromkeys(preferences))
        for reg_id, preferences in preferences_by_reg.items()
    }


def _preferred_return_register_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    active: list[_ActiveInterval],
    preferences: tuple[X86_64SysVPhysicalRegister, ...],
    abi_constraints: X86_64SysVAbiConstraintPlan,
    coalesced_reg_ids: tuple[BackendRegId, ...],
) -> tuple[X86_64SysVPhysicalRegister | None, _ActiveInterval | None]:
    if interval.register_class not in {"gpr", "xmm"} or interval.crosses_call or interval.is_gc_reference or interval.live_at_safepoint:
        return None, None
    if interval.end_position - interval.start_position > 1:
        return None, None
    if not preferences:
        return None, None
    used_register_names = {active_interval.physical_register.name for active_interval in active}
    for physical_register in preferences:
        if not _return_register_is_safe_for_interval(
            interval,
            physical_register=physical_register,
            abi_constraints=abi_constraints,
        ):
            continue
        if physical_register.name not in used_register_names:
            return physical_register, None
        active_to_release = _active_coalesced_interval_using_register(
            active,
            physical_register=physical_register,
            coalesced_reg_ids=coalesced_reg_ids,
        )
        if active_to_release is not None:
            return physical_register, active_to_release
    return None, None


def _return_register_is_safe_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    physical_register: X86_64SysVPhysicalRegister,
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> bool:
    for constraint in abi_constraints.constraints:
        if constraint.register_name != physical_register.name or not _constraint_overlaps_interval(constraint, interval):
            continue
        if constraint.reason == "return_value":
            continue
        if constraint.position == interval.start_position and constraint.reason in {
            "call_argument",
            "call_return",
            "call_clobber",
            "call_lowering_scratch",
        }:
            continue
        if constraint.kind in {"clobber", "temporary"} or constraint.reason in {"call_argument", "call_return"}:
            return False
    return True


def _preferred_call_argument_register_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    active: list[_ActiveInterval],
    preferences: tuple[X86_64SysVPhysicalRegister, ...],
    coalesced_reg_ids: tuple[BackendRegId, ...],
) -> tuple[X86_64SysVPhysicalRegister | None, _ActiveInterval | None]:
    if interval.register_class not in {"gpr", "xmm"} or interval.crosses_call or interval.is_gc_reference:
        return None, None
    if not preferences:
        return None, None
    used_register_names = {active_interval.physical_register.name for active_interval in active}
    for physical_register in preferences:
        if physical_register.register_class != interval.register_class:
            continue
        if physical_register.name not in used_register_names:
            return physical_register, None
        active_to_release = _active_coalesced_interval_using_register(
            active,
            physical_register=physical_register,
            coalesced_reg_ids=coalesced_reg_ids,
        )
        if active_to_release is not None:
            return physical_register, active_to_release
    return None, None


def _active_coalesced_interval_using_register(
    active: list[_ActiveInterval],
    *,
    physical_register: X86_64SysVPhysicalRegister,
    coalesced_reg_ids: tuple[BackendRegId, ...],
) -> _ActiveInterval | None:
    coalesced_reg_id_set = set(coalesced_reg_ids)
    return next(
        (
            active_interval
            for active_interval in active
            if active_interval.interval.reg_id in coalesced_reg_id_set
            and active_interval.physical_register.name == physical_register.name
        ),
        None,
    )


def _copy_preferences_by_dest(
    callable_plan: X86_64SysVCallablePlan,
    *,
    positions: X86_64SysVInstructionPositions,
    interval_by_reg: dict[BackendRegId, X86_64SysVLiveInterval],
) -> dict[BackendRegId, tuple[_CopyPreference, ...]]:
    preference_by_dest: dict[BackendRegId, list[_CopyPreference]] = {}
    register_by_id = {register.reg_id: register for register in callable_plan.callable_decl.registers}

    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCopyInst) or not isinstance(instruction.source, BackendRegOperand):
                continue
            source_reg_id = instruction.source.reg_id
            dest_reg_id = instruction.dest
            source_interval = interval_by_reg.get(source_reg_id)
            dest_interval = interval_by_reg.get(dest_reg_id)
            if source_interval is None or dest_interval is None:
                continue
            if source_interval.register_class != "gpr" or dest_interval.register_class != "gpr":
                continue
            if source_interval.register_class != dest_interval.register_class:
                continue
            if source_reg_id not in register_by_id or dest_reg_id not in register_by_id:
                continue

            position = positions.instruction_position(instruction.inst_id)
            if source_reg_id in callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id):
                continue
            if not _intervals_can_coalesce_at_copy(source_interval, dest_interval, copy_position=position):
                continue

            preference_by_dest.setdefault(dest_reg_id, []).append(
                _CopyPreference(
                    source_reg_id=source_reg_id,
                    dest_reg_id=dest_reg_id,
                    position=position,
                )
            )

    return {
        dest_reg_id: tuple(
            sorted(
                preferences,
                key=lambda preference: (
                    preference.position,
                    reg_id_sort_key(preference.source_reg_id),
                    reg_id_sort_key(preference.dest_reg_id),
                ),
            )
        )
        for dest_reg_id, preferences in preference_by_dest.items()
    }


def _intervals_can_coalesce_at_copy(
    source_interval: X86_64SysVLiveInterval,
    dest_interval: X86_64SysVLiveInterval,
    *,
    copy_position: int,
) -> bool:
    return (
        source_interval.end_position == copy_position
        and dest_interval.start_position == copy_position
        and source_interval.start_position <= source_interval.end_position
        and dest_interval.start_position <= dest_interval.end_position
    )


def _build_copy_coalescing_plan(
    callable_plan: X86_64SysVCallablePlan,
    *,
    positions: X86_64SysVInstructionPositions,
    interval_by_reg: dict[BackendRegId, X86_64SysVLiveInterval],
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> _CoalescingPlan:
    register_by_id = {register.reg_id: register for register in callable_plan.callable_decl.registers}
    parent: dict[BackendRegId, BackendRegId] = {reg_id: reg_id for reg_id in interval_by_reg}

    def find(reg_id: BackendRegId) -> BackendRegId:
        root = parent[reg_id]
        if root != reg_id:
            root = find(root)
            parent[reg_id] = root
        return root

    def group_members(root: BackendRegId) -> tuple[BackendRegId, ...]:
        resolved_root = find(root)
        return tuple(
            sorted(
                (reg_id for reg_id in parent if find(reg_id) == resolved_root),
                key=reg_id_sort_key,
            )
        )

    def union(left: BackendRegId, right: BackendRegId) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if reg_id_sort_key(right_root) < reg_id_sort_key(left_root):
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root

    copy_edges: list[tuple[int, BackendRegId, BackendRegId]] = []
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCopyInst) or not isinstance(instruction.source, BackendRegOperand):
                continue
            copy_edges.append(
                (
                    positions.instruction_position(instruction.inst_id),
                    instruction.source.reg_id,
                    instruction.dest,
                )
            )

    for copy_position, source_reg_id, dest_reg_id in sorted(
        copy_edges,
        key=lambda edge: (edge[0], reg_id_sort_key(edge[1]), reg_id_sort_key(edge[2])),
    ):
        if source_reg_id not in parent or dest_reg_id not in parent:
            continue
        source_group = group_members(source_reg_id)
        dest_group = group_members(dest_reg_id)
        if source_group == dest_group:
            continue
        merged_group = tuple(sorted((*source_group, *dest_group), key=reg_id_sort_key))
        if not _copy_groups_can_coalesce(
            merged_group,
            copied_reg_ids=(source_reg_id, dest_reg_id),
            copy_position=copy_position,
            callable_plan=callable_plan,
            interval_by_reg=interval_by_reg,
            register_by_id=register_by_id,
            abi_constraints=abi_constraints,
        ):
            continue
        union(source_reg_id, dest_reg_id)

    groups_by_root: dict[BackendRegId, list[BackendRegId]] = {}
    for reg_id in sorted(parent, key=reg_id_sort_key):
        groups_by_root.setdefault(find(reg_id), []).append(reg_id)

    return _CoalescingPlan(
        group_members_by_reg={
            reg_id: tuple(members)
            for members in groups_by_root.values()
            if len(members) > 1
            for reg_id in members
        }
    )


def _copy_groups_can_coalesce(
    merged_group: tuple[BackendRegId, ...],
    *,
    copied_reg_ids: tuple[BackendRegId, BackendRegId],
    copy_position: int,
    callable_plan: X86_64SysVCallablePlan,
    interval_by_reg: dict[BackendRegId, X86_64SysVLiveInterval],
    register_by_id: dict[BackendRegId, object],
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> bool:
    source_reg_id, dest_reg_id = copied_reg_ids
    source_interval = interval_by_reg[source_reg_id]
    dest_interval = interval_by_reg[dest_reg_id]
    if source_interval.register_class != dest_interval.register_class:
        return False
    if any(register_is_gc_reference(register_by_id[reg_id]) for reg_id in merged_group):
        return False
    if not _fixed_register_constraints_are_compatible(merged_group, abi_constraints=abi_constraints):
        return False

    for index, left_reg_id in enumerate(merged_group):
        left_interval = interval_by_reg[left_reg_id]
        for right_reg_id in merged_group[index + 1 :]:
            right_interval = interval_by_reg[right_reg_id]
            if left_interval.register_class != right_interval.register_class:
                return False
            if _intervals_strictly_interfere(left_interval, right_interval):
                return False

    return _copy_liveness_allows_coalescing(
        callable_plan,
        source_reg_id=source_reg_id,
        dest_reg_id=dest_reg_id,
        copy_position=copy_position,
    )


def _intervals_strictly_interfere(left: X86_64SysVLiveInterval, right: X86_64SysVLiveInterval) -> bool:
    return max(left.start_position, right.start_position) < min(left.end_position, right.end_position)


def _copy_liveness_allows_coalescing(
    callable_plan: X86_64SysVCallablePlan,
    *,
    source_reg_id: BackendRegId,
    dest_reg_id: BackendRegId,
    copy_position: int,
) -> bool:
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCopyInst) or not isinstance(instruction.source, BackendRegOperand):
                continue
            if instruction.source.reg_id != source_reg_id or instruction.dest != dest_reg_id:
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if source_reg_id in live_after and dest_reg_id in live_after:
                return False
            return True
    return copy_position >= 0


def _fixed_register_constraints_are_compatible(
    reg_ids: tuple[BackendRegId, ...],
    *,
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> bool:
    reg_id_set = set(reg_ids)
    constrained_register_names = {
        constraint.register_name
        for constraint in abi_constraints.constraints
        if constraint.reg_id in reg_id_set
        and constraint.kind in {"definition", "use"}
        and constraint.reason in {"incoming_argument", "call_argument", "call_return", "return_value"}
    }
    return len(constrained_register_names) <= 1


def _merged_physical_preferences(
    reg_ids: tuple[BackendRegId, ...],
    *,
    preferences_by_reg: dict[BackendRegId, tuple[X86_64SysVPhysicalRegister, ...]],
) -> tuple[X86_64SysVPhysicalRegister, ...]:
    preferences: list[X86_64SysVPhysicalRegister] = []
    for reg_id in sorted(reg_ids, key=reg_id_sort_key):
        preferences.extend(preferences_by_reg.get(reg_id, ()))
    return tuple(dict.fromkeys(preferences))


def _preferred_register_for_interval(
    interval: X86_64SysVLiveInterval,
    *,
    active: list[_ActiveInterval],
    copy_preferences: tuple[_CopyPreference, ...],
    interval_by_reg: dict[BackendRegId, X86_64SysVLiveInterval],
    physical_register_by_reg: dict[BackendRegId, X86_64SysVPhysicalRegister],
    spilled_reg_ids: set[BackendRegId],
    allowed_registers: tuple[X86_64SysVPhysicalRegister, ...],
    coalescing_plan: _CoalescingPlan,
) -> tuple[X86_64SysVPhysicalRegister | None, _ActiveInterval | None]:
    active_by_reg = {active_interval.interval.reg_id: active_interval for active_interval in active}
    used_register_names = {active_interval.physical_register.name for active_interval in active}
    allowed_register_names = {register.name for register in allowed_registers}

    for group_reg_id in coalescing_plan.group_members(interval.reg_id):
        if group_reg_id == interval.reg_id or group_reg_id in spilled_reg_ids:
            continue
        preferred_register = physical_register_by_reg.get(group_reg_id)
        if preferred_register is None or preferred_register.name not in allowed_register_names:
            continue
        active_group_member = active_by_reg.get(group_reg_id)
        if active_group_member is not None:
            if active_group_member.physical_register.name != preferred_register.name:
                continue
            return preferred_register, active_group_member
        if preferred_register.name not in used_register_names:
            return preferred_register, None

    for preference in copy_preferences:
        source_interval = interval_by_reg.get(preference.source_reg_id)
        if source_interval is None or preference.source_reg_id in spilled_reg_ids:
            continue
        if not _intervals_can_coalesce_at_copy(source_interval, interval, copy_position=preference.position):
            continue

        preferred_register = physical_register_by_reg.get(preference.source_reg_id)
        if preferred_register is None:
            continue
        if preferred_register.name not in allowed_register_names:
            continue

        active_source = active_by_reg.get(preference.source_reg_id)
        if active_source is not None:
            if active_source.physical_register.name != preferred_register.name:
                continue
            return preferred_register, active_source

        if preferred_register.name not in used_register_names:
            return preferred_register, None

    return None, None


def _call_crossing_reg_ids(callable_plan: X86_64SysVCallablePlan) -> frozenset[BackendRegId]:
    return frozenset(_call_crossing_count_by_reg_id(callable_plan))


def _call_crossing_count_by_reg_id(callable_plan: X86_64SysVCallablePlan) -> dict[BackendRegId, int]:
    call_crossing_count_by_reg: dict[BackendRegId, int] = {}
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if instruction.dest is not None:
                live_after.discard(instruction.dest)
            for reg_id in live_after:
                call_crossing_count_by_reg[reg_id] = call_crossing_count_by_reg.get(reg_id, 0) + 1
    return call_crossing_count_by_reg


def _caller_saved_spills_by_inst(
    callable_plan: X86_64SysVCallablePlan,
    *,
    physical_register_by_reg: dict[BackendRegId, X86_64SysVPhysicalRegister],
    caller_saved_gprs: tuple[X86_64SysVPhysicalRegister, ...],
) -> dict[BackendInstId, X86_64SysVCallerSavedSpillPoint]:
    caller_saved_register_names = {register.name for register in caller_saved_gprs}
    caller_saved_order = {register.name: index for index, register in enumerate(caller_saved_gprs)}
    spill_points: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint] = {}

    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if instruction.dest is not None:
                live_after.discard(instruction.dest)
            spills = tuple(
                sorted(
                    (
                        X86_64SysVCallerSavedSpill(reg_id=reg_id, physical_register=physical_register)
                        for reg_id in live_after
                        if (physical_register := physical_register_by_reg.get(reg_id)) is not None
                        and physical_register.name in caller_saved_register_names
                    ),
                    key=lambda spill: (caller_saved_order[spill.physical_register.name], reg_id_sort_key(spill.reg_id)),
                )
            )
            if spills:
                spill_points[instruction.inst_id] = X86_64SysVCallerSavedSpillPoint(
                    inst_id=instruction.inst_id,
                    spills=spills,
                )

    return spill_points


def _call_argument_reloads_by_inst(
    callable_plan: X86_64SysVCallablePlan,
    *,
    physical_register_by_reg: dict[BackendRegId, X86_64SysVPhysicalRegister],
    argument_gprs: tuple[X86_64SysVPhysicalRegister, ...],
    argument_xmms: tuple[X86_64SysVPhysicalRegister, ...],
    abi: X86_64SysVAbi,
) -> dict[BackendInstId, tuple[X86_64SysVCallArgumentReload, ...]]:
    argument_register_names = {register.name for register in argument_gprs}
    argument_register_names.update(register.name for register in argument_xmms)
    reloads_by_inst: dict[BackendInstId, tuple[X86_64SysVCallArgumentReload, ...]] = {}

    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            live_after = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            if instruction.dest is not None:
                live_after.discard(instruction.dest)
            arg_locations = abi.plan_argument_locations(
                instruction.signature.param_types,
                includes_receiver=_call_includes_receiver(instruction),
            )
            reloads: list[X86_64SysVCallArgumentReload] = []
            for operand, arg_location in zip(instruction.args, arg_locations, strict=True):
                if arg_location.kind not in {"int_reg", "float_reg"} or arg_location.register_name is None:
                    continue
                if not isinstance(operand, BackendRegOperand) or operand.reg_id in live_after:
                    continue
                physical_register = physical_register_by_reg.get(operand.reg_id)
                if physical_register is None:
                    continue
                if physical_register.name != arg_location.register_name:
                    continue
                if physical_register.name not in argument_register_names:
                    continue
                reloads.append(
                    X86_64SysVCallArgumentReload(
                        reg_id=operand.reg_id,
                        physical_register=physical_register,
                    )
                )
            if reloads:
                reloads_by_inst[instruction.inst_id] = tuple(reloads)

    return reloads_by_inst


def _allocation_fragments_by_reg(
    callable_plan: X86_64SysVCallablePlan,
    *,
    intervals: tuple[X86_64SysVLiveInterval, ...],
    physical_register_by_reg: dict[BackendRegId, X86_64SysVPhysicalRegister],
    caller_saved_spills_by_inst: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint],
    abi_constraints: X86_64SysVAbiConstraintPlan,
) -> dict[BackendRegId, tuple[X86_64SysVAllocationFragment, ...]]:
    positions = build_instruction_positions(callable_plan)
    split_positions_by_reg = _split_positions_by_reg(
        callable_plan,
        intervals=intervals,
        caller_saved_spills_by_inst=caller_saved_spills_by_inst,
        abi_constraints=abi_constraints,
        positions=positions,
    )
    split_call_positions_by_reg = _caller_saved_split_call_positions_by_reg(
        caller_saved_spills_by_inst=caller_saved_spills_by_inst,
        positions=positions,
    )
    fragments_by_reg: dict[BackendRegId, tuple[X86_64SysVAllocationFragment, ...]] = {}

    for interval in intervals:
        physical_register = physical_register_by_reg.get(interval.reg_id)
        stack_slot = _stack_location_for_reg(callable_plan, interval.reg_id)
        split_positions = split_positions_by_reg.get(interval.reg_id, ())
        call_split_positions = set(split_call_positions_by_reg.get(interval.reg_id, ()))
        boundaries = (
            interval.start_position,
            *(
                position
                for position in split_positions
                if interval.start_position <= position <= interval.end_position
            ),
            interval.end_position,
        )
        ordered_boundaries = tuple(dict.fromkeys(sorted(boundaries)))
        fragments: list[X86_64SysVAllocationFragment] = []

        for index, start_position in enumerate(ordered_boundaries):
            if index + 1 >= len(ordered_boundaries):
                break
            end_position = ordered_boundaries[index + 1]
            if start_position == end_position:
                continue
            fragments.append(
                X86_64SysVAllocationFragment(
                    reg_id=interval.reg_id,
                    start_position=start_position,
                    end_position=end_position,
                    physical_register=physical_register,
                    stack_slot=stack_slot if physical_register is None else None,
                    kind="register" if physical_register is not None else "stack",
                )
            )
            if end_position in call_split_positions and stack_slot is not None and physical_register is not None:
                fragments.append(
                    X86_64SysVAllocationFragment(
                        reg_id=interval.reg_id,
                        start_position=end_position,
                        end_position=end_position,
                        physical_register=None,
                        stack_slot=stack_slot,
                        kind="call_boundary_stack",
                    )
                )

        if not fragments:
            fragments.append(
                X86_64SysVAllocationFragment(
                    reg_id=interval.reg_id,
                    start_position=interval.start_position,
                    end_position=interval.end_position,
                    physical_register=physical_register,
                    stack_slot=stack_slot if physical_register is None else None,
                    kind="register" if physical_register is not None else "stack",
                )
            )
        fragments_by_reg[interval.reg_id] = tuple(fragments)

    return fragments_by_reg


def _split_positions_by_reg(
    callable_plan: X86_64SysVCallablePlan,
    *,
    intervals: tuple[X86_64SysVLiveInterval, ...],
    caller_saved_spills_by_inst: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint],
    abi_constraints: X86_64SysVAbiConstraintPlan,
    positions: X86_64SysVInstructionPositions,
) -> dict[BackendRegId, tuple[int, ...]]:
    interval_by_reg = {interval.reg_id: interval for interval in intervals}
    split_positions_by_reg: dict[BackendRegId, set[int]] = {}

    for spill_point in caller_saved_spills_by_inst.values():
        position = positions.instruction_position(spill_point.inst_id)
        for spill in spill_point.spills:
            split_positions_by_reg.setdefault(spill.reg_id, set()).add(position)

    for constraint in abi_constraints.constraints:
        if constraint.reg_id is None or constraint.reg_id not in interval_by_reg:
            continue
        if constraint.kind not in {"clobber", "temporary"} and constraint.reason not in {
            "call_argument",
            "call_return",
            "return_value",
        }:
            continue
        split_positions_by_reg.setdefault(constraint.reg_id, set()).add(constraint.position)

    for block in callable_plan.callable_decl.blocks:
        if len(block.instructions) <= 1:
            continue
        first_position = positions.instruction_position(block.instructions[0].inst_id)
        for reg_id in callable_plan.analysis.liveness.block_live_in(block.block_id):
            if reg_id in interval_by_reg:
                split_positions_by_reg.setdefault(reg_id, set()).add(first_position)

    return {
        reg_id: tuple(sorted(position for position in positions_for_reg if _position_splits_interval(interval_by_reg[reg_id], position)))
        for reg_id, positions_for_reg in split_positions_by_reg.items()
        if reg_id in interval_by_reg
    }


def _position_splits_interval(interval: X86_64SysVLiveInterval, position: int) -> bool:
    return interval.start_position < position < interval.end_position


def _caller_saved_split_call_positions_by_reg(
    *,
    caller_saved_spills_by_inst: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint],
    positions: X86_64SysVInstructionPositions,
) -> dict[BackendRegId, tuple[int, ...]]:
    positions_by_reg: dict[BackendRegId, list[int]] = {}
    for spill_point in caller_saved_spills_by_inst.values():
        position = positions.instruction_position(spill_point.inst_id)
        for spill in spill_point.spills:
            positions_by_reg.setdefault(spill.reg_id, []).append(position)
    return {
        reg_id: tuple(sorted(positions_for_reg))
        for reg_id, positions_for_reg in positions_by_reg.items()
    }


def _resolution_moves_by_inst(
    callable_plan: X86_64SysVCallablePlan,
    *,
    caller_saved_spills_by_inst: dict[BackendInstId, X86_64SysVCallerSavedSpillPoint],
) -> dict[BackendInstId, tuple[X86_64SysVResolutionMove, ...]]:
    positions = build_instruction_positions(callable_plan)
    moves_by_inst: dict[BackendInstId, tuple[X86_64SysVResolutionMove, ...]] = {}
    for inst_id, spill_point in caller_saved_spills_by_inst.items():
        position = positions.instruction_position(inst_id)
        moves: list[X86_64SysVResolutionMove] = []
        for spill in spill_point.spills:
            stack_slot = _stack_location_for_reg(callable_plan, spill.reg_id)
            if stack_slot is None:
                continue
            moves.append(
                X86_64SysVResolutionMove(
                    reg_id=spill.reg_id,
                    position=position,
                    kind="spill_before_call",
                    physical_register=spill.physical_register,
                    stack_slot=stack_slot,
                    inst_id=inst_id,
                )
            )
            moves.append(
                X86_64SysVResolutionMove(
                    reg_id=spill.reg_id,
                    position=position,
                    kind="reload_after_call",
                    physical_register=spill.physical_register,
                    stack_slot=stack_slot,
                    inst_id=inst_id,
                )
            )
        if moves:
            moves_by_inst[inst_id] = tuple(moves)
    return moves_by_inst


def _safepoint_live_reg_ids(callable_plan: X86_64SysVCallablePlan) -> frozenset[BackendRegId]:
    return frozenset(_safepoint_crossing_count_by_reg_id(callable_plan))


def _safepoint_crossing_count_by_reg_id(callable_plan: X86_64SysVCallablePlan) -> dict[BackendRegId, int]:
    safepoint_crossing_count_by_reg: dict[BackendRegId, int] = {}
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if not instruction_is_safepoint(instruction):
                continue
            live_regs = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            live_regs.update(instruction_use_regs(instruction))
            destination = instruction_def_reg(instruction)
            if destination is not None:
                live_regs.discard(destination)
            for reg_id in live_regs:
                safepoint_crossing_count_by_reg[reg_id] = safepoint_crossing_count_by_reg.get(reg_id, 0) + 1
    return safepoint_crossing_count_by_reg


def _non_call_safepoint_crossing_count_by_reg_id(callable_plan: X86_64SysVCallablePlan) -> dict[BackendRegId, int]:
    safepoint_crossing_count_by_reg: dict[BackendRegId, int] = {}
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if isinstance(instruction, BackendCallInst) or not instruction_is_safepoint(instruction):
                continue
            live_regs = set(callable_plan.analysis.liveness.instruction_live_after(instruction.inst_id))
            live_regs.update(instruction_use_regs(instruction))
            destination = instruction_def_reg(instruction)
            if destination is not None:
                live_regs.discard(destination)
            for reg_id in live_regs:
                safepoint_crossing_count_by_reg[reg_id] = safepoint_crossing_count_by_reg.get(reg_id, 0) + 1
    return safepoint_crossing_count_by_reg


def _rematerializable_values_by_reg(
    callable_plan: X86_64SysVCallablePlan,
    *,
    interval_by_reg: dict[BackendRegId, X86_64SysVLiveInterval],
) -> dict[BackendRegId, X86_64SysVRematerializedValue]:
    definition_count_by_reg = _definition_count_by_reg(callable_plan)
    values_by_reg: dict[BackendRegId, X86_64SysVRematerializedValue] = {}

    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            if isinstance(instruction, BackendConstInst):
                if definition_count_by_reg.get(instruction.dest, 0) != 1:
                    continue
                interval = interval_by_reg.get(instruction.dest)
                if interval is None:
                    continue
                if _constant_is_rematerializable(instruction.constant, interval=interval):
                    values_by_reg[instruction.dest] = X86_64SysVRematerializedValue(
                        reg_id=instruction.dest,
                        kind="constant",
                        constant=instruction.constant,
                    )
                continue

            if isinstance(instruction, BackendCopyInst) and isinstance(instruction.source, BackendCallableOperand):
                if definition_count_by_reg.get(instruction.dest, 0) != 1:
                    continue
                interval = interval_by_reg.get(instruction.dest)
                if interval is None or interval.register_class != "gpr":
                    continue
                values_by_reg[instruction.dest] = X86_64SysVRematerializedValue(
                    reg_id=instruction.dest,
                    kind="callable",
                    callable_id=instruction.source.callable_id,
                )

    return values_by_reg


def _definition_count_by_reg(callable_plan: X86_64SysVCallablePlan) -> dict[BackendRegId, int]:
    definition_count_by_reg: dict[BackendRegId, int] = {}
    for block in callable_plan.callable_decl.blocks:
        for instruction in block.instructions:
            reg_id = instruction_def_reg(instruction)
            if reg_id is None:
                continue
            definition_count_by_reg[reg_id] = definition_count_by_reg.get(reg_id, 0) + 1
    return definition_count_by_reg


def _constant_is_rematerializable(
    constant: BackendConstant,
    *,
    interval: X86_64SysVLiveInterval,
) -> bool:
    if interval.register_class != "gpr":
        return False
    if interval.is_gc_reference and interval.live_at_safepoint:
        return False
    if isinstance(constant, BackendIntConst):
        return -(2**31) <= constant.value <= 2**31 - 1
    if isinstance(constant, BackendBoolConst):
        return True
    if isinstance(constant, BackendNullConst):
        return True
    return False


def _expire_inactive_intervals(
    active: list[_ActiveInterval],
    *,
    current_start_position: int,
) -> list[_ActiveInterval]:
    return [
        active_interval
        for active_interval in active
        if active_interval.interval.end_position >= current_start_position
    ]


def _sorted_active_intervals(active: list[_ActiveInterval]) -> list[_ActiveInterval]:
    return sorted(
        active,
        key=lambda active_interval: (
            active_interval.interval.end_position,
            reg_id_sort_key(active_interval.interval.reg_id),
        ),
    )


def _spill_candidate(
    active: list[_ActiveInterval],
    *,
    allowed_registers: tuple[X86_64SysVPhysicalRegister, ...],
    rematerializable_reg_ids: frozenset[BackendRegId] = frozenset(),
) -> _ActiveInterval | None:
    allowed_register_names = {register.name for register in allowed_registers}
    candidates = [
        active_interval
        for active_interval in active
        if active_interval.physical_register.name in allowed_register_names
    ]
    if not candidates:
        return None
    rematerializable_candidates = [
        active_interval
        for active_interval in candidates
        if active_interval.interval.reg_id in rematerializable_reg_ids
    ]
    if rematerializable_candidates:
        return max(
            rematerializable_candidates,
            key=lambda active_interval: (
                active_interval.interval.end_position,
                reg_id_sort_key(active_interval.interval.reg_id),
            ),
        )
    return max(
        candidates,
        key=lambda active_interval: (
            active_interval.interval.end_position,
            reg_id_sort_key(active_interval.interval.reg_id),
        ),
    )


def _stack_location_for_reg(
    callable_plan: X86_64SysVCallablePlan,
    reg_id: BackendRegId,
) -> X86_64SysVStackLocation | None:
    frame_slot = callable_plan.frame_layout.for_reg(reg_id)
    if frame_slot is None:
        return _preallocation_stack_location_for_reg(callable_plan, reg_id)
    return X86_64SysVStackLocation(
        byte_offset=frame_slot.byte_offset,
        debug_name=frame_slot.debug_name,
    )


def _preallocation_stack_location_for_reg(
    callable_plan: X86_64SysVCallablePlan,
    reg_id: BackendRegId,
) -> X86_64SysVStackLocation | None:
    home_name = callable_plan.analysis.stack_homes.stack_home_by_reg.get(reg_id)
    if home_name is None:
        return None
    register_by_id = {register.reg_id: register for register in callable_plan.callable_decl.registers}
    register = register_by_id.get(reg_id)
    if register is None:
        return None
    for index, candidate_reg_id in enumerate(callable_plan.analysis.stack_homes.stack_home_by_reg, start=1):
        if candidate_reg_id == reg_id:
            return X86_64SysVStackLocation(
                byte_offset=-(index * X86_64_SYSV_ABI.stack_slot_size_bytes),
                debug_name=register.debug_name,
            )
    return None


__all__ = [
    "X86_64SysVAbiConstraintPlan",
    "X86_64SysVAllocationFragment",
    "X86_64SysVCallArgumentReload",
    "X86_64SysVCallerSavedSpill",
    "X86_64SysVCallerSavedSpillPoint",
    "X86_64SysVFixedRegisterConstraint",
    "X86_64SysVInstructionPositions",
    "X86_64SysVLiveInterval",
    "X86_64SysVRegisterAllocation",
    "X86_64SysVRematerializedValue",
    "X86_64SysVResolutionMove",
    "allocate_x86_64_sysv_registers",
    "build_abi_constraints",
    "build_instruction_positions",
    "build_live_intervals",
]
