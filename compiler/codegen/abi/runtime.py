from __future__ import annotations

from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8


ARRAY_LEN_RUNTIME_CALL = "rt_array_len"
ARRAY_FROM_BYTES_U8_RUNTIME_CALL = "rt_array_from_bytes_u8"
ARRAY_CONSTRUCTOR_RUNTIME_CALLS = {
    TYPE_NAME_I64: "rt_array_new_i64",
    TYPE_NAME_U64: "rt_array_new_u64",
    TYPE_NAME_U8: "rt_array_new_u8",
    TYPE_NAME_BOOL: "rt_array_new_bool",
    TYPE_NAME_DOUBLE: "rt_array_new_double",
    "ref": "rt_array_new_ref",
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
RUNTIME_REF_ARG_INDICES: dict[str, tuple[int, ...]] = {
    "rt_checked_cast": (0,),
    "rt_checked_cast_interface": (0,),
    "rt_is_instance_of_type": (0,),
    "rt_is_instance_of_interface": (0,),
    ARRAY_LEN_RUNTIME_CALL: (0,),
    **{call_name: (0,) for call_name in ARRAY_INDEX_GET_RUNTIME_CALLS.values()},
    **{
        call_name: (0,)
        for runtime_kind, call_name in ARRAY_INDEX_SET_RUNTIME_CALLS.items()
        if runtime_kind is not ArrayRuntimeKind.REF
    },
    ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]: (0, 2),
    **{call_name: (0,) for call_name in ARRAY_SLICE_GET_RUNTIME_CALLS.values()},
    **{
        call_name: (0, 3)
        for runtime_kind, call_name in ARRAY_SLICE_SET_RUNTIME_CALLS.items()
        if runtime_kind is not ArrayRuntimeKind.REF
    },
    ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]: (0, 3),
    "rt_panic_null_term_array": (0,),
}