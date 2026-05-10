from __future__ import annotations

from compiler.backend.program.runtime_layout import (
    RT_INTERFACE_DEBUG_NAME_OFFSET,
    RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES,
    RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES,
    RT_OBJ_HEADER_TYPE_OFFSET,
    RT_TYPE_CLASS_VTABLE_OFFSET,
    RT_TYPE_DEBUG_NAME_OFFSET,
    RT_TYPE_INTERFACE_TABLES_OFFSET,
    RT_TYPE_POINTER_OFFSETS_OFFSET,
    RT_VTABLE_ENTRY_SIZE_BYTES,
)
from compiler.backend.targets.x86_64_sysv.asm import format_stack_slot_operand


def object_type_operand(object_register: str) -> str:
    return format_stack_slot_operand(object_register, RT_OBJ_HEADER_TYPE_OFFSET)


def type_debug_name_operand(type_register: str) -> str:
    return format_stack_slot_operand(type_register, RT_TYPE_DEBUG_NAME_OFFSET)


def pointer_offsets_operand(type_register: str) -> str:
    return format_stack_slot_operand(type_register, RT_TYPE_POINTER_OFFSETS_OFFSET)


def interface_tables_operand(type_register: str) -> str:
    return format_stack_slot_operand(type_register, RT_TYPE_INTERFACE_TABLES_OFFSET)


def interface_table_entry_operand(interface_tables_register: str, slot_index: int) -> str:
    if slot_index < 0:
        raise ValueError("interface slot index must be non-negative")
    return format_stack_slot_operand(interface_tables_register, slot_index * RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES)


def interface_debug_name_operand(interface_register: str) -> str:
    return format_stack_slot_operand(interface_register, RT_INTERFACE_DEBUG_NAME_OFFSET)


def interface_method_entry_operand(method_table_register: str, slot_index: int) -> str:
    if slot_index < 0:
        raise ValueError("interface method slot index must be non-negative")
    return format_stack_slot_operand(method_table_register, slot_index * RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES)


def class_vtable_operand(type_register: str) -> str:
    return format_stack_slot_operand(type_register, RT_TYPE_CLASS_VTABLE_OFFSET)


def class_vtable_entry_operand(vtable_register: str, slot_index: int) -> str:
    if slot_index < 0:
        raise ValueError("virtual method slot index must be non-negative")
    return format_stack_slot_operand(vtable_register, slot_index * RT_VTABLE_ENTRY_SIZE_BYTES)


__all__ = [
    "class_vtable_entry_operand",
    "class_vtable_operand",
    "interface_debug_name_operand",
    "interface_method_entry_operand",
    "interface_table_entry_operand",
    "interface_tables_operand",
    "object_type_operand",
    "pointer_offsets_operand",
    "type_debug_name_operand",
]