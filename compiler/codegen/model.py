from __future__ import annotations

from dataclasses import dataclass, field

from compiler.semantic.symbols import LocalId
from compiler.semantic.types import SemanticTypeRef


@dataclass(frozen=True)
class NamedRootSafepoint:
    node_id: int
    live_local_ids: frozenset[LocalId]


@dataclass(frozen=True)
class NamedRootSafepointSummary:
    expr_calls: tuple[NamedRootSafepoint, ...] = ()
    lvalue_calls: tuple[NamedRootSafepoint, ...] = ()
    for_in_iter_len_calls: tuple[NamedRootSafepoint, ...] = ()
    for_in_iter_get_calls: tuple[NamedRootSafepoint, ...] = ()

    def all_live_local_id_sets(self) -> tuple[frozenset[LocalId], ...]:
        return tuple(
            safepoint.live_local_ids
            for safepoint in (
                *self.expr_calls,
                *self.lvalue_calls,
                *self.for_in_iter_len_calls,
                *self.for_in_iter_get_calls,
            )
        )


@dataclass(frozen=True)
class NamedRootSlotPlan:
    slot_index_by_local_id: dict[LocalId, int] = field(default_factory=dict)
    slot_local_ids: tuple[tuple[LocalId, ...], ...] = ()

    def for_local(self, local_id: LocalId) -> int | None:
        return self.slot_index_by_local_id.get(local_id)

    @property
    def local_ids(self) -> frozenset[LocalId]:
        return frozenset(self.slot_index_by_local_id)

    @property
    def slot_count(self) -> int:
        return len(self.slot_local_ids)


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
    named_root_slot_plan: NamedRootSlotPlan
    thread_state_offset: int
    root_frame_offset: int
    stack_size: int


@dataclass(frozen=True)
class ConstructorLayout:
    class_name: str
    label: str
    init_label: str
    type_symbol: str
    payload_bytes: int
    field_names: list[str]
    param_names: list[str]
    param_field_names: list[str]
    super_param_count: int


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
FLOAT_PARAM_REGISTERS = ["xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7"]
CONSTRUCTOR_OBJECT_SLOT_NAME = "__nif_ctor_obj"
TEMP_RUNTIME_ROOT_SLOT_COUNT = 6
