from __future__ import annotations

from compiler.common.collection_protocols import ArrayRuntimeKind


ARRAY_FROM_BYTES_U8_RUNTIME_CALL = "rt_array_from_bytes_u8"
ARRAY_LEN_RUNTIME_CALL = "rt_array_len"

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


__all__ = [
    "ARRAY_CONSTRUCTOR_RUNTIME_CALLS",
    "ARRAY_FROM_BYTES_U8_RUNTIME_CALL",
    "ARRAY_INDEX_GET_RUNTIME_CALLS",
    "ARRAY_INDEX_SET_RUNTIME_CALLS",
    "ARRAY_LEN_RUNTIME_CALL",
    "ARRAY_SLICE_GET_RUNTIME_CALLS",
    "ARRAY_SLICE_SET_RUNTIME_CALLS",
]