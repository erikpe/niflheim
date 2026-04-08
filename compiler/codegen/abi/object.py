from __future__ import annotations

from compiler.codegen.asm import stack_slot_operand


# These constants mirror runtime/include/runtime.h:RtObjHeader and RtType.
RT_OBJ_HEADER_TYPE_OFFSET = 0
RT_TYPE_INTERFACE_TABLES_OFFSET = 64
RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES = 8
RT_VTABLE_ENTRY_SIZE_BYTES = 8
RT_TYPE_CLASS_VTABLE_OFFSET = 80


def object_type_operand(object_register: str) -> str:
    return stack_slot_operand(object_register, RT_OBJ_HEADER_TYPE_OFFSET)


def class_vtable_operand(type_register: str) -> str:
    return stack_slot_operand(type_register, RT_TYPE_CLASS_VTABLE_OFFSET)


def interface_tables_operand(type_register: str) -> str:
    return stack_slot_operand(type_register, RT_TYPE_INTERFACE_TABLES_OFFSET)


def interface_table_entry_operand(interface_tables_register: str, slot_index: int) -> str:
    if slot_index < 0:
        raise ValueError("interface slot index must be non-negative")
    return stack_slot_operand(interface_tables_register, slot_index * RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES)


def class_vtable_entry_operand(vtable_register: str, slot_index: int) -> str:
    if slot_index < 0:
        raise ValueError("virtual method slot index must be non-negative")
    return stack_slot_operand(vtable_register, slot_index * RT_VTABLE_ENTRY_SIZE_BYTES)