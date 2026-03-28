from __future__ import annotations

from dataclasses import dataclass, field

from compiler.semantic.ir import CastExprS, LocalRefExpr, SemanticExpr, TypeTestExprS, UnaryExprS
from compiler.semantic.operations import CastSemanticsKind, UnaryOpKind
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
        compatible_type_names = self.compatible_type_names | proven_compatible_type_names(
            compatibility_index, target_type_ref
        )
        exact_type = self.exact_type
        if exact_type is None and is_exact_runtime_target(target_type_ref):
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

    def copy_local_facts(self, target_local_id: LocalId, source_local_id: LocalId) -> None:
        self.set_facts(target_local_id, self.facts_for_local(source_local_id))

    def prove_local_target(
        self, compatibility_index: TypeCompatibilityIndex, local_id: LocalId, target_type_ref: SemanticTypeRef
    ) -> bool:
        current_facts = self.facts_for_local(local_id) or TypeFacts()
        next_facts = current_facts.with_proven_target(compatibility_index, target_type_ref)
        changed = next_facts != current_facts
        self.set_facts(local_id, next_facts)
        return changed

    @classmethod
    def merge_branches(cls, *states: "NarrowState") -> "NarrowState":
        if not states:
            return cls.empty()

        shared_local_ids = set(states[0].facts_by_local_id)
        for state in states[1:]:
            shared_local_ids &= set(state.facts_by_local_id)

        merged_state = cls.empty()
        for local_id in shared_local_ids:
            merged_facts = states[0].facts_by_local_id[local_id]
            for state in states[1:]:
                merged_facts = merged_facts.intersect(state.facts_by_local_id[local_id])
            merged_state.set_facts(local_id, merged_facts)
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
    state.invalidate_local(target_local_id)
    if value is None:
        return False

    if isinstance(value, LocalRefExpr):
        state.copy_local_facts(target_local_id, value.local_id)
        return False

    successful_cast = successful_local_checked_cast(value)
    if successful_cast is None:
        return False

    source_local_id, target_type_ref = successful_cast
    source_changed = state.prove_local_target(compatibility_index, source_local_id, target_type_ref)
    target_facts = state.facts_for_local(source_local_id) or TypeFacts()
    target_facts = target_facts.with_proven_target(compatibility_index, target_type_ref)
    target_changed = target_facts != TypeFacts()
    state.set_facts(target_local_id, target_facts)
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