from __future__ import annotations

from compiler.backend.targets.x86_64_sysv.asm import format_stack_slot_operand
from compiler.common.collection_protocols import ArrayRuntimeKind


ARRAY_FROM_BYTES_U8_RUNTIME_CALL = "rt_array_from_bytes_u8"
ARRAY_LEN_RUNTIME_CALL = "rt_array_len"

# These constants mirror runtime/src/array.c and runtime/include/runtime.h.
RT_OBJ_HEADER_SIZE_BYTES = 24
RT_ARRAY_LEN_OFFSET = RT_OBJ_HEADER_SIZE_BYTES
RT_ARRAY_ELEMENT_KIND_OFFSET = RT_ARRAY_LEN_OFFSET + 8

RT_ARRAY_KIND_I64 = 1
RT_ARRAY_KIND_U64 = 2
RT_ARRAY_KIND_U8 = 3
RT_ARRAY_KIND_BOOL = 4
RT_ARRAY_KIND_DOUBLE = 5
RT_ARRAY_KIND_REF = 6

RT_ARRAY_PRIMITIVE_TYPE_SYMBOL = "rt_type_array_primitive_desc"
RT_ARRAY_REFERENCE_TYPE_SYMBOL = "rt_type_array_reference_desc"

ARRAY_CONSTRUCTOR_RUNTIME_CALLS: dict[ArrayRuntimeKind, str] = {
    ArrayRuntimeKind.I64: "rt_array_new_i64",
    ArrayRuntimeKind.U64: "rt_array_new_u64",
    ArrayRuntimeKind.U8: "rt_array_new_u8",
    ArrayRuntimeKind.BOOL: "rt_array_new_bool",
    ArrayRuntimeKind.DOUBLE: "rt_array_new_double",
    ArrayRuntimeKind.REF: "rt_array_new_ref",
}

ARRAY_INDEX_GET_RUNTIME_CALLS: dict[ArrayRuntimeKind, str] = {
    ArrayRuntimeKind.I64: "rt_array_get_i64",
    ArrayRuntimeKind.U64: "rt_array_get_u64",
    ArrayRuntimeKind.U8: "rt_array_get_u8",
    ArrayRuntimeKind.BOOL: "rt_array_get_bool",
    ArrayRuntimeKind.DOUBLE: "rt_array_get_double",
    ArrayRuntimeKind.REF: "rt_array_get_ref",
}

ARRAY_INDEX_SET_RUNTIME_CALLS: dict[ArrayRuntimeKind, str] = {
    ArrayRuntimeKind.I64: "rt_array_set_i64",
    ArrayRuntimeKind.U64: "rt_array_set_u64",
    ArrayRuntimeKind.U8: "rt_array_set_u8",
    ArrayRuntimeKind.BOOL: "rt_array_set_bool",
    ArrayRuntimeKind.DOUBLE: "rt_array_set_double",
    ArrayRuntimeKind.REF: "rt_array_set_ref",
}

ARRAY_SLICE_GET_RUNTIME_CALLS: dict[ArrayRuntimeKind, str] = {
    ArrayRuntimeKind.I64: "rt_array_slice_i64",
    ArrayRuntimeKind.U64: "rt_array_slice_u64",
    ArrayRuntimeKind.U8: "rt_array_slice_u8",
    ArrayRuntimeKind.BOOL: "rt_array_slice_bool",
    ArrayRuntimeKind.DOUBLE: "rt_array_slice_double",
    ArrayRuntimeKind.REF: "rt_array_slice_ref",
}

ARRAY_SLICE_SET_RUNTIME_CALLS: dict[ArrayRuntimeKind, str] = {
    ArrayRuntimeKind.I64: "rt_array_set_slice_i64",
    ArrayRuntimeKind.U64: "rt_array_set_slice_u64",
    ArrayRuntimeKind.U8: "rt_array_set_slice_u8",
    ArrayRuntimeKind.BOOL: "rt_array_set_slice_bool",
    ArrayRuntimeKind.DOUBLE: "rt_array_set_slice_double",
    ArrayRuntimeKind.REF: "rt_array_set_slice_ref",
}


ARRAY_RUNTIME_KIND_TAGS: dict[ArrayRuntimeKind, int] = {
    ArrayRuntimeKind.I64: RT_ARRAY_KIND_I64,
    ArrayRuntimeKind.U64: RT_ARRAY_KIND_U64,
    ArrayRuntimeKind.U8: RT_ARRAY_KIND_U8,
    ArrayRuntimeKind.BOOL: RT_ARRAY_KIND_BOOL,
    ArrayRuntimeKind.DOUBLE: RT_ARRAY_KIND_DOUBLE,
    ArrayRuntimeKind.REF: RT_ARRAY_KIND_REF,
}

ARRAY_RUNTIME_KIND_DISPLAY_NAMES: dict[int, str] = {
    RT_ARRAY_KIND_I64: "i64[]",
    RT_ARRAY_KIND_U64: "u64[]",
    RT_ARRAY_KIND_U8: "u8[]",
    RT_ARRAY_KIND_BOOL: "bool[]",
    RT_ARRAY_KIND_DOUBLE: "double[]",
    RT_ARRAY_KIND_REF: "Obj[]",
}


def array_element_kind_operand(array_register: str) -> str:
    return format_stack_slot_operand(array_register, RT_ARRAY_ELEMENT_KIND_OFFSET)


def array_runtime_kind_tag(runtime_kind: ArrayRuntimeKind) -> int:
    return ARRAY_RUNTIME_KIND_TAGS[runtime_kind]


def array_runtime_kind_display_name_for_tag(kind_tag: int) -> str:
    return ARRAY_RUNTIME_KIND_DISPLAY_NAMES.get(kind_tag, "<unknown-array-kind>")


__all__ = [
    "ARRAY_CONSTRUCTOR_RUNTIME_CALLS",
    "ARRAY_FROM_BYTES_U8_RUNTIME_CALL",
    "ARRAY_INDEX_GET_RUNTIME_CALLS",
    "ARRAY_INDEX_SET_RUNTIME_CALLS",
    "ARRAY_LEN_RUNTIME_CALL",
    "ARRAY_RUNTIME_KIND_DISPLAY_NAMES",
    "ARRAY_RUNTIME_KIND_TAGS",
    "ARRAY_SLICE_GET_RUNTIME_CALLS",
    "ARRAY_SLICE_SET_RUNTIME_CALLS",
    "RT_ARRAY_ELEMENT_KIND_OFFSET",
    "RT_ARRAY_KIND_BOOL",
    "RT_ARRAY_KIND_DOUBLE",
    "RT_ARRAY_KIND_I64",
    "RT_ARRAY_KIND_REF",
    "RT_ARRAY_KIND_U64",
    "RT_ARRAY_KIND_U8",
    "RT_ARRAY_LEN_OFFSET",
    "RT_ARRAY_PRIMITIVE_TYPE_SYMBOL",
    "RT_ARRAY_REFERENCE_TYPE_SYMBOL",
    "RT_OBJ_HEADER_SIZE_BYTES",
    "array_element_kind_operand",
    "array_runtime_kind_display_name_for_tag",
    "array_runtime_kind_tag",
]