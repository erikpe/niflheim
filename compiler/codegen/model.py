from __future__ import annotations

from dataclasses import dataclass

from compiler.semantic.symbols import LocalId
from compiler.semantic.types import SemanticTypeRef


@dataclass(frozen=True)
class LayoutSlot:
    key: str
    display_name: str
    type_ref: SemanticTypeRef
    offset: int
    local_id: LocalId | None = None
    root_index: int | None = None
    root_offset: int | None = None


@dataclass
class FunctionLayout:
    slots: list[LayoutSlot]
    slot_names: list[str]
    slot_offsets: dict[str, int]
    local_slot_offsets: dict[LocalId, int]
    slot_type_refs: dict[str, SemanticTypeRef]
    call_scratch_slot_offsets: list[int]
    root_slots: list[LayoutSlot]
    root_slot_names: list[str]
    root_slot_indices: dict[str, int]
    root_slot_offsets: dict[str, int]
    root_slot_offsets_by_local_id: dict[LocalId, int]
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
    param_names: list[str]
    param_field_names: list[str]


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
FLOAT_PARAM_REGISTERS = ["xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"]
CONSTRUCTOR_OBJECT_SLOT_NAME = "__nif_ctor_obj"
TEMP_RUNTIME_ROOT_SLOT_COUNT = 6
