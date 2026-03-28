from __future__ import annotations

from dataclasses import dataclass

from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8


ARRAY_LEN_RUNTIME_CALL = "rt_array_len"
ARRAY_FROM_BYTES_U8_RUNTIME_CALL = "rt_array_from_bytes_u8"
U64_TO_DOUBLE_RUNTIME_CALL = "rt_cast_u64_to_double"
DOUBLE_TO_I64_RUNTIME_CALL = "rt_cast_double_to_i64"
DOUBLE_TO_U64_RUNTIME_CALL = "rt_cast_double_to_u64"
DOUBLE_TO_U8_RUNTIME_CALL = "rt_cast_double_to_u8"


@dataclass(frozen=True)
class RuntimeCallMetadata:
    name: str
    ref_arg_indices: tuple[int, ...] = ()
    may_gc: bool = True
    needs_safepoint_hooks: bool | None = None

    def __post_init__(self) -> None:
        if any(index < 0 for index in self.ref_arg_indices):
            raise ValueError("Runtime call metadata cannot contain negative reference argument indices")
        if tuple(sorted(self.ref_arg_indices)) != self.ref_arg_indices:
            raise ValueError("Runtime call metadata reference argument indices must be sorted")
        if len(set(self.ref_arg_indices)) != len(self.ref_arg_indices):
            raise ValueError("Runtime call metadata reference argument indices must be unique")

    @property
    def emits_safepoint_hooks(self) -> bool:
        if self.needs_safepoint_hooks is None:
            return self.may_gc
        return self.needs_safepoint_hooks


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


def _runtime_call_metadata(
    name: str,
    *,
    ref_arg_indices: tuple[int, ...] = (),
    may_gc: bool,
    needs_safepoint_hooks: bool | None = None,
) -> RuntimeCallMetadata:
    return RuntimeCallMetadata(
        name=name,
        ref_arg_indices=ref_arg_indices,
        may_gc=may_gc,
        needs_safepoint_hooks=needs_safepoint_hooks,
    )


_RUNTIME_CALL_METADATA_BY_NAME: dict[str, RuntimeCallMetadata] = {
    ARRAY_LEN_RUNTIME_CALL: _runtime_call_metadata(ARRAY_LEN_RUNTIME_CALL, ref_arg_indices=(0,), may_gc=False),
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL: _runtime_call_metadata(ARRAY_FROM_BYTES_U8_RUNTIME_CALL, may_gc=True),
    U64_TO_DOUBLE_RUNTIME_CALL: _runtime_call_metadata(U64_TO_DOUBLE_RUNTIME_CALL, may_gc=False),
    DOUBLE_TO_I64_RUNTIME_CALL: _runtime_call_metadata(DOUBLE_TO_I64_RUNTIME_CALL, may_gc=False),
    DOUBLE_TO_U64_RUNTIME_CALL: _runtime_call_metadata(DOUBLE_TO_U64_RUNTIME_CALL, may_gc=False),
    DOUBLE_TO_U8_RUNTIME_CALL: _runtime_call_metadata(DOUBLE_TO_U8_RUNTIME_CALL, may_gc=False),
    "rt_alloc_obj": _runtime_call_metadata("rt_alloc_obj", may_gc=True),
    "rt_checked_cast": _runtime_call_metadata("rt_checked_cast", ref_arg_indices=(0,), may_gc=False),
    "rt_checked_cast_interface": _runtime_call_metadata(
        "rt_checked_cast_interface", ref_arg_indices=(0,), may_gc=False
    ),
    "rt_checked_cast_array_kind": _runtime_call_metadata(
        "rt_checked_cast_array_kind", ref_arg_indices=(0,), may_gc=False
    ),
    "rt_is_instance_of_type": _runtime_call_metadata("rt_is_instance_of_type", ref_arg_indices=(0,), may_gc=False),
    "rt_is_instance_of_interface": _runtime_call_metadata(
        "rt_is_instance_of_interface", ref_arg_indices=(0,), may_gc=False
    ),
    "rt_lookup_interface_method": _runtime_call_metadata(
        "rt_lookup_interface_method", ref_arg_indices=(0,), may_gc=False
    ),
    "rt_panic_null_term_array": _runtime_call_metadata(
        "rt_panic_null_term_array", ref_arg_indices=(0,), may_gc=False, needs_safepoint_hooks=False
    ),
    **{
        call_name: _runtime_call_metadata(call_name, may_gc=True)
        for call_name in ARRAY_CONSTRUCTOR_RUNTIME_CALLS.values()
    },
    **{
        call_name: _runtime_call_metadata(call_name, ref_arg_indices=(0,), may_gc=False)
        for call_name in ARRAY_INDEX_GET_RUNTIME_CALLS.values()
    },
    **{
        call_name: _runtime_call_metadata(
            call_name,
            ref_arg_indices=(0,) if runtime_kind is not ArrayRuntimeKind.REF else (0, 2),
            may_gc=False,
        )
        for runtime_kind, call_name in ARRAY_INDEX_SET_RUNTIME_CALLS.items()
    },
    **{
        call_name: _runtime_call_metadata(call_name, ref_arg_indices=(0,), may_gc=True)
        for call_name in ARRAY_SLICE_GET_RUNTIME_CALLS.values()
    },
    **{
        call_name: _runtime_call_metadata(
            call_name,
            ref_arg_indices=(0,) if runtime_kind is not ArrayRuntimeKind.REF else (0, 3),
            may_gc=False,
        )
        for runtime_kind, call_name in ARRAY_SLICE_SET_RUNTIME_CALLS.items()
    },
}

RUNTIME_REF_ARG_INDICES: dict[str, tuple[int, ...]] = {
    name: metadata.ref_arg_indices
    for name, metadata in _RUNTIME_CALL_METADATA_BY_NAME.items()
    if metadata.ref_arg_indices
}


def runtime_call_metadata(name: str) -> RuntimeCallMetadata:
    metadata = _RUNTIME_CALL_METADATA_BY_NAME.get(name)
    if metadata is not None:
        return metadata
    if not name.startswith("rt_"):
        raise ValueError(f"'{name}' is not a runtime call name")
    return RuntimeCallMetadata(name=name)