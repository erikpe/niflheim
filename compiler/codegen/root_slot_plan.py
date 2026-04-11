from __future__ import annotations

from compiler.codegen.model import NamedRootSlotPlan
from compiler.codegen.root_liveness import NamedRootLiveness
from compiler.semantic.symbols import LocalId


def build_named_root_slot_plan(liveness: NamedRootLiveness) -> NamedRootSlotPlan:
    live_local_id_sets = tuple(
        live_local_ids for live_local_ids in liveness.all_safepoint_live_local_id_sets() if live_local_ids
    )
    if not live_local_id_sets:
        return NamedRootSlotPlan()

    conflict_local_ids_by_local_id = _build_conflict_local_ids(live_local_id_sets)
    ordered_local_ids = _order_local_ids(conflict_local_ids_by_local_id, live_local_id_sets)

    slot_index_by_local_id: dict[LocalId, int] = {}
    slot_local_ids: list[list[LocalId]] = []
    for local_id in ordered_local_ids:
        conflicting_slot_indices = {
            slot_index_by_local_id[conflict_local_id]
            for conflict_local_id in conflict_local_ids_by_local_id[local_id]
            if conflict_local_id in slot_index_by_local_id
        }
        slot_index = _first_available_slot_index(conflicting_slot_indices, slot_count=len(slot_local_ids))
        if slot_index == len(slot_local_ids):
            slot_local_ids.append([])
        slot_index_by_local_id[local_id] = slot_index
        slot_local_ids[slot_index].append(local_id)

    return NamedRootSlotPlan(
        slot_index_by_local_id=slot_index_by_local_id,
        slot_local_ids=tuple(
            tuple(sorted(slot_local_ids_for_index, key=_local_id_sort_key)) for slot_local_ids_for_index in slot_local_ids
        ),
    )


def _build_conflict_local_ids(
    live_local_id_sets: tuple[frozenset[LocalId], ...]
) -> dict[LocalId, set[LocalId]]:
    conflict_local_ids_by_local_id = {
        local_id: set() for live_local_ids in live_local_id_sets for local_id in live_local_ids
    }
    for live_local_ids in live_local_id_sets:
        for local_id in live_local_ids:
            conflict_local_ids_by_local_id[local_id].update(
                other_local_id for other_local_id in live_local_ids if other_local_id != local_id
            )
    return conflict_local_ids_by_local_id


def _order_local_ids(
    conflict_local_ids_by_local_id: dict[LocalId, set[LocalId]],
    live_local_id_sets: tuple[frozenset[LocalId], ...],
) -> list[LocalId]:
    first_safepoint_index_by_local_id: dict[LocalId, int] = {}
    for safepoint_index, live_local_ids in enumerate(live_local_id_sets):
        for local_id in live_local_ids:
            first_safepoint_index_by_local_id.setdefault(local_id, safepoint_index)
    return sorted(
        conflict_local_ids_by_local_id,
        key=lambda local_id: (
            -len(conflict_local_ids_by_local_id[local_id]),
            first_safepoint_index_by_local_id[local_id],
            _local_id_sort_key(local_id),
        ),
    )


def _first_available_slot_index(conflicting_slot_indices: set[int], *, slot_count: int) -> int:
    for slot_index in range(slot_count):
        if slot_index not in conflicting_slot_indices:
            return slot_index
    return slot_count


def _local_id_sort_key(local_id: LocalId) -> tuple[str, int]:
    return (str(local_id.owner_id), local_id.ordinal)