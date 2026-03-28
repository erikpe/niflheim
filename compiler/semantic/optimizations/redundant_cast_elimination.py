from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *
from compiler.semantic.types import semantic_type_canonical_name

from .helpers.semantic_rewriter import SemanticTreeRewriter


@dataclass
class _RedundantCastStats:
    removed_redundant_casts: int = 0


class _RedundantCastEliminator(SemanticTreeRewriter):
    def __init__(self, stats: _RedundantCastStats) -> None:
        self._stats = stats

    def transform_expr(self, expr: SemanticExpr) -> SemanticExpr:
        if not isinstance(expr, CastExprS):
            return expr
        if not _is_redundant_cast(expr):
            return expr
        self._stats.removed_redundant_casts += 1
        return replace(expr.operand, type_ref=expr.type_ref, span=expr.span)


def redundant_cast_elimination(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _RedundantCastStats()
    optimized_program = _RedundantCastEliminator(stats).rewrite_program(program)
    logger.debugv(
        1, "Optimization pass redundant_cast_elimination removed %d redundant casts", stats.removed_redundant_casts
    )
    return optimized_program


def _is_redundant_cast(expr: CastExprS) -> bool:
    operand_type_name = semantic_type_canonical_name(expression_type_ref(expr.operand))
    target_type_name = semantic_type_canonical_name(expr.target_type_ref)
    return operand_type_name == target_type_name
