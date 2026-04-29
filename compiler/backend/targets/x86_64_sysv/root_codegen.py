from __future__ import annotations

from compiler.backend.ir import BackendRegId
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.backend.targets.x86_64_sysv.root_runtime import (
    root_frame_prev_operand,
    root_frame_reserved_operand,
    root_frame_slot_count_operand,
    root_frame_slots_operand,
    thread_state_roots_top_operand,
)


def emit_zero_root_slots(builder: X86AsmBuilder, *, frame_layout: X86_64SysVFrameLayout) -> None:
    for root_slot in frame_layout.root_slots:
        builder.instruction("mov", format_stack_slot_operand("rbp", root_slot.byte_offset), "0")


def emit_root_frame_setup(builder: X86AsmBuilder, *, frame_layout: X86_64SysVFrameLayout) -> None:
    if not frame_layout.has_root_frame:
        return
    if frame_layout.thread_state_offset is None or frame_layout.root_frame_offset is None:
        raise BackendTargetLoweringError("x86_64_sysv root-frame setup requires thread-state and root-frame slots")
    if not frame_layout.root_slots:
        raise BackendTargetLoweringError("x86_64_sysv root-frame setup requires at least one root slot")

    builder.instruction("call", "rt_thread_state")
    builder.instruction("mov", format_stack_slot_operand("rbp", frame_layout.thread_state_offset), "rax")
    builder.instruction("lea", "rdi", f"[rbp - {abs(frame_layout.root_frame_offset)}]")
    builder.instruction("mov", "rcx", thread_state_roots_top_operand("rax"))
    builder.instruction("mov", root_frame_prev_operand("rdi"), "rcx")
    builder.instruction("mov", root_frame_slot_count_operand("rdi"), str(frame_layout.root_slot_count))
    builder.instruction("mov", root_frame_reserved_operand("rdi"), "0")
    first_root_slot_offset = min(root_slot.byte_offset for root_slot in frame_layout.root_slots)
    builder.instruction("lea", "rcx", f"[rbp - {abs(first_root_slot_offset)}]")
    builder.instruction("mov", root_frame_slots_operand("rdi"), "rcx")
    builder.instruction("mov", thread_state_roots_top_operand("rax"), "rdi")


def emit_root_frame_pop(builder: X86AsmBuilder, *, frame_layout: X86_64SysVFrameLayout) -> None:
    if not frame_layout.has_root_frame:
        return
    if frame_layout.thread_state_offset is None or frame_layout.root_frame_offset is None:
        raise BackendTargetLoweringError("x86_64_sysv root-frame teardown requires thread-state and root-frame slots")

    builder.instruction("mov", "rdi", format_stack_slot_operand("rbp", frame_layout.thread_state_offset))
    builder.instruction("lea", "rcx", f"[rbp - {abs(frame_layout.root_frame_offset)}]")
    builder.instruction("mov", "rcx", root_frame_prev_operand("rcx"))
    builder.instruction("mov", thread_state_roots_top_operand("rdi"), "rcx")


def emit_root_slot_sync(
    builder: X86AsmBuilder,
    *,
    frame_layout: X86_64SysVFrameLayout,
    live_reg_ids: tuple[BackendRegId, ...],
) -> None:
    for reg_id in live_reg_ids:
        home_slot = frame_layout.for_reg(reg_id)
        root_slot = frame_layout.root_slot_for_reg(reg_id)
        if home_slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv root sync is missing a stack home for register 'r{reg_id.ordinal}'"
            )
        if root_slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv root sync is missing a root slot for register 'r{reg_id.ordinal}'"
            )
        builder.instruction("mov", "r10", format_stack_slot_operand("rbp", home_slot.byte_offset))
        builder.instruction("mov", format_stack_slot_operand("rbp", root_slot.byte_offset), "r10")


def emit_root_slot_reload(
    builder: X86AsmBuilder,
    *,
    frame_layout: X86_64SysVFrameLayout,
    live_reg_ids: tuple[BackendRegId, ...],
) -> None:
    for reg_id in live_reg_ids:
        home_slot = frame_layout.for_reg(reg_id)
        root_slot = frame_layout.root_slot_for_reg(reg_id)
        if home_slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv root reload is missing a stack home for register 'r{reg_id.ordinal}'"
            )
        if root_slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv root reload is missing a root slot for register 'r{reg_id.ordinal}'"
            )
        builder.instruction("mov", "r10", format_stack_slot_operand("rbp", root_slot.byte_offset))
        builder.instruction("mov", format_stack_slot_operand("rbp", home_slot.byte_offset), "r10")


__all__ = [
    "emit_root_frame_pop",
    "emit_root_frame_setup",
    "emit_root_slot_reload",
    "emit_root_slot_sync",
    "emit_zero_root_slots",
]