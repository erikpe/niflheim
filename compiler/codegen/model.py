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
CONSTRUCTOR_OBJECT_SLOT_NAME = "__nif_ctor_obj"
TEMP_RUNTIME_ROOT_SLOT_COUNT = 6
