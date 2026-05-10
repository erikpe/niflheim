from __future__ import annotations

from compiler.backend.program.runtime_layout import (
    RT_ARRAY_DATA_OFFSET,
    RT_ARRAY_ELEMENT_KIND_OFFSET,
    RT_ARRAY_LEN_OFFSET,
    direct_primitive_array_element_size,
)
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, emit_add_address, format_memory_operand
from compiler.common.collection_protocols import ArrayRuntimeKind


def array_element_kind_operand(array_register: str) -> str:
    return format_memory_operand(array_register, RT_ARRAY_ELEMENT_KIND_OFFSET)


def array_length_operand(array_register: str) -> str:
    return format_memory_operand(array_register, RT_ARRAY_LEN_OFFSET)


def emit_array_data_address(builder: AArch64AsmBuilder, target_register: str, array_register: str) -> None:
    emit_add_address(builder, target_register, array_register, RT_ARRAY_DATA_OFFSET)


def direct_primitive_array_load_operand(data_register: str, index_register: str, *, runtime_kind: ArrayRuntimeKind) -> str:
    element_size = direct_primitive_array_element_size(runtime_kind)
    if element_size == 1:
        return f"[{data_register}, {index_register}]"
    if element_size == 8:
        return f"[{data_register}, {index_register}, lsl #3]"
    raise ValueError(f"unsupported direct primitive array runtime kind '{runtime_kind}'")


def direct_ref_array_operand(data_register: str, index_register: str) -> str:
    return f"[{data_register}, {index_register}, lsl #3]"


__all__ = [
    "array_element_kind_operand",
    "array_length_operand",
    "direct_primitive_array_load_operand",
    "direct_ref_array_operand",
    "emit_array_data_address",
]