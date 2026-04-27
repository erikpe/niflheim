from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendCallInst, BackendCallableDecl, BackendRegId
from compiler.backend.targets import BackendTargetInput, BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI, X86_64SysVAbi


@dataclass(frozen=True, slots=True)
class X86_64SysVFrameSlot:
    reg_id: BackendRegId
    home_name: str
    debug_name: str
    byte_offset: int


@dataclass(frozen=True, slots=True)
class X86_64SysVFrameLayout:
    callable_decl: BackendCallableDecl
    slots: tuple[X86_64SysVFrameSlot, ...]
    slot_by_reg: dict[BackendRegId, X86_64SysVFrameSlot]
    slot_by_home_name: dict[str, X86_64SysVFrameSlot]
    outgoing_stack_arg_offsets: tuple[int, ...]
    scratch_slot_offsets: tuple[int, ...]
    stack_size: int

    def for_reg(self, reg_id: BackendRegId) -> X86_64SysVFrameSlot | None:
        return self.slot_by_reg.get(reg_id)

    def for_home_name(self, home_name: str) -> X86_64SysVFrameSlot | None:
        return self.slot_by_home_name.get(home_name)

    @property
    def home_count(self) -> int:
        return len(self.slots)


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
    if callable_analysis.root_slots.root_slot_by_reg:
        _frame_error(
            callable_decl,
            "reduced phase-4 x86_64_sysv does not yet support GC root-slot setup",
        )

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
    scratch_slot_offsets = tuple(
        next_offset - (index * abi.stack_slot_size_bytes)
        for index in range(1, scratch_slot_count + 1)
    )
    next_offset -= scratch_slot_count * abi.stack_slot_size_bytes
    outgoing_stack_arg_offsets = tuple(
        next_offset - (index * abi.stack_slot_size_bytes)
        for index in range(1, resolved_outgoing_stack_arg_slot_count + 1)
    )

    frame_bytes = (len(slots) + scratch_slot_count + resolved_outgoing_stack_arg_slot_count) * abi.stack_slot_size_bytes
    return X86_64SysVFrameLayout(
        callable_decl=callable_decl,
        slots=tuple(slots),
        slot_by_reg=slot_by_reg,
        slot_by_home_name=slot_by_home_name,
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
            max_stack_arg_slot_count = max(
                max_stack_arg_slot_count,
                abi.outgoing_stack_arg_slot_count(len(instruction.args)),
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
    "X86_64SysVFrameSlot",
    "plan_callable_frame_layout",
]