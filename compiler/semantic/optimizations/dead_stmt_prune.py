from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *

from .dataflow import LoopControlFlowState, solve_loop_fixed_point
from .local_usage import is_pure_expr, read_locals_expr, read_locals_lvalue


@dataclass
class _DeadStmtPruneStats:
    removed_var_declarations: int = 0
    removed_local_assignments: int = 0
    removed_expression_statements: int = 0
    rewritten_effectful_statements: int = 0


def dead_stmt_prune(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _DeadStmtPruneStats()
    pruned_program = SemanticProgram(
        entry_module=program.entry_module,
        modules={module_path: _prune_module(module, stats) for module_path, module in program.modules.items()},
    )
    logger.debugv(
        1,
        "Optimization pass dead_stmt_prune removed %d var declarations, %d local assignments, %d expression statements, rewrote %d statements to preserve side effects",
        stats.removed_var_declarations,
        stats.removed_local_assignments,
        stats.removed_expression_statements,
        stats.rewritten_effectful_statements,
    )
    return pruned_program


def _prune_module(module: SemanticModule, stats: _DeadStmtPruneStats) -> SemanticModule:
    return replace(
        module,
        classes=[_prune_class(cls, stats) for cls in module.classes],
        functions=[_prune_function(fn, stats) for fn in module.functions],
        interfaces=list(module.interfaces),
    )


def _prune_class(cls: SemanticClass, stats: _DeadStmtPruneStats) -> SemanticClass:
    return replace(
        cls,
        fields=[_prune_field(field, stats) for field in cls.fields],
        methods=[_prune_method(method, stats) for method in cls.methods],
    )


def _prune_field(field: SemanticField, stats: _DeadStmtPruneStats) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_prune_expr(field.initializer))


def _prune_function(fn: SemanticFunction, stats: _DeadStmtPruneStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    pruned_body, _ = _prune_block(fn.body, set(), stats)
    return replace(fn, body=pruned_body)


def _prune_method(method: SemanticMethod, stats: _DeadStmtPruneStats) -> SemanticMethod:
    pruned_body, _ = _prune_block(method.body, set(), stats)
    return replace(method, body=pruned_body)


def _prune_block(
    block: SemanticBlock,
    live_after: set[LocalId],
    stats: _DeadStmtPruneStats,
    *,
    loop_context: LoopControlFlowState[set[LocalId]] | None = None,
) -> tuple[SemanticBlock, set[LocalId]]:
    current_live = set(live_after)
    declared_local_ids: set[LocalId] = set()
    kept_statements_reversed: list[SemanticStmt] = []

    for stmt in reversed(block.statements):
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)

        pruned_stmt, current_live = _prune_stmt(stmt, current_live, stats, loop_context=loop_context)
        if pruned_stmt is not None:
            kept_statements_reversed.append(pruned_stmt)

    current_live.difference_update(declared_local_ids)
    return replace(block, statements=list(reversed(kept_statements_reversed))), current_live


