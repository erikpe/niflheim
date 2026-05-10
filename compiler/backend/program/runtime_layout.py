"""Shared C runtime ABI layout and metadata constants for checked backends."""

from __future__ import annotations

from compiler.common.collection_protocols import ArrayRuntimeKind


RT_THREAD_STATE_ROOTS_TOP_OFFSET = 0

RT_ROOT_FRAME_PREV_OFFSET = 0
RT_ROOT_FRAME_SLOT_COUNT_OFFSET = 8
RT_ROOT_FRAME_RESERVED_OFFSET = 12
RT_ROOT_FRAME_SLOTS_OFFSET = 16
RT_ROOT_FRAME_SIZE_BYTES = 24

RT_OBJ_HEADER_TYPE_OFFSET = 0
RT_OBJ_HEADER_SIZE_BYTES = 24

RT_TYPE_DEBUG_NAME_OFFSET = 24
RT_TYPE_POINTER_OFFSETS_OFFSET = 40
RT_TYPE_SUPER_TYPE_OFFSET = 56
RT_TYPE_INTERFACE_TABLES_OFFSET = 64
RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES = 8
RT_INTERFACE_DEBUG_NAME_OFFSET = 0
RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES = 8
RT_TYPE_CLASS_VTABLE_OFFSET = 80
RT_VTABLE_ENTRY_SIZE_BYTES = 8

RT_TYPE_FLAG_HAS_REFS = 1

RT_ARRAY_LEN_OFFSET = RT_OBJ_HEADER_SIZE_BYTES
RT_ARRAY_ELEMENT_KIND_OFFSET = RT_ARRAY_LEN_OFFSET + 8
RT_ARRAY_ELEMENT_SIZE_OFFSET = RT_ARRAY_ELEMENT_KIND_OFFSET + 8
RT_ARRAY_DATA_OFFSET = RT_ARRAY_ELEMENT_SIZE_OFFSET + 8

RT_ARRAY_KIND_I64 = 1
RT_ARRAY_KIND_U64 = 2
RT_ARRAY_KIND_U8 = 3
RT_ARRAY_KIND_BOOL = 4
RT_ARRAY_KIND_DOUBLE = 5
RT_ARRAY_KIND_REF = 6

RT_ARRAY_PRIMITIVE_TYPE_SYMBOL = "rt_type_array_primitive_desc"
RT_ARRAY_REFERENCE_TYPE_SYMBOL = "rt_type_array_reference_desc"

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

DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES: dict[ArrayRuntimeKind, int] = {
    ArrayRuntimeKind.I64: 8,
    ArrayRuntimeKind.U64: 8,
    ArrayRuntimeKind.U8: 1,
    ArrayRuntimeKind.BOOL: 8,
    ArrayRuntimeKind.DOUBLE: 8,
}


def array_runtime_kind_tag(runtime_kind: ArrayRuntimeKind) -> int:
    return ARRAY_RUNTIME_KIND_TAGS[runtime_kind]


def array_runtime_kind_display_name_for_tag(kind_tag: int) -> str:
    return ARRAY_RUNTIME_KIND_DISPLAY_NAMES.get(kind_tag, "<unknown-array-kind>")


def is_direct_primitive_array_runtime_kind(runtime_kind: ArrayRuntimeKind | None) -> bool:
    return runtime_kind in DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES


def direct_primitive_array_element_size(runtime_kind: ArrayRuntimeKind) -> int:
    element_size = DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES.get(runtime_kind)
    if element_size is None:
        raise ValueError(f"unsupported direct primitive array runtime kind: {runtime_kind}")
    return element_size


__all__ = [
    "ARRAY_RUNTIME_KIND_DISPLAY_NAMES",
    "ARRAY_RUNTIME_KIND_TAGS",
    "DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES",
    "RT_ARRAY_DATA_OFFSET",
    "RT_ARRAY_ELEMENT_KIND_OFFSET",
    "RT_ARRAY_ELEMENT_SIZE_OFFSET",
    "RT_ARRAY_KIND_BOOL",
    "RT_ARRAY_KIND_DOUBLE",
    "RT_ARRAY_KIND_I64",
    "RT_ARRAY_KIND_REF",
    "RT_ARRAY_KIND_U64",
    "RT_ARRAY_KIND_U8",
    "RT_ARRAY_LEN_OFFSET",
    "RT_ARRAY_PRIMITIVE_TYPE_SYMBOL",
    "RT_ARRAY_REFERENCE_TYPE_SYMBOL",
    "RT_INTERFACE_DEBUG_NAME_OFFSET",
    "RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES",
    "RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES",
    "RT_OBJ_HEADER_SIZE_BYTES",
    "RT_OBJ_HEADER_TYPE_OFFSET",
    "RT_ROOT_FRAME_PREV_OFFSET",
    "RT_ROOT_FRAME_RESERVED_OFFSET",
    "RT_ROOT_FRAME_SIZE_BYTES",
    "RT_ROOT_FRAME_SLOT_COUNT_OFFSET",
    "RT_ROOT_FRAME_SLOTS_OFFSET",
    "RT_THREAD_STATE_ROOTS_TOP_OFFSET",
    "RT_TYPE_CLASS_VTABLE_OFFSET",
    "RT_TYPE_DEBUG_NAME_OFFSET",
    "RT_TYPE_FLAG_HAS_REFS",
    "RT_TYPE_INTERFACE_TABLES_OFFSET",
    "RT_TYPE_POINTER_OFFSETS_OFFSET",
    "RT_TYPE_SUPER_TYPE_OFFSET",
    "RT_VTABLE_ENTRY_SIZE_BYTES",
    "array_runtime_kind_display_name_for_tag",
    "array_runtime_kind_tag",
    "direct_primitive_array_element_size",
    "is_direct_primitive_array_runtime_kind",
]