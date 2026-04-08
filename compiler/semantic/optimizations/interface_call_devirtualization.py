from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.common.collection_protocols import CollectionOpKind, array_runtime_kind_for_element_type_name
from compiler.semantic.ir import *
from compiler.semantic.types import semantic_type_array_element, semantic_type_canonical_name, semantic_type_is_array

from .helpers.interface_dispatch import build_interface_dispatch_index, resolve_implementing_method
from .helpers.narrowing_state import (
    NarrowMerge,
    NarrowState,
    branch_states_for_condition,
    exact_runtime_target_from_value,
    preserved_loop_state,
    update_local_facts_from_value,
)
from .helpers.program_structure import rewrite_program_structure
from .helpers.type_compatibility import TypeCompatibilityIndex, build_type_compatibility_index, is_exact_runtime_target


@dataclass
class _DevirtualizationStats:
    devirtualized_interface_calls: int = 0
    devirtualized_virtual_calls: int = 0
    specialized_interface_dispatches: int = 0
    specialized_virtual_dispatches: int = 0
    recovered_array_runtime_dispatches: int = 0
    skipped_non_local_receivers: int = 0
    skipped_without_exact_receiver_type: int = 0


def interface_call_devirtualization(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    compatibility_index = build_type_compatibility_index(program)
    dispatch_index = build_interface_dispatch_index(program)
    stats = _DevirtualizationStats()
    optimized_program = rewrite_program_structure(
        program,
        rewrite_field=lambda field: _rewrite_field(field, compatibility_index, dispatch_index, stats),
        rewrite_function=lambda fn: _rewrite_function(fn, compatibility_index, dispatch_index, stats),
        rewrite_method=lambda method: _rewrite_method(method, compatibility_index, dispatch_index, stats),
    )
    logger.debugv(
        1,
        "Optimization pass interface_call_devirtualization devirtualized %d interface calls, devirtualized %d virtual calls, specialized %d structural interface dispatches, specialized %d structural virtual dispatches, recovered %d array runtime dispatches, skipped %d non-local receivers, skipped %d cases without exact receiver type",
        stats.devirtualized_interface_calls,
        stats.devirtualized_virtual_calls,
        stats.specialized_interface_dispatches,
        stats.specialized_virtual_dispatches,
        stats.recovered_array_runtime_dispatches,
        stats.skipped_non_local_receivers,
        stats.skipped_without_exact_receiver_type,
    )
    return optimized_program


def _rewrite_field(
    field: SemanticField,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(
        field,
        initializer=_rewrite_expr(field.initializer, NarrowState.empty(), compatibility_index, dispatch_index, stats),
    )


def _rewrite_function(
    fn: SemanticFunction,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticFunction:
    if fn.body is None:
        return fn
    rewritten_body, _ = _rewrite_nested_block(fn.body, NarrowState.empty(), compatibility_index, dispatch_index, stats)
    return replace(fn, body=rewritten_body)


def _rewrite_method(
    method: SemanticMethod,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticMethod:
    rewritten_body, _ = _rewrite_nested_block(
        method.body,
        NarrowState.empty(),
        compatibility_index,
        dispatch_index,
        stats,
    )
    return replace(method, body=rewritten_body)


def _rewrite_nested_block(
    block: SemanticBlock,
    state: NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> tuple[SemanticBlock, NarrowState]:
    current_state = state.fork()
    declared_local_ids: set[LocalId] = set()
    rewritten_statements: list[SemanticStmt] = []

    for stmt in block.statements:
        rewritten_stmt, current_state = _rewrite_stmt(stmt, current_state, compatibility_index, dispatch_index, stats)
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)
        rewritten_statements.append(rewritten_stmt)

    for local_id in declared_local_ids:
        current_state.drop_scoped_local(local_id)

    return replace(block, statements=rewritten_statements), current_state


def _rewrite_stmt(
    stmt: SemanticStmt,
    state: NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> tuple[SemanticStmt, NarrowState]:
    if isinstance(stmt, SemanticBlock):
        return _rewrite_nested_block(stmt, state, compatibility_index, dispatch_index, stats)

    if isinstance(stmt, SemanticVarDecl):
        initializer = None
        if stmt.initializer is not None:
            initializer = _rewrite_expr(stmt.initializer, state, compatibility_index, dispatch_index, stats)
        next_state = state.fork()
        update_local_facts_from_value(next_state, stmt.local_id, initializer, compatibility_index)
        return replace(stmt, initializer=initializer), next_state

    if isinstance(stmt, SemanticAssign):
        target = _rewrite_lvalue(stmt.target, state, compatibility_index, dispatch_index, stats)
        value = _rewrite_expr(stmt.value, state, compatibility_index, dispatch_index, stats)
        next_state = state.fork()
        if isinstance(target, LocalLValue):
            update_local_facts_from_value(next_state, target.local_id, value, compatibility_index)
        return replace(stmt, target=target, value=value), next_state

    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_rewrite_expr(stmt.expr, state, compatibility_index, dispatch_index, stats)), state

    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _rewrite_expr(stmt.value, state, compatibility_index, dispatch_index, stats)
        return replace(stmt, value=value), state

    if isinstance(stmt, SemanticIf):
        rewritten_condition = _rewrite_expr(stmt.condition, state, compatibility_index, dispatch_index, stats)
        then_state, else_state, _ = branch_states_for_condition(state, rewritten_condition, compatibility_index)
        then_block, then_exit_state = _rewrite_nested_block(
            stmt.then_block,
            then_state,
            compatibility_index,
            dispatch_index,
            stats,
        )
        else_block = None
        else_exit_state = else_state
        if stmt.else_block is not None:
            else_block, else_exit_state = _rewrite_nested_block(
                stmt.else_block,
                else_state,
                compatibility_index,
                dispatch_index,
                stats,
            )

        then_exits = _block_always_exits(then_block)
        else_exits = stmt.else_block is not None and _block_always_exits(else_block)
        if then_exits and not else_exits:
            next_state = else_exit_state
        elif else_exits and not then_exits:
            next_state = then_exit_state
        else:
            next_state = NarrowMerge.merge_branches(state, then_exit_state, else_exit_state).apply(state)

        return replace(stmt, condition=rewritten_condition, then_block=then_block, else_block=else_block), next_state

    if isinstance(stmt, SemanticWhile):
        loop_state = preserved_loop_state(state, stmt.body)
        rewritten_condition = _rewrite_expr(stmt.condition, loop_state, compatibility_index, dispatch_index, stats)
        body_state, _, _ = branch_states_for_condition(loop_state, rewritten_condition, compatibility_index)
        return (
            replace(
                stmt,
                condition=rewritten_condition,
                body=_rewrite_nested_block(stmt.body, body_state, compatibility_index, dispatch_index, stats)[0],
            ),
            loop_state,
        )

    if isinstance(stmt, SemanticForIn):
        rewritten_collection = _rewrite_expr(stmt.collection, state, compatibility_index, dispatch_index, stats)
        loop_state = preserved_loop_state(state, stmt.body)
        return (
            replace(
                stmt,
                collection=rewritten_collection,
                iter_len_dispatch=_maybe_specialize_structural_dispatch(
                    stmt.iter_len_dispatch,
                    rewritten_collection,
                    CollectionOpKind.ITER_LEN,
                    state,
                    dispatch_index,
                    stats,
                ),
                iter_get_dispatch=_maybe_specialize_structural_dispatch(
                    stmt.iter_get_dispatch,
                    rewritten_collection,
                    CollectionOpKind.ITER_GET,
                    state,
                    dispatch_index,
                    stats,
                ),
                body=_rewrite_nested_block(stmt.body, loop_state, compatibility_index, dispatch_index, stats)[0],
            ),
            loop_state,
        )

    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt, state

    raise TypeError(f"Unsupported semantic statement for interface devirtualization: {type(stmt).__name__}")


def _rewrite_lvalue(
    target: SemanticLValue,
    state: NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(
            target,
            access=replace(
                target.access,
                receiver=_rewrite_expr(target.access.receiver, state, compatibility_index, dispatch_index, stats),
            ),
        )
    if isinstance(target, IndexLValue):
        rewritten_target = _rewrite_expr(target.target, state, compatibility_index, dispatch_index, stats)
        return replace(
            target,
            target=rewritten_target,
            index=_rewrite_expr(target.index, state, compatibility_index, dispatch_index, stats),
            dispatch=_maybe_specialize_structural_dispatch(
                target.dispatch,
                rewritten_target,
                CollectionOpKind.INDEX_SET,
                state,
                dispatch_index,
                stats,
            ),
        )
    if isinstance(target, SliceLValue):
        rewritten_target = _rewrite_expr(target.target, state, compatibility_index, dispatch_index, stats)
        return replace(
            target,
            target=rewritten_target,
            begin=_rewrite_expr(target.begin, state, compatibility_index, dispatch_index, stats),
            end=_rewrite_expr(target.end, state, compatibility_index, dispatch_index, stats),
            dispatch=_maybe_specialize_structural_dispatch(
                target.dispatch,
                rewritten_target,
                CollectionOpKind.SLICE_SET,
                state,
                dispatch_index,
                stats,
            ),
        )
    raise TypeError(f"Unsupported semantic lvalue for interface devirtualization: {type(target).__name__}")


def _rewrite_expr(
    expr: SemanticExpr,
    state: NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticExpr:
    if isinstance(expr, LocalRefExpr):
        return expr

    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return expr

    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _rewrite_expr(expr.receiver, state, compatibility_index, dispatch_index, stats)
        return replace(expr, receiver=receiver)

    if isinstance(expr, UnaryExprS):
        return replace(expr, operand=_rewrite_expr(expr.operand, state, compatibility_index, dispatch_index, stats))

    if isinstance(expr, BinaryExprS):
        return replace(
            expr,
            left=_rewrite_expr(expr.left, state, compatibility_index, dispatch_index, stats),
            right=_rewrite_expr(expr.right, state, compatibility_index, dispatch_index, stats),
        )

    if isinstance(expr, CastExprS):
        return replace(expr, operand=_rewrite_expr(expr.operand, state, compatibility_index, dispatch_index, stats))

    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_rewrite_expr(expr.operand, state, compatibility_index, dispatch_index, stats))

    if isinstance(expr, FieldReadExpr):
        return replace(
            expr,
            access=replace(
                expr.access,
                receiver=_rewrite_expr(expr.access.receiver, state, compatibility_index, dispatch_index, stats),
            ),
        )

    if isinstance(expr, CallExprS):
        rewritten_args = [_rewrite_expr(arg, state, compatibility_index, dispatch_index, stats) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(
                expr,
                target=replace(
                    expr.target,
                    callee=_rewrite_expr(expr.target.callee, state, compatibility_index, dispatch_index, stats),
                ),
                args=rewritten_args,
            )

        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=rewritten_args)

        rewritten_access = replace(
            access,
            receiver=_rewrite_expr(access.receiver, state, compatibility_index, dispatch_index, stats),
        )
        rewritten_target = replace(expr.target, access=rewritten_access)
        if isinstance(rewritten_target, InterfaceMethodCallTarget):
            rewritten_target = _maybe_devirtualize_call_target(
                rewritten_target,
                state,
                dispatch_index,
                stats,
            )
        elif isinstance(rewritten_target, VirtualMethodCallTarget):
            rewritten_target = _maybe_devirtualize_virtual_call_target(
                rewritten_target,
                state,
                stats,
            )
        return replace(expr, target=rewritten_target, args=rewritten_args)

    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_rewrite_expr(expr.target, state, compatibility_index, dispatch_index, stats))

    if isinstance(expr, IndexReadExpr):
        rewritten_target = _rewrite_expr(expr.target, state, compatibility_index, dispatch_index, stats)
        return replace(
            expr,
            target=rewritten_target,
            index=_rewrite_expr(expr.index, state, compatibility_index, dispatch_index, stats),
            dispatch=_maybe_specialize_structural_dispatch(
                expr.dispatch,
                rewritten_target,
                CollectionOpKind.INDEX_GET,
                state,
                dispatch_index,
                stats,
            ),
        )

    if isinstance(expr, SliceReadExpr):
        rewritten_target = _rewrite_expr(expr.target, state, compatibility_index, dispatch_index, stats)
        return replace(
            expr,
            target=rewritten_target,
            begin=_rewrite_expr(expr.begin, state, compatibility_index, dispatch_index, stats),
            end=_rewrite_expr(expr.end, state, compatibility_index, dispatch_index, stats),
            dispatch=_maybe_specialize_structural_dispatch(
                expr.dispatch,
                rewritten_target,
                CollectionOpKind.SLICE_GET,
                state,
                dispatch_index,
                stats,
            ),
        )

    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_rewrite_expr(expr.length_expr, state, compatibility_index, dispatch_index, stats))

    raise TypeError(f"Unsupported semantic expression for interface devirtualization: {type(expr).__name__}")


def _maybe_devirtualize_call_target(
    target: InterfaceMethodCallTarget,
    state: NarrowState,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticCallTarget:
    exact_type = _exact_local_receiver_type(target.access.receiver, state, stats)
    if exact_type is None or exact_type.class_id is None:
        return target

    method_id = resolve_implementing_method(dispatch_index, exact_type.class_id, target.method_id)
    if method_id is None:
        stats.skipped_without_exact_receiver_type += 1
        return target

    stats.devirtualized_interface_calls += 1
    return InstanceMethodCallTarget(
        method_id=method_id,
        access=replace(target.access, receiver_type_ref=exact_type),
    )


def _maybe_specialize_structural_dispatch(
    dispatch: SemanticDispatch,
    receiver: SemanticExpr,
    operation: CollectionOpKind,
    state: NarrowState,
    dispatch_index,
    stats: _DevirtualizationStats,
) -> SemanticDispatch:
    recovered_array_dispatch = _maybe_recover_array_runtime_dispatch(
        dispatch,
        receiver,
        operation,
        state,
        stats,
    )
    if recovered_array_dispatch is not None:
        return recovered_array_dispatch

    if not isinstance(dispatch, InterfaceDispatch):
        if not isinstance(dispatch, VirtualMethodDispatch):
            return dispatch

        exact_type = _exact_virtual_receiver_type(
            receiver,
            state,
            expected_receiver_class_id=dispatch.receiver_class_id,
            stats=stats,
        )
        if exact_type is None:
            return dispatch

        stats.specialized_virtual_dispatches += 1
        return MethodDispatch(method_id=dispatch.selected_method_id)

    exact_type = _exact_local_receiver_type(receiver, state, stats)
    if exact_type is None or exact_type.class_id is None:
        return dispatch

    method_id = resolve_implementing_method(dispatch_index, exact_type.class_id, dispatch.method_id)
    if method_id is None:
        stats.skipped_without_exact_receiver_type += 1
        return dispatch

    stats.specialized_interface_dispatches += 1
    return MethodDispatch(method_id=method_id)


def _maybe_recover_array_runtime_dispatch(
    dispatch: SemanticDispatch,
    receiver: SemanticExpr,
    operation: CollectionOpKind,
    state: NarrowState,
    stats: _DevirtualizationStats,
) -> RuntimeDispatch | None:
    exact_array_type = _exact_array_receiver_type(receiver, state)
    if exact_array_type is None:
        return None

    recovered_dispatch = _runtime_dispatch_for_exact_array(operation, exact_array_type)
    if dispatch != recovered_dispatch:
        stats.recovered_array_runtime_dispatches += 1
    return recovered_dispatch


def _maybe_devirtualize_virtual_call_target(
    target: VirtualMethodCallTarget,
    state: NarrowState,
    stats: _DevirtualizationStats,
) -> SemanticCallTarget:
    exact_type = _exact_virtual_receiver_type(
        target.access.receiver,
        state,
        expected_receiver_class_id=target.access.receiver_type_ref.class_id,
        stats=stats,
    )
    if exact_type is None:
        return target

    stats.devirtualized_virtual_calls += 1
    return InstanceMethodCallTarget(
        method_id=target.selected_method_id,
        access=replace(target.access, receiver_type_ref=exact_type),
    )


def _exact_local_receiver_type(
    receiver: SemanticExpr,
    state: NarrowState,
    stats: _DevirtualizationStats,
) -> SemanticTypeRef | None:
    exact_type, supported_shape = _resolve_exact_receiver_type(receiver, state)
    if exact_type is None:
        if supported_shape:
            stats.skipped_without_exact_receiver_type += 1
        else:
            stats.skipped_non_local_receivers += 1
        return None

    return exact_type


def _exact_array_receiver_type(receiver: SemanticExpr, state: NarrowState) -> SemanticTypeRef | None:
    exact_type, _ = _resolve_exact_receiver_type(receiver, state)
    if exact_type is not None and semantic_type_is_array(exact_type):
        return exact_type

    receiver_type_ref = expression_type_ref(receiver)
    if semantic_type_is_array(receiver_type_ref):
        return receiver_type_ref

    return None


def _resolve_exact_receiver_type(
    receiver: SemanticExpr,
    state: NarrowState,
) -> tuple[SemanticTypeRef | None, bool]:
    if isinstance(receiver, LocalRefExpr):
        receiver_facts = state.facts_for_local(receiver.local_id)
        return (None if receiver_facts is None else receiver_facts.exact_type), True

    exact_expr_type = exact_runtime_target_from_value(receiver)
    if exact_expr_type is not None:
        return exact_expr_type, True

    if isinstance(receiver, CastExprS) and receiver.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY:
        if is_exact_runtime_target(receiver.target_type_ref):
            return receiver.target_type_ref, True
        return _resolve_exact_receiver_type(receiver.operand, state)

    return None, False


def _exact_virtual_receiver_type(
    receiver: SemanticExpr,
    state: NarrowState,
    expected_receiver_class_id: ClassId | None,
    stats: _DevirtualizationStats,
) -> SemanticTypeRef | None:
    exact_type = _exact_local_receiver_type(receiver, state, stats)
    if exact_type is None or exact_type.class_id is None:
        return None
    if expected_receiver_class_id is None:
        stats.skipped_without_exact_receiver_type += 1
        return None
    if exact_type.class_id != expected_receiver_class_id:
        stats.skipped_without_exact_receiver_type += 1
        return None
    return exact_type


def _runtime_dispatch_for_exact_array(operation: CollectionOpKind, exact_array_type: SemanticTypeRef) -> RuntimeDispatch:
    if operation in {CollectionOpKind.LEN, CollectionOpKind.ITER_LEN}:
        return RuntimeDispatch(operation=operation)

    element_type_name = semantic_type_canonical_name(semantic_type_array_element(exact_array_type))
    return RuntimeDispatch(
        operation=operation,
        runtime_kind=array_runtime_kind_for_element_type_name(element_type_name),
    )


def _block_always_exits(block: SemanticBlock) -> bool:
    return any(_stmt_always_exits(stmt) for stmt in block.statements)


def _stmt_always_exits(stmt: SemanticStmt) -> bool:
    if isinstance(stmt, SemanticReturn):
        return True
    if isinstance(stmt, SemanticBlock):
        return _block_always_exits(stmt)
    if isinstance(stmt, SemanticIf):
        return stmt.else_block is not None and _block_always_exits(stmt.then_block) and _block_always_exits(stmt.else_block)
    return False