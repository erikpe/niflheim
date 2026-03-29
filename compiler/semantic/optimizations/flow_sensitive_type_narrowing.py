from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *
from compiler.semantic.operations import CastSemanticsKind

from .helpers.program_structure import rewrite_program_structure
from .helpers.narrowing_state import (
    NarrowMerge as _NarrowMerge,
    NarrowState as _NarrowState,
    apply_branch_seed,
    branch_seeds_for_condition,
    update_local_facts_from_value,
)
from .helpers.type_compatibility import (
    TypeCompatibilityIndex,
    build_type_compatibility_index,
)


@dataclass
class _NarrowingStats:
    removed_checked_casts: int = 0
    folded_type_tests: int = 0
    seeded_branch_facts: int = 0
    seeded_cast_facts: int = 0


def flow_sensitive_type_narrowing(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    compatibility_index = build_type_compatibility_index(program)
    stats = _NarrowingStats()
    optimized_program = rewrite_program_structure(
        program,
        rewrite_field=lambda field: _narrow_field(field, compatibility_index, stats),
        rewrite_function=lambda fn: _narrow_function(fn, compatibility_index, stats),
        rewrite_method=lambda method: _narrow_method(method, compatibility_index, stats),
    )
    logger.debugv(
        1,
        "Optimization pass flow_sensitive_type_narrowing removed %d checked casts, folded %d type tests, seeded %d branch facts, seeded %d cast facts",
        stats.removed_checked_casts,
        stats.folded_type_tests,
        stats.seeded_branch_facts,
        stats.seeded_cast_facts,
    )
    return optimized_program


def _narrow_field(
    field: SemanticField, compatibility_index: TypeCompatibilityIndex, stats: _NarrowingStats
) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_rewrite_expr(field.initializer, _NarrowState.empty(), compatibility_index, stats))


def _narrow_function(
    fn: SemanticFunction, compatibility_index: TypeCompatibilityIndex, stats: _NarrowingStats
) -> SemanticFunction:
    if fn.body is None:
        return fn
    narrowed_body, _ = _rewrite_nested_block(fn.body, _NarrowState.empty(), compatibility_index, stats)
    return replace(fn, body=narrowed_body)


def _narrow_method(
    method: SemanticMethod, compatibility_index: TypeCompatibilityIndex, stats: _NarrowingStats
) -> SemanticMethod:
    narrowed_body, _ = _rewrite_nested_block(method.body, _NarrowState.empty(), compatibility_index, stats)
    return replace(method, body=narrowed_body)


def _rewrite_nested_block(
    block: SemanticBlock,
    state: _NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    stats: _NarrowingStats,
) -> tuple[SemanticBlock, _NarrowState]:
    current_state = state.fork()
    declared_local_ids: set[LocalId] = set()
    rewritten_statements: list[SemanticStmt] = []

    for stmt in block.statements:
        rewritten_stmt, current_state = _rewrite_stmt(stmt, current_state, compatibility_index, stats)
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)
        rewritten_statements.append(rewritten_stmt)

    for local_id in declared_local_ids:
        current_state.drop_scoped_local(local_id)

    return replace(block, statements=rewritten_statements), current_state


def _rewrite_stmt(
    stmt: SemanticStmt,
    state: _NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    stats: _NarrowingStats,
) -> tuple[SemanticStmt, _NarrowState]:
    if isinstance(stmt, SemanticBlock):
        return _rewrite_nested_block(stmt, state, compatibility_index, stats)

    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _rewrite_expr(stmt.initializer, state, compatibility_index, stats)
        next_state = state.fork()
        if update_local_facts_from_value(
            next_state,
            stmt.local_id,
            initializer,
            compatibility_index,
        ):
            stats.seeded_cast_facts += 1
        return replace(stmt, initializer=initializer), next_state

    if isinstance(stmt, SemanticAssign):
        target = _rewrite_lvalue(stmt.target, state, compatibility_index, stats)
        value = _rewrite_expr(stmt.value, state, compatibility_index, stats)
        next_state = state.fork()
        if isinstance(target, LocalLValue):
            if update_local_facts_from_value(next_state, target.local_id, value, compatibility_index):
                stats.seeded_cast_facts += 1
        return replace(stmt, target=target, value=value), next_state

    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_rewrite_expr(stmt.expr, state, compatibility_index, stats)), state

    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _rewrite_expr(stmt.value, state, compatibility_index, stats)
        return replace(stmt, value=value), state

    if isinstance(stmt, SemanticIf):
        rewritten_condition = _rewrite_expr(stmt.condition, state, compatibility_index, stats)
        then_seed, else_seed = branch_seeds_for_condition(rewritten_condition)
        then_state, then_seeded = apply_branch_seed(state, then_seed, compatibility_index)
        else_state, else_seeded = apply_branch_seed(state, else_seed, compatibility_index)
        stats.seeded_branch_facts += int(then_seeded) + int(else_seeded)
        then_block, then_exit_state = _rewrite_nested_block(stmt.then_block, then_state, compatibility_index, stats)
        else_block = None
        else_exit_state = else_state
        if stmt.else_block is not None:
            else_block, else_exit_state = _rewrite_nested_block(stmt.else_block, else_state, compatibility_index, stats)

        then_exits = _block_always_exits(then_block)
        else_exits = stmt.else_block is not None and _block_always_exits(else_block)
        if then_exits and not else_exits:
            next_state = else_exit_state
        elif else_exits and not then_exits:
            next_state = then_exit_state
        else:
            next_state = _NarrowMerge.merge_branches(state, then_exit_state, else_exit_state).apply(state)

        return (
            replace(stmt, condition=rewritten_condition, then_block=then_block, else_block=else_block),
            next_state,
        )

    if isinstance(stmt, SemanticWhile):
        return (
            replace(
                stmt,
                condition=_rewrite_expr(stmt.condition, _NarrowState.empty(), compatibility_index, stats),
                body=_rewrite_nested_block(stmt.body, _NarrowState.empty(), compatibility_index, stats)[0],
            ),
            _NarrowMerge.reset(state).apply(state),
        )

    if isinstance(stmt, SemanticForIn):
        return (
            replace(
                stmt,
                collection=_rewrite_expr(stmt.collection, state, compatibility_index, stats),
                body=_rewrite_nested_block(stmt.body, _NarrowState.empty(), compatibility_index, stats)[0],
            ),
            _NarrowMerge.reset(state).apply(state),
        )

    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt, state

    raise TypeError(f"Unsupported semantic statement for flow-sensitive narrowing: {type(stmt).__name__}")


