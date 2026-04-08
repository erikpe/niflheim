from __future__ import annotations

from compiler.common.span import SourcePos, SourceSpan
from compiler.semantic.ir import (
    ArrayCtorExprS,
    BinaryExprS,
    CallExprS,
    CastExprS,
    ConstructorCallTarget,
    IntConstant,
    LiteralExprS,
    LocalRefExpr,
    TypeTestExprS,
    UnaryExprS,
)
from compiler.semantic.operations import (
    BinaryOpFlavor,
    BinaryOpKind,
    CastSemanticsKind,
    SemanticBinaryOp,
    SemanticUnaryOp,
    TypeTestSemanticsKind,
    UnaryOpFlavor,
    UnaryOpKind,
)
from compiler.semantic.optimizations.helpers.narrowing_state import (
    NarrowMerge,
    NarrowState,
    TypeFacts,
    apply_branch_seed,
    branch_states_for_condition,
    branch_seeds_for_condition,
    update_local_facts_from_value,
)
from compiler.semantic.optimizations.helpers.type_compatibility import TypeCompatibilityIndex
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, LocalId
from compiler.semantic.types import (
    semantic_array_type_ref,
    semantic_primitive_type_ref,
    semantic_type_ref_for_class_id,
    semantic_type_ref_for_interface_id,
    semantic_type_ref_from_type_info,
)
from compiler.typecheck.model import TypeInfo


def _span() -> SourceSpan:
    start = SourcePos(path="test.nif", offset=0, line=1, column=1)
    end = SourcePos(path="test.nif", offset=0, line=1, column=1)
    return SourceSpan(start=start, end=end)


def _local_id(ordinal: int) -> LocalId:
    return LocalId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=ordinal)


def _compatibility_index() -> TypeCompatibilityIndex:
    return TypeCompatibilityIndex(
        implemented_interfaces_by_class_id={
            ClassId(module_path=("main",), name="Key"): frozenset(
                {InterfaceId(module_path=("main",), name="Hashable")}
            )
        }
    )


def _obj_type_ref():
    return semantic_type_ref_from_type_info(("main",), TypeInfo(name="Obj", kind="reference"))


def test_type_facts_retain_exact_class_when_proving_interface_compatibility() -> None:
    compatibility_index = _compatibility_index()
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    facts = TypeFacts().with_proven_target(compatibility_index, key_type_ref)
    facts = facts.with_proven_target(compatibility_index, hashable_type_ref)

    assert facts.exact_type == key_type_ref
    assert facts.proves(key_type_ref)
    assert facts.proves(hashable_type_ref)


def test_narrow_state_merge_keeps_only_shared_branch_facts() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    exact_state = NarrowState.empty()
    exact_state.prove_local_target(compatibility_index, local_id, key_type_ref)

    compatible_state = NarrowState.empty()
    compatible_state.prove_local_target(compatibility_index, local_id, hashable_type_ref)

    merged_state = NarrowMerge.merge_branches(NarrowState.empty(), exact_state, compatible_state).apply(NarrowState.empty())
    merged_facts = merged_state.facts_for_local(local_id)

    assert merged_facts is not None
    assert merged_facts.exact_type is None
    assert merged_facts.proves(hashable_type_ref)
    assert merged_facts.proves(key_type_ref) is False


def test_update_local_facts_from_value_invalidates_facts_after_non_narrowing_reassignment() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, local_id, key_type_ref)

    changed = update_local_facts_from_value(
        state,
        local_id,
        LocalRefExpr(local_id=_local_id(1), type_ref=_obj_type_ref(), span=_span()),
        compatibility_index,
    )

    assert changed is False
    assert state.facts_for_local(local_id) is None


def test_update_local_facts_from_value_reports_change_when_copying_existing_facts() -> None:
    compatibility_index = _compatibility_index()
    source_local_id = _local_id(0)
    target_local_id = _local_id(1)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, source_local_id, key_type_ref)

    changed = update_local_facts_from_value(
        state,
        target_local_id,
        LocalRefExpr(local_id=source_local_id, type_ref=_obj_type_ref(), span=_span()),
        compatibility_index,
    )

    assert changed is True
    assert state.facts_for_local(target_local_id) == state.facts_for_local(source_local_id)