def _prune_stmt(
    stmt: SemanticStmt,
    live_after: set[LocalId],
    stats: _DeadStmtPruneStats,
    *,
    loop_context: LoopControlFlowState[set[LocalId]] | None = None,
) -> tuple[SemanticStmt | None, set[LocalId]]:
    if isinstance(stmt, SemanticBlock):
        pruned_block, live_before = _prune_block(stmt, live_after, stats, loop_context=loop_context)
        return pruned_block, live_before

    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _prune_expr(stmt.initializer)
        if stmt.local_id in live_after:
            live_before = set(live_after)
            live_before.discard(stmt.local_id)
            if initializer is not None:
                live_before.update(read_locals_expr(initializer))
            return replace(stmt, initializer=initializer), live_before

        stats.removed_var_declarations += 1
        replacement = _rewrite_effectful_expr_stmt(initializer, stmt.span, stats)
        live_before = set(live_after)
        if replacement is not None:
            live_before.update(read_locals_expr(replacement.expr))
        return replacement, live_before

    if isinstance(stmt, SemanticAssign):
        pruned_value = _prune_expr(stmt.value)
        if isinstance(stmt.target, LocalLValue):
            if stmt.target.local_id in live_after:
                live_before = set(live_after)
                live_before.discard(stmt.target.local_id)
                live_before.update(read_locals_expr(pruned_value))
                return replace(stmt, value=pruned_value), live_before

            stats.removed_local_assignments += 1
            replacement = _rewrite_effectful_expr_stmt(pruned_value, stmt.span, stats)
            live_before = set(live_after)
            if replacement is not None:
                live_before.update(read_locals_expr(replacement.expr))
            return replacement, live_before

        pruned_target = _prune_lvalue(stmt.target)
        live_before = set(live_after)
        live_before.update(read_locals_lvalue(pruned_target))
        live_before.update(read_locals_expr(pruned_value))
        return replace(stmt, target=pruned_target, value=pruned_value), live_before

    if isinstance(stmt, SemanticExprStmt):
        pruned_expr = _prune_expr(stmt.expr)
        if is_pure_expr(pruned_expr):
            stats.removed_expression_statements += 1
            return None, set(live_after)
        live_before = set(live_after)
        live_before.update(read_locals_expr(pruned_expr))
        return replace(stmt, expr=pruned_expr), live_before

    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _prune_expr(stmt.value)
        return replace(stmt, value=value), read_locals_expr(value)

    if isinstance(stmt, SemanticIf):
        pruned_condition = _prune_expr(stmt.condition)
        then_block, then_live = _prune_block(stmt.then_block, live_after, stats, loop_context=loop_context)
        if stmt.else_block is None:
            else_block = None
            else_live = set(live_after)
        else:
            else_block, else_live = _prune_block(stmt.else_block, live_after, stats, loop_context=loop_context)

        live_before = set(then_live) | set(else_live) | read_locals_expr(pruned_condition)
        return replace(stmt, condition=pruned_condition, then_block=then_block, else_block=else_block), live_before

    if isinstance(stmt, SemanticWhile):
        return _prune_while_stmt(stmt, live_after, stats)

    if isinstance(stmt, SemanticForIn):
        return _prune_for_in_stmt(stmt, live_after, stats)

    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        if loop_context is None:
            return stmt, set(live_after)
        if isinstance(stmt, SemanticBreak):
            return stmt, set(loop_context.break_state)
        return stmt, set(loop_context.continue_state)

    raise TypeError(f"Unsupported semantic statement for dead statement pruning: {type(stmt).__name__}")


def _prune_lvalue(target: SemanticLValue) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(target, access=replace(target.access, receiver=_prune_expr(target.access.receiver)))
    if isinstance(target, IndexLValue):
        return replace(target, target=_prune_expr(target.target), index=_prune_expr(target.index))
    if isinstance(target, SliceLValue):
        return replace(
            target, target=_prune_expr(target.target), begin=_prune_expr(target.begin), end=_prune_expr(target.end)
        )
    raise TypeError(f"Unsupported semantic lvalue for dead statement pruning: {type(target).__name__}")


def _prune_expr(expr: SemanticExpr) -> SemanticExpr:
    if isinstance(expr, (LocalRefExpr, FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return expr
    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _prune_expr(expr.receiver)
        return replace(expr, receiver=receiver)
    if isinstance(expr, UnaryExprS):
        return replace(expr, operand=_prune_expr(expr.operand))
    if isinstance(expr, BinaryExprS):
        return replace(expr, left=_prune_expr(expr.left), right=_prune_expr(expr.right))
    if isinstance(expr, CastExprS):
        return replace(expr, operand=_prune_expr(expr.operand))
    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_prune_expr(expr.operand))
    if isinstance(expr, FieldReadExpr):
        return replace(expr, access=replace(expr.access, receiver=_prune_expr(expr.access.receiver)))
    if isinstance(expr, CallExprS):
        pruned_args = [_prune_expr(arg) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(expr, target=replace(expr.target, callee=_prune_expr(expr.target.callee)), args=pruned_args)
        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=pruned_args)
        return replace(
            expr,
            target=replace(expr.target, access=replace(access, receiver=_prune_expr(access.receiver))),
            args=pruned_args,
        )
    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_prune_expr(expr.target))
    if isinstance(expr, IndexReadExpr):
        return replace(expr, target=_prune_expr(expr.target), index=_prune_expr(expr.index))
    if isinstance(expr, SliceReadExpr):
        return replace(expr, target=_prune_expr(expr.target), begin=_prune_expr(expr.begin), end=_prune_expr(expr.end))
    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_prune_expr(expr.length_expr))
    raise TypeError(f"Unsupported semantic expression for dead statement pruning: {type(expr).__name__}")


