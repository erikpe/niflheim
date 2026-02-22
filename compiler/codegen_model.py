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


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
FLOAT_PARAM_REGISTERS = ["xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"]
PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
BOX_CONSTRUCTOR_RUNTIME_CALLS = {
    "BoxI64": "rt_box_i64_new",
    "BoxU64": "rt_box_u64_new",
    "BoxU8": "rt_box_u8_new",
    "BoxBool": "rt_box_bool_new",
    "BoxDouble": "rt_box_double_new",
}
BUILTIN_CONSTRUCTOR_RUNTIME_CALLS = {
    "Vec": "rt_vec_new",
    **BOX_CONSTRUCTOR_RUNTIME_CALLS,
}
BOX_VALUE_GETTER_RUNTIME_CALLS = {
    "BoxI64": "rt_box_i64_get",
    "BoxU64": "rt_box_u64_get",
    "BoxU8": "rt_box_u8_get",
    "BoxBool": "rt_box_bool_get",
    "BoxDouble": "rt_box_double_get",
}
BUILTIN_METHOD_RUNTIME_CALLS = {
    ("Vec", "len"): "rt_vec_len",
    ("Vec", "push"): "rt_vec_push",
    ("Vec", "get"): "rt_vec_get",
    ("Vec", "set"): "rt_vec_set",
}
BUILTIN_METHOD_RETURN_TYPES: dict[tuple[str, str], str] = {
    ("Vec", "len"): "i64",
    ("Vec", "push"): "unit",
    ("Vec", "get"): "Obj",
    ("Vec", "set"): "unit",
}
BUILTIN_INDEX_RUNTIME_CALLS = {
    "Vec": "rt_vec_get",
}
TEMP_RUNTIME_ROOT_SLOT_COUNT = 6
RUNTIME_REF_ARG_INDICES: dict[str, tuple[int, ...]] = {
    "rt_checked_cast": (0,),
    "rt_box_i64_get": (0,),
    "rt_box_u64_get": (0,),
    "rt_box_u8_get": (0,),
    "rt_box_bool_get": (0,),
    "rt_box_double_get": (0,),
    "rt_vec_len": (0,),
    "rt_vec_get": (0,),
    "rt_vec_push": (0, 1),
    "rt_vec_set": (0, 2),
}
BUILTIN_RUNTIME_TYPE_SYMBOLS: dict[str, str] = {
    "Vec": "rt_type_vec_desc",
    "BoxI64": "rt_type_box_i64_desc",
    "BoxU64": "rt_type_box_u64_desc",
    "BoxU8": "rt_type_box_u8_desc",
    "BoxBool": "rt_type_box_bool_desc",
    "BoxDouble": "rt_type_box_double_desc",
}
RUNTIME_RETURN_TYPES: dict[str, str] = {
    "rt_box_double_get": "double",
    "rt_box_i64_get": "i64",
    "rt_box_u64_get": "u64",
    "rt_box_u8_get": "u8",
    "rt_box_bool_get": "bool",
    "rt_vec_len": "i64",
    "rt_vec_get": "Obj",
    "rt_vec_new": "Vec",
    "rt_checked_cast": "Obj",
    "rt_panic_str": "unit",
}
