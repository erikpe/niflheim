from __future__ import annotations

from dataclasses import dataclass


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
class ConstructorLayout:
    class_name: str
    label: str
    type_symbol: str
    payload_bytes: int
    field_names: list[str]
    param_field_names: list[str]


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
FLOAT_PARAM_REGISTERS = ["xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"]
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
    "rt_checked_cast_interface": (0,),
    "rt_is_instance_of_type": (0,),
    "rt_is_instance_of_interface": (0,),
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
    "rt_array_set_slice_i64": (0, 3),
    "rt_array_set_slice_u64": (0, 3),
    "rt_array_set_slice_u8": (0, 3),
    "rt_array_set_slice_bool": (0, 3),
    "rt_array_set_slice_double": (0, 3),
    "rt_array_set_slice_ref": (0, 3),
    "rt_panic_null_term_array": (0,),
}