def test_update_local_facts_from_value_seeds_exact_class_facts_from_constructor_call() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_class_id = ClassId(module_path=("main",), name="Key")
    key_type_ref = semantic_type_ref_for_class_id(key_class_id)
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    changed = update_local_facts_from_value(
        state := NarrowState.empty(),
        local_id,
        CallExprS(
            target=ConstructorCallTarget(
                constructor_id=ConstructorId(module_path=key_class_id.module_path, class_name=key_class_id.name)
            ),
            args=[],
            type_ref=key_type_ref,
            span=_span(),
        ),
        compatibility_index,
    )

    facts = state.facts_for_local(local_id)

    assert changed is True
    assert facts is not None
    assert facts.exact_type == key_type_ref
    assert facts.proves(key_type_ref)
    assert facts.proves(hashable_type_ref)


def test_update_local_facts_from_value_seeds_exact_array_facts_from_array_constructor() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    element_type_ref = semantic_primitive_type_ref("i64")
    array_type_ref = semantic_array_type_ref(element_type_ref)

    changed = update_local_facts_from_value(
        state := NarrowState.empty(),
        local_id,
        ArrayCtorExprS(
            element_type_ref=element_type_ref,
            length_expr=LiteralExprS(
                constant=IntConstant(1),
                type_ref=semantic_primitive_type_ref("u64"),
                span=_span(),
            ),
            type_ref=array_type_ref,
            span=_span(),
        ),
        compatibility_index,
    )

    facts = state.facts_for_local(local_id)

    assert changed is True
    assert facts is not None
    assert facts.exact_type == array_type_ref
    assert facts.proves(array_type_ref)


def test_update_local_facts_from_value_preserves_constructor_seeded_facts_across_local_copy() -> None:
    compatibility_index = _compatibility_index()
    source_local_id = _local_id(0)
    target_local_id = _local_id(1)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    update_local_facts_from_value(
        state,
        source_local_id,
        CallExprS(
            target=ConstructorCallTarget(constructor_id=ConstructorId(module_path=("main",), class_name="Key")),
            args=[],
            type_ref=key_type_ref,
            span=_span(),
        ),
        compatibility_index,
    )

    changed = update_local_facts_from_value(
        state,
        target_local_id,
        LocalRefExpr(local_id=source_local_id, type_ref=_obj_type_ref(), span=_span()),
        compatibility_index,
    )

    assert changed is True
    assert state.facts_for_local(target_local_id) == state.facts_for_local(source_local_id)


def test_update_local_facts_from_value_preserves_facts_on_self_copy_assignment() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, local_id, key_type_ref)

    changed = update_local_facts_from_value(
        state,
        local_id,
        LocalRefExpr(local_id=local_id, type_ref=_obj_type_ref(), span=_span()),
        compatibility_index,
    )

    assert changed is False
    assert state.facts_for_local(local_id) is not None
    assert state.facts_for_local(local_id).proves(key_type_ref)


def test_update_local_facts_from_value_seeds_source_and_target_from_successful_cast() -> None:
    compatibility_index = _compatibility_index()
    source_local_id = _local_id(0)
    target_local_id = _local_id(1)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    changed = update_local_facts_from_value(
        state,
        target_local_id,
        CastExprS(
            operand=LocalRefExpr(local_id=source_local_id, type_ref=_obj_type_ref(), span=_span()),
            cast_kind=CastSemanticsKind.REFERENCE_COMPATIBILITY,
            target_type_ref=key_type_ref,
            type_ref=key_type_ref,
            span=_span(),
        ),
        compatibility_index,
    )

    assert changed is True
    assert state.facts_for_local(source_local_id) is not None
    assert state.facts_for_local(source_local_id).proves(key_type_ref)
    assert state.facts_for_local(target_local_id) is not None
    assert state.facts_for_local(target_local_id).proves(key_type_ref)


def test_update_local_facts_from_value_reports_no_change_when_successful_cast_facts_already_exist() -> None:
    compatibility_index = _compatibility_index()
    source_local_id = _local_id(0)
    target_local_id = _local_id(1)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, source_local_id, key_type_ref)
    state.prove_local_target(compatibility_index, target_local_id, key_type_ref)

    changed = update_local_facts_from_value(
        state,
        target_local_id,
        CastExprS(
            operand=LocalRefExpr(local_id=source_local_id, type_ref=_obj_type_ref(), span=_span()),
            cast_kind=CastSemanticsKind.REFERENCE_COMPATIBILITY,
            target_type_ref=key_type_ref,
            type_ref=key_type_ref,
            span=_span(),
        ),
        compatibility_index,
    )

    assert changed is False


