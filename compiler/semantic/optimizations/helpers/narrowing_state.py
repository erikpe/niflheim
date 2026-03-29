from __future__ import annotations

from dataclasses import dataclass, field

from compiler.semantic.ir import BinaryExprS, CastExprS, LocalRefExpr, SemanticExpr, TypeTestExprS, UnaryExprS
from compiler.semantic.operations import BinaryOpKind, CastSemanticsKind, UnaryOpKind
from compiler.semantic.symbols import LocalId
from compiler.semantic.types import SemanticTypeRef, semantic_type_canonical_name

from .type_compatibility import (
    TypeCompatibilityIndex,
    is_exact_runtime_target,
    proven_compatible_type_names,
)


@dataclass(frozen=True)
class TypeFacts:
    exact_type: SemanticTypeRef | None = None
    compatible_type_names: frozenset[str] = frozenset()

    def with_proven_target(
        self, compatibility_index: TypeCompatibilityIndex, target_type_ref: SemanticTypeRef
    ) -> "TypeFacts":
        target_type_name = semantic_type_canonical_name(target_type_ref)
        compatible_type_names = self.compatible_type_names | proven_compatible_type_names(
            compatibility_index, target_type_ref
        )
        exact_type = self.exact_type
        if is_exact_runtime_target(target_type_ref) and (
            exact_type is None or semantic_type_canonical_name(exact_type) != target_type_name
        ):
            exact_type = target_type_ref
        return TypeFacts(exact_type=exact_type, compatible_type_names=compatible_type_names)

    def intersect(self, other: "TypeFacts") -> "TypeFacts":
        exact_type = None
        if self.exact_type is not None and other.exact_type is not None:
            if semantic_type_canonical_name(self.exact_type) == semantic_type_canonical_name(other.exact_type):
                exact_type = self.exact_type
        compatible_type_names = self.compatible_type_names & other.compatible_type_names
        if exact_type is not None and semantic_type_canonical_name(exact_type) not in compatible_type_names:
            exact_type = None
        return TypeFacts(exact_type=exact_type, compatible_type_names=compatible_type_names)

    def proves(self, target_type_ref: SemanticTypeRef) -> bool:
        return semantic_type_canonical_name(target_type_ref) in self.compatible_type_names

    def is_empty(self) -> bool:
        return self.exact_type is None and not self.compatible_type_names


@dataclass
class NarrowState:
    facts_by_local_id: dict[LocalId, TypeFacts] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "NarrowState":
        return cls()

    def fork(self) -> "NarrowState":
        return NarrowState(facts_by_local_id=self.facts_by_local_id.copy())

    def facts_for_local(self, local_id: LocalId) -> TypeFacts | None:
        return self.facts_by_local_id.get(local_id)

    def set_facts(self, local_id: LocalId, facts: TypeFacts | None) -> None:
        if facts is None or facts.is_empty():
            self.facts_by_local_id.pop(local_id, None)
            return
        self.facts_by_local_id[local_id] = facts

    def invalidate_local(self, local_id: LocalId) -> None:
        self.facts_by_local_id.pop(local_id, None)

    def drop_scoped_local(self, local_id: LocalId) -> None:
        self.invalidate_local(local_id)

    def copy_local_facts(self, target_local_id: LocalId, source_local_id: LocalId) -> bool:
        current_facts = self.facts_for_local(target_local_id)
        next_facts = self.facts_for_local(source_local_id)
        changed = current_facts != next_facts
        self.set_facts(target_local_id, next_facts)
        return changed

    def prove_local_target(
        self, compatibility_index: TypeCompatibilityIndex, local_id: LocalId, target_type_ref: SemanticTypeRef
    ) -> bool:
        current_facts = self.facts_for_local(local_id) or TypeFacts()
        next_facts = current_facts.with_proven_target(compatibility_index, target_type_ref)
        changed = next_facts != current_facts
        self.set_facts(local_id, next_facts)
        return changed


@dataclass(frozen=True)
class NarrowMerge:
    invalidated_local_ids: frozenset[LocalId] = frozenset()
    fact_updates: dict[LocalId, TypeFacts] = field(default_factory=dict)

    @classmethod
    def reset(cls, state: NarrowState) -> "NarrowMerge":
        return cls(invalidated_local_ids=frozenset(state.facts_by_local_id))

    @classmethod
    def merge_branches(cls, state: NarrowState, *branch_states: NarrowState) -> "NarrowMerge":
        if not branch_states:
            return cls()

        shared_local_ids = set(branch_states[0].facts_by_local_id)
        for branch_state in branch_states[1:]:
            shared_local_ids &= set(branch_state.facts_by_local_id)

        fact_updates: dict[LocalId, TypeFacts] = {}
        for local_id in shared_local_ids:
            merged_facts = branch_states[0].facts_by_local_id[local_id]
            for branch_state in branch_states[1:]:
                merged_facts = merged_facts.intersect(branch_state.facts_by_local_id[local_id])
            if not merged_facts.is_empty():
                fact_updates[local_id] = merged_facts

        invalidated_local_ids = frozenset(
            local_id for local_id in state.facts_by_local_id if local_id not in fact_updates
        )
        return cls(invalidated_local_ids=invalidated_local_ids, fact_updates=fact_updates)

    def apply(self, state: NarrowState) -> NarrowState:
        merged_state = state.fork()
        for local_id in self.invalidated_local_ids:
            merged_state.invalidate_local(local_id)
        for local_id, facts in self.fact_updates.items():
            merged_state.set_facts(local_id, facts)
        return merged_state


