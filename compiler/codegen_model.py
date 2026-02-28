from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import Expression


@dataclass
class FunctionLayout:
    slot_names: list[str]
    slot_offsets: dict[str, int]
    slot_type_names: dict[str, str]
    root_slot_names: list[str]
    root_slot_indices: dict[str, int]
    root_slot_offsets: dict[str, int]
    temp_root_slot_offsets: list[int]
    temp_root_slot_start_index: int
    root_slot_count: int
    thread_state_offset: int
    root_frame_offset: int
    stack_size: int


@dataclass(frozen=True)
class ResolvedCallTarget:
    name: str
    receiver_expr: Expression | None
    return_type_name: str


@dataclass(frozen=True)
class ConstructorLayout:
    class_name: str
    label: str
    type_symbol: str
    payload_bytes: int
    field_names: list[str]


@dataclass
class EmitContext:
    layout: FunctionLayout
    fn_name: str
    label_counter: list[int]
    method_labels: dict[tuple[str, str], str]
    method_return_types: dict[tuple[str, str], str]
    method_is_static: dict[tuple[str, str], bool]
    constructor_labels: dict[str, str]
    function_return_types: dict[str, str]
    string_literal_labels: dict[str, tuple[str, int]]
    class_field_type_names: dict[tuple[str, str], str]


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
FLOAT_PARAM_REGISTERS = ["xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"]
PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
BUILTIN_METHOD_RUNTIME_CALLS = {
}
BUILTIN_METHOD_RETURN_TYPES: dict[tuple[str, str], str] = {
}
BUILTIN_INDEX_RUNTIME_CALLS: dict[str, str] = {}
ARRAY_CONSTRUCTOR_RUNTIME_CALLS = {
    "i64": "rt_array_new_i64",
    "u64": "rt_array_new_u64",
    "u8": "rt_array_new_u8",
    "bool": "rt_array_new_bool",
    "double": "rt_array_new_double",
    "ref": "rt_array_new_ref",
}
ARRAY_GET_RUNTIME_CALLS = {
    "i64": "rt_array_get_i64",
    "u64": "rt_array_get_u64",
    "u8": "rt_array_get_u8",
    "bool": "rt_array_get_bool",
    "double": "rt_array_get_double",
    "ref": "rt_array_get_ref",
}
ARRAY_SET_RUNTIME_CALLS = {
    "i64": "rt_array_set_i64",
    "u64": "rt_array_set_u64",
    "u8": "rt_array_set_u8",
    "bool": "rt_array_set_bool",
    "double": "rt_array_set_double",
    "ref": "rt_array_set_ref",
}
ARRAY_SLICE_RUNTIME_CALLS = {
    "i64": "rt_array_slice_i64",
    "u64": "rt_array_slice_u64",
    "u8": "rt_array_slice_u8",
    "bool": "rt_array_slice_bool",
    "double": "rt_array_slice_double",
    "ref": "rt_array_slice_ref",
}
TEMP_RUNTIME_ROOT_SLOT_COUNT = 6
RUNTIME_REF_ARG_INDICES: dict[str, tuple[int, ...]] = {
    "rt_checked_cast": (0,),
    "rt_array_len": (0,),
    "rt_array_get_i64": (0,),
    "rt_array_get_u64": (0,),
    "rt_array_get_u8": (0,),
    "rt_array_get_bool": (0,),
    "rt_array_get_double": (0,),
    "rt_array_get_ref": (0,),
    "rt_array_set_i64": (0,),
    "rt_array_set_u64": (0,),
    "rt_array_set_u8": (0,),
    "rt_array_set_bool": (0,),
    "rt_array_set_double": (0,),
    "rt_array_set_ref": (0, 2),
    "rt_array_slice_i64": (0,),
    "rt_array_slice_u64": (0,),
    "rt_array_slice_u8": (0,),
    "rt_array_slice_bool": (0,),
    "rt_array_slice_double": (0,),
    "rt_array_slice_ref": (0,),
    "rt_strbuf_reserve": (0,),
    "rt_strbuf_len": (0,),
    "rt_strbuf_get_u8": (0,),
    "rt_strbuf_set_u8": (0,),
    "rt_strbuf_to_str": (0,),
}
RUNTIME_RETURN_TYPES: dict[str, str] = {
    "rt_array_len": "u64",
    "rt_array_get_i64": "i64",
    "rt_array_get_u64": "u64",
    "rt_array_get_u8": "u8",
    "rt_array_get_bool": "bool",
    "rt_array_get_double": "double",
    "rt_array_get_ref": "Obj",
    "rt_checked_cast": "Obj",
    "rt_panic_str": "unit",
}
