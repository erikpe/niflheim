from __future__ import annotations

from compiler.backend.ir import BackendRegId
from compiler.backend.program.runtime_layout import (
    RT_ROOT_FRAME_PREV_OFFSET,
    RT_ROOT_FRAME_RESERVED_OFFSET,
    RT_ROOT_FRAME_SLOT_COUNT_OFFSET,
    RT_ROOT_FRAME_SLOTS_OFFSET,
    RT_THREAD_STATE_ROOTS_TOP_OFFSET,
)
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, emit_add_address, format_memory_operand, format_stack_slot_operand
from compiler.backend.targets.aarch64.frame import AArch64FrameLayout


def emit_zero_root_slots(builder: AArch64AsmBuilder, *, frame_layout: AArch64FrameLayout) -> None:
    for root_slot in frame_layout.root_slots:
        builder.instruction("str", "xzr", format_stack_slot_operand("x29", root_slot.byte_offset))


def emit_root_frame_setup(builder: AArch64AsmBuilder, *, frame_layout: AArch64FrameLayout) -> None:
    if not frame_layout.has_root_frame:
        return
    if frame_layout.thread_state_offset is None or frame_layout.root_frame_offset is None:
        raise BackendTargetLoweringError("aarch64 root-frame setup requires thread-state and root-frame slots")
    if not frame_layout.root_slots:
        raise BackendTargetLoweringError("aarch64 root-frame setup requires at least one root slot")

    builder.instruction("bl", "rt_thread_state")
    builder.instruction("str", "x0", format_stack_slot_operand("x29", frame_layout.thread_state_offset))
    emit_add_address(builder, "x1", "x29", frame_layout.root_frame_offset)
    builder.instruction("ldr", "x2", format_memory_operand("x0", RT_THREAD_STATE_ROOTS_TOP_OFFSET))
    builder.instruction("str", "x2", format_memory_operand("x1", RT_ROOT_FRAME_PREV_OFFSET))
    builder.instruction("mov", "w2", f"#{frame_layout.root_slot_count}")
    builder.instruction("str", "w2", format_memory_operand("x1", RT_ROOT_FRAME_SLOT_COUNT_OFFSET))
    builder.instruction("mov", "w2", "wzr")
    builder.instruction("str", "w2", format_memory_operand("x1", RT_ROOT_FRAME_RESERVED_OFFSET))
    first_root_slot_offset = min(root_slot.byte_offset for root_slot in frame_layout.root_slots)
    emit_add_address(builder, "x2", "x29", first_root_slot_offset)
    builder.instruction("str", "x2", format_memory_operand("x1", RT_ROOT_FRAME_SLOTS_OFFSET))
    builder.instruction("str", "x1", format_memory_operand("x0", RT_THREAD_STATE_ROOTS_TOP_OFFSET))


def emit_root_frame_pop(builder: AArch64AsmBuilder, *, frame_layout: AArch64FrameLayout) -> None:
    if not frame_layout.has_root_frame:
        return
    if frame_layout.thread_state_offset is None or frame_layout.root_frame_offset is None:
        raise BackendTargetLoweringError("aarch64 root-frame teardown requires thread-state and root-frame slots")

    builder.instruction("ldr", "x0", format_stack_slot_operand("x29", frame_layout.thread_state_offset))
    emit_add_address(builder, "x1", "x29", frame_layout.root_frame_offset)
    builder.instruction("ldr", "x1", format_memory_operand("x1", RT_ROOT_FRAME_PREV_OFFSET))
    builder.instruction("str", "x1", format_memory_operand("x0", RT_THREAD_STATE_ROOTS_TOP_OFFSET))


def emit_root_slot_sync(
    builder: AArch64AsmBuilder,
    *,
    frame_layout: AArch64FrameLayout,
    live_reg_ids: tuple[BackendRegId, ...],
) -> None:
    for reg_id in live_reg_ids:
        home_slot = frame_layout.for_reg(reg_id)
        root_slot = frame_layout.root_slot_for_reg(reg_id)
        if home_slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 root sync is missing a stack home for register 'r{reg_id.ordinal}'"
            )
        if root_slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 root sync is missing a root slot for register 'r{reg_id.ordinal}'"
            )
        builder.instruction("ldr", "x10", format_stack_slot_operand("x29", home_slot.byte_offset))
        builder.instruction("str", "x10", format_stack_slot_operand("x29", root_slot.byte_offset))


def emit_root_slot_reload(
    builder: AArch64AsmBuilder,
    *,
    frame_layout: AArch64FrameLayout,
    live_reg_ids: tuple[BackendRegId, ...],
) -> None:
    for reg_id in live_reg_ids:
        home_slot = frame_layout.for_reg(reg_id)
        root_slot = frame_layout.root_slot_for_reg(reg_id)
        if home_slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 root reload is missing a stack home for register 'r{reg_id.ordinal}'"
            )
        if root_slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 root reload is missing a root slot for register 'r{reg_id.ordinal}'"
            )
        builder.instruction("ldr", "x10", format_stack_slot_operand("x29", root_slot.byte_offset))
        builder.instruction("str", "x10", format_stack_slot_operand("x29", home_slot.byte_offset))


__all__ = [
    "emit_root_frame_pop",
    "emit_root_frame_setup",
    "emit_root_slot_reload",
    "emit_root_slot_sync",
    "emit_zero_root_slots",
]