def _rewrite_effectful_expr_stmt(
    expr: SemanticExpr | None, span: SourceSpan, stats: _DeadStmtPruneStats
) -> SemanticExprStmt | None:
    if expr is None or is_pure_expr(expr):
        return None
    stats.rewritten_effectful_statements += 1
    return SemanticExprStmt(expr=expr, span=span)


def _prune_while_stmt(
    stmt: SemanticWhile, live_after: set[LocalId], stats: _DeadStmtPruneStats
) -> tuple[SemanticWhile, set[LocalId]]:
    pruned_condition = _prune_expr(stmt.condition)
    condition_reads = read_locals_expr(pruned_condition)

    def extend_live_set(body_live_before: set[LocalId]) -> set[LocalId]:
        return set(live_after) | condition_reads | body_live_before

    pruned_body, loop_live = _prune_loop_body_to_fixed_point(
        stmt.body, set(live_after) | condition_reads, extend_live_set, set(live_after), stats
    )
    live_before = set(condition_reads) | loop_live
    return replace(stmt, condition=pruned_condition, body=pruned_body), live_before


def _prune_for_in_stmt(
    stmt: SemanticForIn, live_after: set[LocalId], stats: _DeadStmtPruneStats
) -> tuple[SemanticForIn, set[LocalId]]:
    pruned_collection = _prune_expr(stmt.collection)
    collection_reads = read_locals_expr(pruned_collection)

    def extend_live_set(body_live_before: set[LocalId]) -> set[LocalId]:
        return set(live_after) | (body_live_before - {stmt.element_local_id})

    pruned_body, loop_live = _prune_loop_body_to_fixed_point(
        stmt.body, set(live_after), extend_live_set, set(live_after), stats
    )
    live_before = set(collection_reads) | loop_live
    return replace(stmt, collection=pruned_collection, body=pruned_body), live_before


def _prune_loop_body_to_fixed_point(
    body: SemanticBlock,
    initial_live_after: set[LocalId],
    extend_live_set,
    outer_live_after: set[LocalId],
    stats: _DeadStmtPruneStats,
) -> tuple[SemanticBlock, set[LocalId]]:
    stable_loop_live_after, stable_loop_context = solve_loop_fixed_point(
        initial_state=set(initial_live_after),
        loop_exit_state=set(outer_live_after),
        next_state=lambda loop_live_after, loop_context: extend_live_set(
            _prune_block(body, loop_live_after, _DeadStmtPruneStats(), loop_context=loop_context)[1]
        ),
    )
    pruned_body, _ = _prune_block(body, stable_loop_live_after, stats, loop_context=stable_loop_context)
    return pruned_body, stable_loop_live_after


def _read_locals_block(block: SemanticBlock) -> set[LocalId]:
    reads: set[LocalId] = set()
    for stmt in block.statements:
        reads.update(_read_locals_stmt(stmt))
    return reads


def _read_locals_stmt(stmt: SemanticStmt) -> set[LocalId]:
    if isinstance(stmt, SemanticBlock):
        return _read_locals_block(stmt)
    if isinstance(stmt, SemanticVarDecl):
        return read_locals_expr(stmt.initializer)
    if isinstance(stmt, SemanticAssign):
        return read_locals_lvalue(stmt.target) | read_locals_expr(stmt.value)
    if isinstance(stmt, SemanticExprStmt):
        return read_locals_expr(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return read_locals_expr(stmt.value)
    if isinstance(stmt, SemanticIf):
        reads = read_locals_expr(stmt.condition) | _read_locals_block(stmt.then_block)
        if stmt.else_block is not None:
            reads |= _read_locals_block(stmt.else_block)
        return reads
    if isinstance(stmt, SemanticWhile):
        return read_locals_expr(stmt.condition) | _read_locals_block(stmt.body)
    if isinstance(stmt, SemanticForIn):
        return read_locals_expr(stmt.collection) | (_read_locals_block(stmt.body) - {stmt.element_local_id})
    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return set()
    raise TypeError(f"Unsupported semantic statement for dead statement pruning reads: {type(stmt).__name__}")
