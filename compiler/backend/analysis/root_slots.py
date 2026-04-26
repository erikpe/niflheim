from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.safepoints import BackendCallableSafepoints, analyze_callable_safepoints
from compiler.backend.ir import BackendCallableDecl, BackendFunctionAnalysisDump, BackendRegId
from compiler.backend.ir._ordering import reg_id_sort_key


@dataclass(frozen=True)
class BackendCallableRootSlots:
    callable_decl: BackendCallableDecl
    root_slot_by_reg: dict[BackendRegId, int]
    slot_reg_ids: tuple[tuple[BackendRegId, ...], ...] = ()

    def for_reg(self, reg_id: BackendRegId) -> int | None:
        return self.root_slot_by_reg.get(reg_id)

    @property
    def reg_ids(self) -> frozenset[BackendRegId]:
        return frozenset(self.root_slot_by_reg)

    @property
    def slot_count(self) -> int:
        return len(self.slot_reg_ids)

    def to_analysis_dump(self) -> BackendFunctionAnalysisDump:
        return BackendFunctionAnalysisDump(
            predecessors={},
            successors={},
            live_in={},
            live_out={},
            safepoint_live_regs={},
            root_slot_by_reg=dict(self.root_slot_by_reg),
            stack_home_by_reg={},
        )


def analyze_callable_root_slots(
    callable_decl: BackendCallableDecl,
    *,
    safepoints: BackendCallableSafepoints | None = None,
) -> BackendCallableRootSlots:
    resolved_safepoints = analyze_callable_safepoints(callable_decl) if safepoints is None else safepoints
    root_slot_by_reg, slot_reg_ids = build_root_slot_plan_from_live_reg_sets(
        resolved_safepoints.all_safepoint_live_reg_sets()
    )
    return BackendCallableRootSlots(
        callable_decl=callable_decl,
        root_slot_by_reg=root_slot_by_reg,
        slot_reg_ids=slot_reg_ids,
    )


def build_root_slot_plan_from_live_reg_sets(
    live_reg_sets: tuple[tuple[BackendRegId, ...], ...] | list[tuple[BackendRegId, ...]],
) -> tuple[dict[BackendRegId, int], tuple[tuple[BackendRegId, ...], ...]]:
    ordered_live_reg_sets = tuple(
        tuple(sorted(set(live_regs), key=reg_id_sort_key))
        for live_regs in live_reg_sets
        if live_regs
    )
    if not ordered_live_reg_sets:
        return {}, ()

    conflict_reg_ids_by_reg = _build_conflict_reg_ids(ordered_live_reg_sets)
    ordered_reg_ids = _order_reg_ids(conflict_reg_ids_by_reg, ordered_live_reg_sets)

    root_slot_by_reg: dict[BackendRegId, int] = {}
    slot_reg_lists: list[list[BackendRegId]] = []
    for reg_id in ordered_reg_ids:
        conflicting_slot_indices = {
            root_slot_by_reg[conflict_reg_id]
            for conflict_reg_id in conflict_reg_ids_by_reg[reg_id]
            if conflict_reg_id in root_slot_by_reg
        }
        slot_index = _first_available_slot_index(conflicting_slot_indices, slot_count=len(slot_reg_lists))
        if slot_index == len(slot_reg_lists):
            slot_reg_lists.append([])
        root_slot_by_reg[reg_id] = slot_index
        slot_reg_lists[slot_index].append(reg_id)

    return root_slot_by_reg, tuple(
        tuple(sorted(slot_reg_ids, key=reg_id_sort_key))
        for slot_reg_ids in slot_reg_lists
    )


def _build_conflict_reg_ids(
    live_reg_sets: tuple[tuple[BackendRegId, ...], ...],
) -> dict[BackendRegId, set[BackendRegId]]:
    conflict_reg_ids_by_reg = {
        reg_id: set() for live_regs in live_reg_sets for reg_id in live_regs
    }
    for live_regs in live_reg_sets:
        for reg_id in live_regs:
            conflict_reg_ids_by_reg[reg_id].update(
                other_reg_id for other_reg_id in live_regs if other_reg_id != reg_id
            )
    return conflict_reg_ids_by_reg


def _order_reg_ids(
    conflict_reg_ids_by_reg: dict[BackendRegId, set[BackendRegId]],
    live_reg_sets: tuple[tuple[BackendRegId, ...], ...],
) -> list[BackendRegId]:
    first_safepoint_index_by_reg: dict[BackendRegId, int] = {}
    for safepoint_index, live_regs in enumerate(live_reg_sets):
        for reg_id in live_regs:
            first_safepoint_index_by_reg.setdefault(reg_id, safepoint_index)
    return sorted(
        conflict_reg_ids_by_reg,
        key=lambda reg_id: (
            -len(conflict_reg_ids_by_reg[reg_id]),
            first_safepoint_index_by_reg[reg_id],
            reg_id_sort_key(reg_id),
        ),
    )


def _first_available_slot_index(conflicting_slot_indices: set[int], *, slot_count: int) -> int:
    for slot_index in range(slot_count):
        if slot_index not in conflicting_slot_indices:
            return slot_index
    return slot_count