def _rewrite_lvalue(
    target: SemanticLValue,
    state: _NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    stats: _NarrowingStats,
) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(
            target,
            access=replace(target.access, receiver=_rewrite_expr(target.access.receiver, state, compatibility_index, stats)),
        )
    if isinstance(target, IndexLValue):
        return replace(
            target,
            target=_rewrite_expr(target.target, state, compatibility_index, stats),
            index=_rewrite_expr(target.index, state, compatibility_index, stats),
        )
    if isinstance(target, SliceLValue):
        return replace(
            target,
            target=_rewrite_expr(target.target, state, compatibility_index, stats),
            begin=_rewrite_expr(target.begin, state, compatibility_index, stats),
            end=_rewrite_expr(target.end, state, compatibility_index, stats),
        )
    raise TypeError(f"Unsupported semantic lvalue for flow-sensitive narrowing: {type(target).__name__}")


def _rewrite_expr(
    expr: SemanticExpr,
    state: _NarrowState,
    compatibility_index: TypeCompatibilityIndex,
    stats: _NarrowingStats,
) -> SemanticExpr:
    if isinstance(expr, LocalRefExpr):
        return expr

    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return expr

    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _rewrite_expr(expr.receiver, state, compatibility_index, stats)
        return replace(expr, receiver=receiver)

    if isinstance(expr, UnaryExprS):
        return replace(expr, operand=_rewrite_expr(expr.operand, state, compatibility_index, stats))

    if isinstance(expr, BinaryExprS):
        return replace(
            expr,
            left=_rewrite_expr(expr.left, state, compatibility_index, stats),
            right=_rewrite_expr(expr.right, state, compatibility_index, stats),
        )

    if isinstance(expr, CastExprS):
        rewritten_operand = _rewrite_expr(expr.operand, state, compatibility_index, stats)
        rewritten_expr = replace(expr, operand=rewritten_operand)
        if (
            rewritten_expr.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY
            and isinstance(rewritten_expr.operand, LocalRefExpr)
        ):
            local_facts = state.facts_for_local(rewritten_expr.operand.local_id)
            if local_facts is not None and local_facts.proves(rewritten_expr.target_type_ref):
                stats.removed_checked_casts += 1
                return replace(rewritten_expr.operand, type_ref=rewritten_expr.type_ref, span=rewritten_expr.span)
        return rewritten_expr

    if isinstance(expr, TypeTestExprS):
        rewritten_operand = _rewrite_expr(expr.operand, state, compatibility_index, stats)
        rewritten_expr = replace(expr, operand=rewritten_operand)
        if isinstance(rewritten_expr.operand, LocalRefExpr):
            local_facts = state.facts_for_local(rewritten_expr.operand.local_id)
            if local_facts is not None and local_facts.proves(rewritten_expr.target_type_ref):
                stats.folded_type_tests += 1
                return LiteralExprS(constant=BoolConstant(True), type_ref=rewritten_expr.type_ref, span=rewritten_expr.span)
        return rewritten_expr

    if isinstance(expr, FieldReadExpr):
        return replace(
            expr,
            access=replace(expr.access, receiver=_rewrite_expr(expr.access.receiver, state, compatibility_index, stats)),
        )

    if isinstance(expr, CallExprS):
        rewritten_args = [_rewrite_expr(arg, state, compatibility_index, stats) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(
                expr,
                target=replace(expr.target, callee=_rewrite_expr(expr.target.callee, state, compatibility_index, stats)),
                args=rewritten_args,
            )
        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=rewritten_args)
        return replace(
            expr,
            target=replace(
                expr.target,
                access=replace(access, receiver=_rewrite_expr(access.receiver, state, compatibility_index, stats)),
            ),
            args=rewritten_args,
        )

    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_rewrite_expr(expr.target, state, compatibility_index, stats))

    if isinstance(expr, IndexReadExpr):
        return replace(
            expr,
            target=_rewrite_expr(expr.target, state, compatibility_index, stats),
            index=_rewrite_expr(expr.index, state, compatibility_index, stats),
        )

    if isinstance(expr, SliceReadExpr):
        return replace(
            expr,
            target=_rewrite_expr(expr.target, state, compatibility_index, stats),
            begin=_rewrite_expr(expr.begin, state, compatibility_index, stats),
            end=_rewrite_expr(expr.end, state, compatibility_index, stats),
        )

    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_rewrite_expr(expr.length_expr, state, compatibility_index, stats))

    raise TypeError(f"Unsupported semantic expression for flow-sensitive narrowing: {type(expr).__name__}")


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
