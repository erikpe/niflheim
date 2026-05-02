from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.ir import *
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, SemanticUnaryOp, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_primitive_type_ref, semantic_type_canonical_name

from .helpers.semantic_rewriter import SemanticTreeRewriter


_ALL_ONES_BY_TYPE = {
    TYPE_NAME_I64: -1,
    TYPE_NAME_U64: (1 << 64) - 1,
    TYPE_NAME_U8: (1 << 8) - 1,
}


@dataclass
class _AlgebraicSimplifyStats:
    simplified_expressions: int = 0


class _AlgebraicSimplifier(SemanticTreeRewriter):
    def __init__(self, stats: _AlgebraicSimplifyStats) -> None:
        self._stats = stats

    def transform_expr(self, expr: SemanticExpr) -> SemanticExpr:
        if isinstance(expr, UnaryExprS):
            return self._simplify_unary(expr)
        if isinstance(expr, BinaryExprS):
            return self._simplify_binary(expr)
        return expr

    def _simplify_unary(self, expr: UnaryExprS) -> SemanticExpr:
        if expr.op.kind is UnaryOpKind.LOGICAL_NOT and isinstance(expr.operand, UnaryExprS):
            operand = expr.operand
            if operand.op.kind is UnaryOpKind.LOGICAL_NOT:
                self._stats.simplified_expressions += 1
                return _with_span(operand.operand, expr.span)
        return expr

    def _simplify_binary(self, expr: BinaryExprS) -> SemanticExpr:
        if expr.op.flavor is BinaryOpFlavor.BOOL_LOGICAL:
            return self._simplify_bool_logical(expr)
        if expr.op.flavor is BinaryOpFlavor.BOOL_COMPARISON:
            return self._simplify_bool_comparison(expr)
        if expr.op.flavor is BinaryOpFlavor.INTEGER:
            return self._simplify_integer(expr)
        return expr

    def _simplify_bool_logical(self, expr: BinaryExprS) -> SemanticExpr:
        left_bool = _bool_literal_value(expr.left)
        right_bool = _bool_literal_value(expr.right)

        if expr.op.kind is BinaryOpKind.LOGICAL_AND:
            if left_bool is False:
                self._stats.simplified_expressions += 1
                return _bool_literal(False, span=expr.span)
            if left_bool is True:
                self._stats.simplified_expressions += 1
                return _with_span(expr.right, expr.span)
            if right_bool is True:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr

        if expr.op.kind is BinaryOpKind.LOGICAL_OR:
            if left_bool is True:
                self._stats.simplified_expressions += 1
                return _bool_literal(True, span=expr.span)
            if left_bool is False:
                self._stats.simplified_expressions += 1
                return _with_span(expr.right, expr.span)
            if right_bool is False:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr

        return expr

    def _simplify_bool_comparison(self, expr: BinaryExprS) -> SemanticExpr:
        left_bool = _bool_literal_value(expr.left)
        right_bool = _bool_literal_value(expr.right)

        if expr.op.kind is BinaryOpKind.EQUAL:
            if left_bool is True:
                self._stats.simplified_expressions += 1
                return _with_span(expr.right, expr.span)
            if right_bool is True:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            if left_bool is False:
                self._stats.simplified_expressions += 1
                return _logical_not(expr.right, span=expr.span)
            if right_bool is False:
                self._stats.simplified_expressions += 1
                return _logical_not(expr.left, span=expr.span)
            return expr

        if expr.op.kind is BinaryOpKind.NOT_EQUAL:
            if left_bool is False:
                self._stats.simplified_expressions += 1
                return _with_span(expr.right, expr.span)
            if right_bool is False:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            if left_bool is True:
                self._stats.simplified_expressions += 1
                return _logical_not(expr.right, span=expr.span)
            if right_bool is True:
                self._stats.simplified_expressions += 1
                return _logical_not(expr.left, span=expr.span)
            return expr

        return expr

    def _simplify_integer(self, expr: BinaryExprS) -> SemanticExpr:
        left_value = _integer_literal_value(expr.left)
        right_value = _integer_literal_value(expr.right)
        operand_type_name = semantic_type_canonical_name(expr.type_ref)

        if expr.op.kind is BinaryOpKind.ADD:
            return self._simplify_identity(expr, left_value=left_value, right_value=right_value, identity=0)
        if expr.op.kind is BinaryOpKind.SUBTRACT:
            if right_value == 0:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr
        if expr.op.kind is BinaryOpKind.MULTIPLY:
            return self._simplify_identity(expr, left_value=left_value, right_value=right_value, identity=1)
        if expr.op.kind is BinaryOpKind.DIVIDE:
            if right_value == 1:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr
        if expr.op.kind is BinaryOpKind.POWER:
            if right_value == 1:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr
        if expr.op.kind is BinaryOpKind.BITWISE_AND:
            all_ones = _ALL_ONES_BY_TYPE.get(operand_type_name)
            if all_ones is None:
                return expr
            return self._simplify_identity(expr, left_value=left_value, right_value=right_value, identity=all_ones)
        if expr.op.kind in {BinaryOpKind.BITWISE_OR, BinaryOpKind.BITWISE_XOR}:
            return self._simplify_identity(expr, left_value=left_value, right_value=right_value, identity=0)
        if expr.op.kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
            if right_value == 0:
                self._stats.simplified_expressions += 1
                return _with_span(expr.left, expr.span)
            return expr
        return expr

    def _simplify_identity(
        self,
        expr: BinaryExprS,
        *,
        left_value: int | None,
        right_value: int | None,
        identity: int,
    ) -> SemanticExpr:
        if left_value == identity:
            self._stats.simplified_expressions += 1
            return _with_span(expr.right, expr.span)
        if right_value == identity:
            self._stats.simplified_expressions += 1
            return _with_span(expr.left, expr.span)
        return expr


def algebraic_simplify(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _AlgebraicSimplifyStats()
    optimized_program = _AlgebraicSimplifier(stats).rewrite_program(program)
    logger.debugv(
        1, "Optimization pass algebraic_simplify simplified %d expressions", stats.simplified_expressions
    )
    return optimized_program


def _bool_literal_value(expr: SemanticExpr) -> bool | None:
    if isinstance(expr, LiteralExprS) and isinstance(expr.constant, BoolConstant):
        return expr.constant.value
    return None


def _integer_literal_value(expr: SemanticExpr) -> int | None:
    if isinstance(expr, LiteralExprS) and isinstance(expr.constant, (IntConstant, CharConstant)):
        return expr.constant.value
    return None


def _with_span(expr: SemanticExpr, span) -> SemanticExpr:
    return replace(expr, span=span)


def _logical_not(expr: SemanticExpr, *, span) -> UnaryExprS:
    return UnaryExprS(
        op=SemanticUnaryOp(kind=UnaryOpKind.LOGICAL_NOT, flavor=UnaryOpFlavor.BOOL),
        operand=_with_span(expr, span),
        type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        span=span,
    )


def _bool_literal(value: bool, *, span) -> LiteralExprS:
    return LiteralExprS(
        constant=BoolConstant(value=value),
        type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        span=span,
    )


__all__ = ["algebraic_simplify"]
