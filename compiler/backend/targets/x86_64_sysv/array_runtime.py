from __future__ import annotations

from compiler.backend.program.runtime_layout import (
    RT_ARRAY_DATA_OFFSET,
    RT_ARRAY_ELEMENT_KIND_OFFSET,
    RT_ARRAY_LEN_OFFSET,
    direct_primitive_array_element_size,
)
from compiler.backend.targets.x86_64_sysv.asm import format_stack_slot_operand
from compiler.common.collection_protocols import ArrayRuntimeKind


def array_element_kind_operand(array_register: str) -> str:
    return format_stack_slot_operand(array_register, RT_ARRAY_ELEMENT_KIND_OFFSET)


def array_length_operand(array_register: str) -> str:
    return format_stack_slot_operand(array_register, RT_ARRAY_LEN_OFFSET)


def array_data_index_address(array_register: str, index_register: str, *, element_size: int) -> str:
    if element_size not in {1, 8}:
        raise ValueError(f"unsupported direct array element size: {element_size}")
    if element_size == 1:
        return f"[{array_register} + {index_register} + {RT_ARRAY_DATA_OFFSET}]"
    return f"[{array_register} + {index_register} * {element_size} + {RT_ARRAY_DATA_OFFSET}]"


def direct_primitive_array_store_operand(
    array_register: str, index_register: str, *, runtime_kind: ArrayRuntimeKind
) -> str:
    address = array_data_index_address(
        array_register,
        index_register,
        element_size=direct_primitive_array_element_size(runtime_kind),
    )
    if runtime_kind is ArrayRuntimeKind.U8:
        return f"byte ptr {address}"
    return f"qword ptr {address}"


def direct_ref_array_store_operand(array_register: str, index_register: str) -> str:
    return f"qword ptr {array_data_index_address(array_register, index_register, element_size=8)}"


__all__ = [
    "array_data_index_address",
    "array_element_kind_operand",
    "array_length_operand",
    "direct_primitive_array_store_operand",
    "direct_ref_array_store_operand",
]