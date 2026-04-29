from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendCallInst, BackendCallableDecl, BackendRegId
from compiler.backend.targets import BackendTargetInput, BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI, X86_64SysVAbi
from compiler.backend.targets.x86_64_sysv.root_runtime import RT_ROOT_FRAME_SIZE_BYTES


@dataclass(frozen=True, slots=True)
class X86_64SysVFrameSlot:
    reg_id: BackendRegId
    home_name: str
    debug_name: str
    byte_offset: int


@dataclass(frozen=True, slots=True)
class X86_64SysVRootSlot:
    slot_index: int
    reg_ids: tuple[BackendRegId, ...]
    byte_offset: int


@dataclass(frozen=True, slots=True)
class X86_64SysVFrameLayout:
    callable_decl: BackendCallableDecl
    slots: tuple[X86_64SysVFrameSlot, ...]
    slot_by_reg: dict[BackendRegId, X86_64SysVFrameSlot]
    slot_by_home_name: dict[str, X86_64SysVFrameSlot]
    root_slots: tuple[X86_64SysVRootSlot, ...]
    root_slot_by_reg: dict[BackendRegId, X86_64SysVRootSlot]
    thread_state_offset: int | None
    root_frame_offset: int | None
    outgoing_stack_arg_offsets: tuple[int, ...]
    scratch_slot_offsets: tuple[int, ...]
    stack_size: int

    def for_reg(self, reg_id: BackendRegId) -> X86_64SysVFrameSlot | None:
        return self.slot_by_reg.get(reg_id)

    def for_home_name(self, home_name: str) -> X86_64SysVFrameSlot | None:
        return self.slot_by_home_name.get(home_name)

    def root_slot_for_reg(self, reg_id: BackendRegId) -> X86_64SysVRootSlot | None:
        return self.root_slot_by_reg.get(reg_id)

    @property
    def home_count(self) -> int:
        return len(self.slots)

    @property
    def root_slot_count(self) -> int:
        return len(self.root_slots)

    @property
    def has_root_frame(self) -> bool:
        return self.root_slot_count > 0


class X86_64SysVFrameError(BackendTargetLoweringError):
    """Raised when the reduced x86-64 SysV frame slice cannot materialize a callable."""


def plan_callable_frame_layout(
    target_input: BackendTargetInput,
    callable_decl: BackendCallableDecl,
    *,
    abi: X86_64SysVAbi = X86_64_SYSV_ABI,
    outgoing_stack_arg_slot_count: int | None = None,
    scratch_slot_count: int = 0,
) -> X86_64SysVFrameLayout:
    resolved_outgoing_stack_arg_slot_count = (
        _max_outgoing_stack_arg_slot_count(callable_decl, abi=abi)
        if outgoing_stack_arg_slot_count is None
        else outgoing_stack_arg_slot_count
    )
    if resolved_outgoing_stack_arg_slot_count < 0:
        raise ValueError("Outgoing stack argument slot count must be non-negative")
    if scratch_slot_count < 0:
        raise ValueError("Scratch slot count must be non-negative")

    callable_analysis = target_input.analysis_for_callable(callable_decl.callable_id)

    registers_by_reg_id = {register.reg_id: register for register in callable_decl.registers}
    slots: list[X86_64SysVFrameSlot] = []
    slot_by_reg: dict[BackendRegId, X86_64SysVFrameSlot] = {}
    slot_by_home_name: dict[str, X86_64SysVFrameSlot] = {}

    for index, (reg_id, home_name) in enumerate(callable_analysis.stack_homes.stack_home_by_reg.items(), start=1):
        register = registers_by_reg_id[reg_id]
        slot = X86_64SysVFrameSlot(
            reg_id=reg_id,
            home_name=home_name,
            debug_name=register.debug_name,
            byte_offset=-(index * abi.stack_slot_size_bytes),
        )
        slots.append(slot)
        slot_by_reg[reg_id] = slot
        slot_by_home_name[home_name] = slot

    next_offset = -(len(slots) * abi.stack_slot_size_bytes)

    thread_state_offset: int | None = None
    root_frame_offset: int | None = None
    root_slots: list[X86_64SysVRootSlot] = []
    root_slot_by_reg: dict[BackendRegId, X86_64SysVRootSlot] = {}
    if callable_analysis.root_slots.slot_count > 0:
        thread_state_offset = next_offset - abi.stack_slot_size_bytes
        next_offset = thread_state_offset
        root_frame_offset = next_offset - RT_ROOT_FRAME_SIZE_BYTES
        next_offset = root_frame_offset
        for slot_index, reg_ids in enumerate(callable_analysis.root_slots.slot_reg_ids):
            byte_offset = next_offset - abi.stack_slot_size_bytes
            next_offset = byte_offset
            root_slot = X86_64SysVRootSlot(
                slot_index=slot_index,
                reg_ids=reg_ids,
                byte_offset=byte_offset,
            )
            root_slots.append(root_slot)
            for reg_id in reg_ids:
                root_slot_by_reg[reg_id] = root_slot

    scratch_slot_offsets = tuple(
        next_offset - (index * abi.stack_slot_size_bytes)
        for index in range(1, scratch_slot_count + 1)
    )
    next_offset -= scratch_slot_count * abi.stack_slot_size_bytes
    outgoing_stack_arg_offsets = tuple(
        next_offset - (index * abi.stack_slot_size_bytes)
        for index in range(1, resolved_outgoing_stack_arg_slot_count + 1)
    )

    frame_bytes = abs(next_offset) + (resolved_outgoing_stack_arg_slot_count * abi.stack_slot_size_bytes)
    return X86_64SysVFrameLayout(
        callable_decl=callable_decl,
        slots=tuple(slots),
        slot_by_reg=slot_by_reg,
        slot_by_home_name=slot_by_home_name,
        root_slots=tuple(root_slots),
        root_slot_by_reg=root_slot_by_reg,
        thread_state_offset=thread_state_offset,
        root_frame_offset=root_frame_offset,
        outgoing_stack_arg_offsets=outgoing_stack_arg_offsets,
        scratch_slot_offsets=scratch_slot_offsets,
        stack_size=abi.align_stack_size(frame_bytes),
    )


def _max_outgoing_stack_arg_slot_count(callable_decl: BackendCallableDecl, *, abi: X86_64SysVAbi) -> int:
    max_stack_arg_slot_count = 0
    for block in callable_decl.blocks:
        for instruction in block.instructions:
            if not isinstance(instruction, BackendCallInst):
                continue
            includes_receiver = len(instruction.args) == len(instruction.signature.param_types) + 1
            max_stack_arg_slot_count = max(
                max_stack_arg_slot_count,
                abi.outgoing_stack_arg_slot_count(
                    instruction.signature.param_types,
                    includes_receiver=includes_receiver,
                ),
            )
    return max_stack_arg_slot_count


def _frame_error(callable_decl: BackendCallableDecl, message: str) -> None:
    raise X86_64SysVFrameError(
        f"Backend target 'x86_64_sysv' callable '{_format_callable_id(callable_decl)}': {message}"
    )


def _format_callable_id(callable_decl: BackendCallableDecl) -> str:
    callable_id = callable_decl.callable_id
    if hasattr(callable_id, "class_name") and hasattr(callable_id, "ordinal"):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
    if hasattr(callable_id, "class_name"):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
    return f"{'.'.join(callable_id.module_path)}::{callable_id.name}"


__all__ = [
    "X86_64SysVFrameError",
    "X86_64SysVFrameLayout",
    "X86_64SysVRootSlot",
    "X86_64SysVFrameSlot",
    "plan_callable_frame_layout",
]