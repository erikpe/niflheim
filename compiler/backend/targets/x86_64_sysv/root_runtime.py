from __future__ import annotations

from compiler.backend.program.runtime_layout import (
    RT_ROOT_FRAME_PREV_OFFSET,
    RT_ROOT_FRAME_RESERVED_OFFSET,
    RT_ROOT_FRAME_SLOT_COUNT_OFFSET,
    RT_ROOT_FRAME_SLOTS_OFFSET,
    RT_THREAD_STATE_ROOTS_TOP_OFFSET,
)
from compiler.backend.targets.x86_64_sysv.asm import format_stack_slot_operand


def thread_state_roots_top_operand(register_name: str) -> str:
    return format_stack_slot_operand(register_name, RT_THREAD_STATE_ROOTS_TOP_OFFSET)


def root_frame_prev_operand(register_name: str) -> str:
    return format_stack_slot_operand(register_name, RT_ROOT_FRAME_PREV_OFFSET)


def root_frame_slot_count_operand(register_name: str) -> str:
    return format_stack_slot_operand(register_name, RT_ROOT_FRAME_SLOT_COUNT_OFFSET, size="dword ptr")


def root_frame_reserved_operand(register_name: str) -> str:
    return format_stack_slot_operand(register_name, RT_ROOT_FRAME_RESERVED_OFFSET, size="dword ptr")


def root_frame_slots_operand(register_name: str) -> str:
    return format_stack_slot_operand(register_name, RT_ROOT_FRAME_SLOTS_OFFSET)


__all__ = [
    "root_frame_prev_operand",
    "root_frame_reserved_operand",
    "root_frame_slot_count_operand",
    "root_frame_slots_operand",
    "thread_state_roots_top_operand",
]