def test_narrow_state_drop_scoped_local_removes_local_facts() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, local_id, key_type_ref)
    state.drop_scoped_local(local_id)

    assert state.facts_for_local(local_id) is None


def test_type_facts_replace_exact_type_when_later_exact_proof_is_more_specific() -> None:
    compatibility_index = _compatibility_index()
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    obj_array_type_ref = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Obj[]", kind="reference", element_type=TypeInfo(name="Obj", kind="reference")))

    facts = TypeFacts().with_proven_target(compatibility_index, key_type_ref)
    facts = facts.with_proven_target(compatibility_index, obj_array_type_ref)

    assert facts.exact_type == obj_array_type_ref
    assert facts.proves(key_type_ref)
    assert facts.proves(obj_array_type_ref)


def test_narrow_merge_reset_clears_all_known_local_facts() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))

    state = NarrowState.empty()
    state.prove_local_target(compatibility_index, local_id, key_type_ref)

    reset_state = NarrowMerge.reset(state).apply(state)

    assert reset_state.facts_for_local(local_id) is None


def test_branch_seeds_for_condition_extracts_positive_and_negated_type_tests() -> None:
    local_id = _local_id(0)
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))
    bool_type_ref = semantic_primitive_type_ref("bool")
    positive_condition = TypeTestExprS(
        operand=LocalRefExpr(local_id=local_id, type_ref=_obj_type_ref(), span=_span()),
        test_kind=TypeTestSemanticsKind.INTERFACE_COMPATIBILITY,
        target_type_ref=hashable_type_ref,
        type_ref=bool_type_ref,
        span=_span(),
    )
    negated_condition = UnaryExprS(
        op=SemanticUnaryOp(kind=UnaryOpKind.LOGICAL_NOT, flavor=UnaryOpFlavor.BOOL),
        operand=positive_condition,
        type_ref=bool_type_ref,
        span=_span(),
    )

    then_seed, else_seed = branch_seeds_for_condition(positive_condition)
    negated_then_seed, negated_else_seed = branch_seeds_for_condition(negated_condition)

    assert then_seed is not None
    assert then_seed.local_id == local_id
    assert then_seed.target_type_ref == hashable_type_ref
    assert else_seed is None
    assert negated_then_seed is None
    assert negated_else_seed is not None
    assert negated_else_seed.local_id == local_id
    assert negated_else_seed.target_type_ref == hashable_type_ref


def test_apply_branch_seed_seeds_state_when_fact_is_new() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))
    condition = TypeTestExprS(
        operand=LocalRefExpr(local_id=local_id, type_ref=_obj_type_ref(), span=_span()),
        test_kind=TypeTestSemanticsKind.INTERFACE_COMPATIBILITY,
        target_type_ref=hashable_type_ref,
        type_ref=semantic_primitive_type_ref("bool"),
        span=_span(),
    )

    state, changed = apply_branch_seed(NarrowState.empty(), branch_seeds_for_condition(condition)[0], compatibility_index)

    assert changed is True
    assert state.facts_for_local(local_id) is not None
    assert state.facts_for_local(local_id).proves(hashable_type_ref)


def test_branch_states_for_logical_and_seed_then_branch_and_keep_else_conservative() -> None:
    compatibility_index = _compatibility_index()
    local_id = _local_id(0)
    flag_local_id = _local_id(1)
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))
    bool_type_ref = semantic_primitive_type_ref("bool")
    condition = BinaryExprS(
        op=SemanticBinaryOp(kind=BinaryOpKind.LOGICAL_AND, flavor=BinaryOpFlavor.BOOL_LOGICAL),
        left=TypeTestExprS(
            operand=LocalRefExpr(local_id=local_id, type_ref=_obj_type_ref(), span=_span()),
            test_kind=TypeTestSemanticsKind.INTERFACE_COMPATIBILITY,
            target_type_ref=hashable_type_ref,
            type_ref=bool_type_ref,
            span=_span(),
        ),
        right=LocalRefExpr(local_id=flag_local_id, type_ref=bool_type_ref, span=_span()),
        type_ref=bool_type_ref,
        span=_span(),
    )

    then_state, else_state, seeded_count = branch_states_for_condition(
        NarrowState.empty(), condition, compatibility_index
    )

    assert seeded_count == 1
    assert then_state.facts_for_local(local_id) is not None
    assert then_state.facts_for_local(local_id).proves(hashable_type_ref)
    assert else_state.facts_for_local(local_id) is None