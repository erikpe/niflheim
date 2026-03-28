from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *


@dataclass
class _SimplifyStats:
    simplified_conditionals: int = 0
    removed_while_loops: int = 0
    pruned_unreachable_statements: int = 0


def simplify_control_flow(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _SimplifyStats()
    simplified_program = SemanticProgram(
        entry_module=program.entry_module,
        modules={module_path: _simplify_module(module, stats) for module_path, module in program.modules.items()},
    )
    logger.debugv(
        1,
        "Optimization pass simplify_control_flow simplified %d conditionals, removed %d while loops, pruned %d unreachable statements",
        stats.simplified_conditionals,
        stats.removed_while_loops,
        stats.pruned_unreachable_statements,
    )
    return simplified_program


def _simplify_module(module: SemanticModule, stats: _SimplifyStats) -> SemanticModule:
    return replace(
        module,
        classes=[_simplify_class(cls, stats) for cls in module.classes],
        functions=[_simplify_function(fn, stats) for fn in module.functions],
        interfaces=list(module.interfaces),
    )


def _simplify_class(cls: SemanticClass, stats: _SimplifyStats) -> SemanticClass:
    return replace(cls, fields=list(cls.fields), methods=[_simplify_method(method, stats) for method in cls.methods])


def _simplify_function(fn: SemanticFunction, stats: _SimplifyStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    return replace(fn, body=_simplify_block(fn.body, stats))


def _simplify_method(method: SemanticMethod, stats: _SimplifyStats) -> SemanticMethod:
    return replace(method, body=_simplify_block(method.body, stats))


def _simplify_block(block: SemanticBlock, stats: _SimplifyStats) -> SemanticBlock:
    simplified_statements: list[SemanticStmt] = []
    block_terminated = False

    for stmt in block.statements:
        if block_terminated:
            stats.pruned_unreachable_statements += 1
            continue

        replacement_statements = _simplify_stmt(stmt, stats)
        for replacement_stmt in replacement_statements:
            if block_terminated:
                stats.pruned_unreachable_statements += 1
                continue
            simplified_statements.append(replacement_stmt)
            if _is_terminator(replacement_stmt):
                block_terminated = True

    return replace(block, statements=simplified_statements)


def _simplify_stmt(stmt: SemanticStmt, stats: _SimplifyStats) -> list[SemanticStmt]:
    if isinstance(stmt, SemanticBlock):
        return [_simplify_block(stmt, stats)]

    if isinstance(stmt, SemanticIf):
        simplified_then = _simplify_block(stmt.then_block, stats)
        simplified_else = None if stmt.else_block is None else _simplify_block(stmt.else_block, stats)
        condition_value = _bool_literal_value(stmt.condition)

        if condition_value is True:
            stats.simplified_conditionals += 1
            return list(simplified_then.statements)
        if condition_value is False:
            stats.simplified_conditionals += 1
            if simplified_else is None:
                return []
            return list(simplified_else.statements)

        return [replace(stmt, then_block=simplified_then, else_block=simplified_else)]

    if isinstance(stmt, SemanticWhile):
        simplified_body = _simplify_block(stmt.body, stats)
        if _bool_literal_value(stmt.condition) is False:
            stats.removed_while_loops += 1
            return []
        return [replace(stmt, body=simplified_body)]

    if isinstance(stmt, SemanticForIn):
        return [replace(stmt, body=_simplify_block(stmt.body, stats))]

    return [stmt]


def _bool_literal_value(expr: SemanticExpr) -> bool | None:
    if isinstance(expr, LiteralExprS) and isinstance(expr.constant, BoolConstant):
        return expr.constant.value
    return None


def _is_terminator(stmt: SemanticStmt) -> bool:
    return isinstance(stmt, (SemanticReturn, SemanticBreak, SemanticContinue))