@dataclass(frozen=True)
class BranchSeed:
    local_id: LocalId
    target_type_ref: SemanticTypeRef


def successful_local_checked_cast(expr: SemanticExpr) -> tuple[LocalId, SemanticTypeRef] | None:
    if not isinstance(expr, CastExprS):
        return None
    if expr.cast_kind is not CastSemanticsKind.REFERENCE_COMPATIBILITY:
        return None
    if not isinstance(expr.operand, LocalRefExpr):
        return None
    return expr.operand.local_id, expr.target_type_ref


def update_local_facts_from_value(
    state: NarrowState,
    target_local_id: LocalId,
    value: SemanticExpr | None,
    compatibility_index: TypeCompatibilityIndex,
) -> bool:
    current_target_facts = state.facts_for_local(target_local_id)
    if value is None:
        state.invalidate_local(target_local_id)
        return False

    if isinstance(value, LocalRefExpr):
        next_target_facts = state.facts_for_local(value.local_id)
        state.set_facts(target_local_id, next_target_facts)
        return next_target_facts is not None and current_target_facts != next_target_facts

    successful_cast = successful_local_checked_cast(value)
    if successful_cast is None:
        state.invalidate_local(target_local_id)
        return False

    source_local_id, target_type_ref = successful_cast
    source_facts = state.facts_for_local(source_local_id) or TypeFacts()
    next_source_facts = source_facts.with_proven_target(compatibility_index, target_type_ref)
    source_changed = next_source_facts != source_facts
    state.set_facts(source_local_id, next_source_facts)

    next_target_facts = next_source_facts.with_proven_target(compatibility_index, target_type_ref)
    target_changed = current_target_facts != next_target_facts
    state.set_facts(target_local_id, next_target_facts)
    return source_changed or target_changed


def branch_seeds_for_condition(condition: SemanticExpr) -> tuple[BranchSeed | None, BranchSeed | None]:
    if isinstance(condition, TypeTestExprS) and isinstance(condition.operand, LocalRefExpr):
        return BranchSeed(local_id=condition.operand.local_id, target_type_ref=condition.target_type_ref), None

    if (
        isinstance(condition, UnaryExprS)
        and condition.op.kind is UnaryOpKind.LOGICAL_NOT
        and isinstance(condition.operand, TypeTestExprS)
        and isinstance(condition.operand.operand, LocalRefExpr)
    ):
        return None, BranchSeed(
            local_id=condition.operand.operand.local_id,
            target_type_ref=condition.operand.target_type_ref,
        )

    return None, None


def apply_branch_seed(
    state: NarrowState,
    seed: BranchSeed | None,
    compatibility_index: TypeCompatibilityIndex,
) -> tuple[NarrowState, bool]:
    next_state = state.fork()
    if seed is None:
        return next_state, False
    return next_state, next_state.prove_local_target(compatibility_index, seed.local_id, seed.target_type_ref)


def branch_states_for_condition(
    state: NarrowState,
    condition: SemanticExpr,
    compatibility_index: TypeCompatibilityIndex,
) -> tuple[NarrowState, NarrowState, int]:
    then_seed, else_seed = branch_seeds_for_condition(condition)
    if then_seed is not None or else_seed is not None:
        then_state, then_seeded = apply_branch_seed(state, then_seed, compatibility_index)
        else_state, else_seeded = apply_branch_seed(state, else_seed, compatibility_index)
        return then_state, else_state, int(then_seeded) + int(else_seeded)

    if isinstance(condition, UnaryExprS) and condition.op.kind is UnaryOpKind.LOGICAL_NOT:
        negated_then_state, negated_else_state, seeded_count = branch_states_for_condition(
            state, condition.operand, compatibility_index
        )
        return negated_else_state, negated_then_state, seeded_count

    if isinstance(condition, BinaryExprS) and condition.op.kind is BinaryOpKind.LOGICAL_AND:
        left_then_state, left_else_state, left_seeded_count = branch_states_for_condition(
            state, condition.left, compatibility_index
        )
        right_then_state, right_else_state, right_seeded_count = branch_states_for_condition(
            left_then_state, condition.right, compatibility_index
        )
        else_state = NarrowMerge.merge_branches(state, left_else_state, right_else_state).apply(state)
        return right_then_state, else_state, left_seeded_count + right_seeded_count

    return state.fork(), state.fork(), 0