from __future__ import annotations

from dataclasses import dataclass

from compiler.common.collection_protocols import (
    COLLECTION_METHOD_LEN,
    COLLECTION_METHOD_SLICE_GET,
    COLLECTION_METHOD_SLICE_SET,
)
from compiler.common.type_names import TYPE_NAME_I64
from compiler.frontend.ast_nodes import (
    BlockStmt,
    CallExpr,
    CastExpr,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForInStmt,
    TypeRef,
)
from compiler.frontend.lexer import SourceSpan, Token
from compiler.frontend.literals import int_literal_expr


@dataclass
class ParserSugar:
    symbol_counter: int = 0

    def next_symbol(self, stem: str) -> str:
        value = self.symbol_counter
        self.symbol_counter += 1
        return f"__nif_sugar_{stem}_{value}"

    def build_for_in_stmt(
        self, *, for_token: Token, element_token: Token, collection_expr: Expression, body: BlockStmt
    ) -> ForInStmt:
        return ForInStmt(
            element_name=element_token.lexeme,
            collection_expr=collection_expr,
            body=body,
            coll_temp_name=self.next_symbol("for_coll"),
            len_temp_name=self.next_symbol("for_len"),
            index_temp_name=self.next_symbol("for_i"),
            collection_type_name="",
            element_type_name="",
            span=SourceSpan(start=for_token.span.start, end=body.span.end),
        )


def build_slice_expr(
    *, object_expr: Expression, begin_expr: Expression | None, end_expr: Expression | None, end_span
) -> Expression:
    zero_literal = int_literal_expr("0", SourceSpan(start=object_expr.span.start, end=object_expr.span.start))
    begin_arg = begin_expr if begin_expr is not None else zero_literal

    if end_expr is None:
        len_field = FieldAccessExpr(
            object_expr=object_expr,
            field_name=COLLECTION_METHOD_LEN,
            span=SourceSpan(start=object_expr.span.start, end=object_expr.span.end),
        )
        len_call = CallExpr(
            callee=len_field, arguments=[], span=SourceSpan(start=object_expr.span.start, end=object_expr.span.end)
        )
        end_arg: Expression = CastExpr(
            type_ref=TypeRef(name=TYPE_NAME_I64, span=len_call.span), operand=len_call, span=len_call.span
        )
    else:
        end_arg = end_expr

    slice_field = FieldAccessExpr(
        object_expr=object_expr,
        field_name=COLLECTION_METHOD_SLICE_GET,
        span=SourceSpan(start=object_expr.span.start, end=object_expr.span.end),
    )
    return CallExpr(
        callee=slice_field, arguments=[begin_arg, end_arg], span=SourceSpan(start=object_expr.span.start, end=end_span)
    )


def try_build_slice_write_stmt(expr: Expression, value: Expression, end_span) -> ExprStmt | None:
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if expr.callee.field_name != COLLECTION_METHOD_SLICE_GET:
        return None
    if len(expr.arguments) != 2:
        return None

    set_slice_callee = FieldAccessExpr(
        object_expr=expr.callee.object_expr, field_name=COLLECTION_METHOD_SLICE_SET, span=expr.callee.span
    )
    set_slice_call = CallExpr(
        callee=set_slice_callee,
        arguments=[expr.arguments[0], expr.arguments[1], value],
        span=SourceSpan(start=expr.span.start, end=end_span),
    )
    return ExprStmt(expression=set_slice_call, span=SourceSpan(start=expr.span.start, end=end_span))
