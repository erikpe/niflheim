from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.common.span import SourceSpan
from compiler.semantic.ir import *

from .helpers.dataflow import LoopControlFlowState, solve_loop_fixed_point
from .helpers.local_usage import is_pure_expr, read_locals_expr, read_locals_lvalue
from .helpers.program_structure import rewrite_program_structure


@dataclass
class _DeadStoreStats:
    removed_var_declarations: int = 0
    removed_local_assignments: int = 0
    rewritten_effectful_statements: int = 0


def dead_store_elimination(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _DeadStoreStats()
    optimized_program = rewrite_program_structure(
        program,
        rewrite_field=lambda field: field,
        rewrite_function=lambda fn: _eliminate_function(fn, stats),
        rewrite_method=lambda method: _eliminate_method(method, stats),
    )
    logger.debugv(
        1,
        "Optimization pass dead_store_elimination removed %d var declarations, %d local assignments, rewrote %d statements to preserve side effects",
        stats.removed_var_declarations,
        stats.removed_local_assignments,
        stats.rewritten_effectful_statements,
    )
    return optimized_program


def _eliminate_function(fn: SemanticFunction, stats: _DeadStoreStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    body, _ = _eliminate_block(fn.body, set(), stats)
    return replace(fn, body=body)


def _eliminate_method(method: SemanticMethod, stats: _DeadStoreStats) -> SemanticMethod:
    body, _ = _eliminate_block(method.body, set(), stats)
    return replace(method, body=body)


def _eliminate_block(
    block: SemanticBlock,
    live_after: set[LocalId],
    stats: _DeadStoreStats,
    *,
    loop_context: LoopControlFlowState[set[LocalId]] | None = None,
) -> tuple[SemanticBlock, set[LocalId]]:
    current_live = set(live_after)
    declared_local_ids: set[LocalId] = set()
    kept_statements_reversed: list[SemanticStmt] = []

    for stmt in reversed(block.statements):
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)

        kept_stmt, current_live = _eliminate_stmt(stmt, current_live, stats, loop_context=loop_context)
        if kept_stmt is not None:
            kept_statements_reversed.append(kept_stmt)

    current_live.difference_update(declared_local_ids)
    return replace(block, statements=list(reversed(kept_statements_reversed))), current_live


def _eliminate_stmt(
    stmt: SemanticStmt,
    live_after: set[LocalId],
    stats: _DeadStoreStats,
    *,
    loop_context: LoopControlFlowState[set[LocalId]] | None = None,
) -> tuple[SemanticStmt | None, set[LocalId]]:
    if isinstance(stmt, SemanticBlock):
        return _eliminate_block(stmt, live_after, stats, loop_context=loop_context)

    if isinstance(stmt, SemanticVarDecl):
        if stmt.local_id in live_after:
            live_before = set(live_after)
            live_before.discard(stmt.local_id)
            live_before.update(read_locals_expr(stmt.initializer))
            return stmt, live_before

        stats.removed_var_declarations += 1
        replacement = _rewrite_effectful_expr_stmt(stmt.initializer, stmt.span, stats)
        live_before = set(live_after)
        if replacement is not None:
            live_before.update(read_locals_expr(replacement.expr))
        return replacement, live_before

    if isinstance(stmt, SemanticAssign):
        if isinstance(stmt.target, LocalLValue):
            if stmt.target.local_id in live_after:
                live_before = set(live_after)
                live_before.discard(stmt.target.local_id)
                live_before.update(read_locals_expr(stmt.value))
                return stmt, live_before

            stats.removed_local_assignments += 1
            replacement = _rewrite_effectful_expr_stmt(stmt.value, stmt.span, stats)
            live_before = set(live_after)
            if replacement is not None:
                live_before.update(read_locals_expr(replacement.expr))
            return replacement, live_before

        live_before = set(live_after)
        live_before.update(read_locals_lvalue(stmt.target))
        live_before.update(read_locals_expr(stmt.value))
        return stmt, live_before

    if isinstance(stmt, SemanticExprStmt):
        return stmt, set(live_after) | read_locals_expr(stmt.expr)

    if isinstance(stmt, SemanticReturn):
        return stmt, read_locals_expr(stmt.value)

    if isinstance(stmt, SemanticIf):
        then_block, then_live = _eliminate_block(stmt.then_block, live_after, stats, loop_context=loop_context)
        if stmt.else_block is None:
            else_block = None
            else_live = set(live_after)
        else:
            else_block, else_live = _eliminate_block(stmt.else_block, live_after, stats, loop_context=loop_context)
        live_before = set(then_live) | set(else_live) | read_locals_expr(stmt.condition)
        return replace(stmt, then_block=then_block, else_block=else_block), live_before

    if isinstance(stmt, SemanticWhile):
        return _eliminate_while_stmt(stmt, live_after, stats)

    if isinstance(stmt, SemanticForIn):
        return _eliminate_for_in_stmt(stmt, live_after, stats)

    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        if loop_context is None:
            return stmt, set(live_after)
        if isinstance(stmt, SemanticBreak):
            return stmt, set(loop_context.break_state)
        return stmt, set(loop_context.continue_state)

    raise TypeError(f"Unsupported semantic statement for dead store elimination: {type(stmt).__name__}")


def _eliminate_while_stmt(
    stmt: SemanticWhile, live_after: set[LocalId], stats: _DeadStoreStats
) -> tuple[SemanticWhile, set[LocalId]]:
    condition_reads = read_locals_expr(stmt.condition)

    def extend_live_set(body_live_before: set[LocalId]) -> set[LocalId]:
        return set(live_after) | condition_reads | body_live_before

    optimized_body, loop_live = _eliminate_loop_body_to_fixed_point(
        stmt.body, set(live_after) | condition_reads, extend_live_set, set(live_after), stats
    )
    live_before = set(condition_reads) | loop_live
    return replace(stmt, body=optimized_body), live_before


def _eliminate_for_in_stmt(
    stmt: SemanticForIn, live_after: set[LocalId], stats: _DeadStoreStats
) -> tuple[SemanticForIn, set[LocalId]]:
    collection_reads = read_locals_expr(stmt.collection)

    def extend_live_set(body_live_before: set[LocalId]) -> set[LocalId]:
        return set(live_after) | (body_live_before - {stmt.element_local_id})

    optimized_body, loop_live = _eliminate_loop_body_to_fixed_point(
        stmt.body, set(live_after), extend_live_set, set(live_after), stats
    )
    live_before = set(collection_reads) | loop_live
    return replace(stmt, body=optimized_body), live_before


def _eliminate_loop_body_to_fixed_point(
    body: SemanticBlock,
    initial_live_after: set[LocalId],
    extend_live_set,
    outer_live_after: set[LocalId],
    stats: _DeadStoreStats,
) -> tuple[SemanticBlock, set[LocalId]]:
    stable_loop_live_after, stable_loop_context = solve_loop_fixed_point(
        initial_state=set(initial_live_after),
        loop_exit_state=set(outer_live_after),
        next_state=lambda loop_live_after, loop_context: extend_live_set(
            _eliminate_block(body, loop_live_after, _DeadStoreStats(), loop_context=loop_context)[1]
        ),
    )
    optimized_body, _ = _eliminate_block(body, stable_loop_live_after, stats, loop_context=stable_loop_context)
    return optimized_body, stable_loop_live_after


def _rewrite_effectful_expr_stmt(
    expr: SemanticExpr | None, span: SourceSpan, stats: _DeadStoreStats
) -> SemanticExprStmt | None:
    if expr is None or is_pure_expr(expr):
        return None
    stats.rewritten_effectful_statements += 1
    return SemanticExprStmt(expr=expr, span=span)
