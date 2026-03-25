from __future__ import annotations

from collections.abc import Callable

from compiler.common.literals import IntLiteralKind, decode_char_literal, decode_string_literal
from compiler.common.type_names import TYPE_NAME_I64
from compiler.common.type_shapes import is_str_type_name
from compiler.frontend.ast_nodes import *
from compiler.semantic.ir import *
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.types import semantic_primitive_type_ref
from compiler.typecheck.constants import I64_MIN_MAGNITUDE_LITERAL
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.semantic.lowering.ids import resolve_static_method_id


LowerExpr = Callable[[object], SemanticExpr]


def lower_string_literal_expr(
    typecheck_ctx: TypeCheckContext, expr: LiteralExpr, result_type_name: str
) -> CallExprS:
    if not isinstance(expr.literal, StringLiteralValue):
        raise TypeError("Expected StringLiteralValue for string literal lowering")
    decode_string_literal(expr.literal.raw_text)
    return CallExprS(
        target=StaticMethodCallTarget(
            method_id=resolve_static_method_id(typecheck_ctx, result_type_name, "from_u8_array")
        ),
        args=[
            StringLiteralBytesExpr(literal_text=expr.literal.raw_text, span=expr.span)
        ],
        type_name=result_type_name,
        type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, infer_expression_type(typecheck_ctx, expr)),
        span=expr.span,
    )


def try_lower_string_concat_expr(
    typecheck_ctx: TypeCheckContext,
    expr: BinaryExpr,
    result_type_name: str,
    result_type_ref: SemanticTypeRef,
    *,
    lower_expr: LowerExpr,
) -> CallExprS | None:
    left_type = infer_expression_type(typecheck_ctx, expr.left)
    right_type = infer_expression_type(typecheck_ctx, expr.right)
    if expr.operator != "+" or not is_str_type_name(left_type.name) or not is_str_type_name(right_type.name):
        return None

    return CallExprS(
        target=StaticMethodCallTarget(method_id=resolve_static_method_id(typecheck_ctx, result_type_name, "concat")),
        args=[lower_expr(expr.left), lower_expr(expr.right)],
        type_name=result_type_name,
        type_ref=result_type_ref,
        span=expr.span,
    )


def lower_non_string_literal_expr(typecheck_ctx: TypeCheckContext, expr: LiteralExpr) -> LiteralExprS:
    literal = expr.literal
    type_name = lowered_literal_type_name(typecheck_ctx, expr)
    type_ref = semantic_primitive_type_ref(type_name)

    if isinstance(literal, BoolLiteralValue):
        constant: SemanticConstant = BoolConstant(value=literal.value, type_name=type_name)
    elif isinstance(literal, CharLiteralValue):
        constant = CharConstant(value=decode_char_literal(literal.raw_text), type_name=type_name)
    elif isinstance(literal, FloatLiteralValue):
        constant = FloatConstant(value=literal.value, type_name=type_name)
    elif isinstance(literal, IntLiteralValue):
        constant = IntConstant(value=literal.magnitude, type_name=type_name)
    else:
        raise TypeError(f"Unsupported non-string literal for semantic lowering: {type(literal).__name__}")

    return LiteralExprS(constant=constant, type_name=type_name, type_ref=type_ref, span=expr.span)


def lowered_literal_type_name(typecheck_ctx: TypeCheckContext, expr: LiteralExpr) -> str:
    literal = expr.literal
    if (
        isinstance(literal, IntLiteralValue)
        and literal.kind == IntLiteralKind.UNSUFFIXED
        and literal.magnitude == I64_MIN_MAGNITUDE_LITERAL
    ):
        return TYPE_NAME_I64
    return infer_expression_type(typecheck_ctx, expr).name
