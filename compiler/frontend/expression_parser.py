from __future__ import annotations

from typing import Callable

from compiler.common.span import SourceSpan
from compiler.frontend.ast_nodes import *
from compiler.frontend.lexer import Token
from compiler.frontend.literals import literal_expr_from_token
from compiler.frontend.parser_sugar import build_slice_expr
from compiler.frontend.parser_support import expect_symbol_name, ParserError, TokenStream
from compiler.frontend.type_parser import lookahead_simple_type_ref
from compiler.frontend.tokens import UNARY_START_TOKENS, TokenKind


ParseTypeRef = Callable[[], TypeRefNode]


class ExpressionParser:
    def __init__(self, stream: TokenStream, *, parse_type_ref: ParseTypeRef) -> None:
        self.stream = stream
        self._parse_type_ref = parse_type_ref

    def parse_expression(self) -> Expression:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> Expression:
        return self._parse_left_associative(self._parse_logical_and, TokenKind.OROR)

    def _parse_logical_and(self) -> Expression:
        return self._parse_left_associative(self._parse_bitwise_or, TokenKind.ANDAND)

    def _parse_bitwise_or(self) -> Expression:
        return self._parse_left_associative(self._parse_bitwise_xor, TokenKind.PIPE)

    def _parse_bitwise_xor(self) -> Expression:
        return self._parse_left_associative(self._parse_bitwise_and, TokenKind.CARET)

    def _parse_bitwise_and(self) -> Expression:
        return self._parse_left_associative(self._parse_equality, TokenKind.AMP)

    def _parse_equality(self) -> Expression:
        return self._parse_left_associative(self._parse_comparison, TokenKind.EQEQ, TokenKind.NEQ)

    def _parse_comparison(self) -> Expression:
        return self._parse_left_associative(
            self._parse_type_test, TokenKind.LT, TokenKind.LTE, TokenKind.GT, TokenKind.GTE
        )

    def _parse_type_test(self) -> Expression:
        expr = self._parse_shift()
        if self.stream.match(TokenKind.IS):
            type_ref = self._parse_type_ref()
            return TypeTestExpr(
                operand=expr, type_ref=type_ref, span=SourceSpan(start=expr.span.start, end=type_ref.span.end)
            )
        return expr

    def _parse_shift(self) -> Expression:
        return self._parse_left_associative(self._parse_additive, TokenKind.LSHIFT, TokenKind.RSHIFT)

    def _parse_additive(self) -> Expression:
        return self._parse_left_associative(self._parse_multiplicative, TokenKind.PLUS, TokenKind.MINUS)

    def _parse_multiplicative(self) -> Expression:
        return self._parse_left_associative(self._parse_power, TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT)

    def _parse_power(self) -> Expression:
        expr = self._parse_unary()
        if self.stream.match(TokenKind.POW):
            op = self.stream.previous()
            right = self._parse_power()
            return self._build_binary_expr(expr, op, right)
        return expr

    def _parse_unary(self) -> Expression:
        if self.stream.match(TokenKind.BANG, TokenKind.MINUS, TokenKind.TILDE):
            op = self.stream.previous()
            operand = self._parse_unary()
            return UnaryExpr(
                operator=op.lexeme, operand=operand, span=SourceSpan(start=op.span.start, end=operand.span.end)
            )

        if self._is_cast_start():
            return self._parse_cast_expr()

        return self._parse_postfix()

    def _parse_cast_expr(self) -> CastExpr:
        lparen = self.stream.expect(TokenKind.LPAREN, "Expected '(' to start cast")
        type_ref = self._parse_type_ref()
        self.stream.expect(TokenKind.RPAREN, "Expected ')' after cast type")
        operand = self._parse_unary()
        return CastExpr(
            type_ref=type_ref, operand=operand, span=SourceSpan(start=lparen.span.start, end=operand.span.end)
        )

    def _parse_postfix(self) -> Expression:
        expr = self._parse_primary()

        while True:
            if self.stream.match(TokenKind.LPAREN):
                expr = self._finish_call_expr(expr)
                continue

            if self.stream.match(TokenKind.DOT):
                expr = self._finish_field_access_expr(expr)
                continue

            if self.stream.match(TokenKind.LBRACKET):
                expr = self._finish_subscript_expr(expr)
                continue

            return expr

    def _finish_call_expr(self, callee: Expression) -> CallExpr:
        arguments: list[Expression] = []
        if not self.stream.check(TokenKind.RPAREN):
            while True:
                arguments.append(self.parse_expression())
                if not self.stream.match(TokenKind.COMMA):
                    break

        rparen = self.stream.expect(TokenKind.RPAREN, "Expected ')' after arguments")
        return CallExpr(
            callee=callee, arguments=arguments, span=SourceSpan(start=callee.span.start, end=rparen.span.end)
        )

    def _finish_field_access_expr(self, object_expr: Expression) -> FieldAccessExpr:
        field = expect_symbol_name(self.stream, "Expected field name after '.'")
        return FieldAccessExpr(
            object_expr=object_expr,
            field_name=field.lexeme,
            span=SourceSpan(start=object_expr.span.start, end=field.span.end),
        )

    def _finish_subscript_expr(self, object_expr: Expression) -> Expression:
        if self.stream.match(TokenKind.COLON):
            return self._finish_slice_expr(object_expr, begin_expr=None)

        start_expr = self.parse_expression()
        if self.stream.match(TokenKind.COLON):
            return self._finish_slice_expr(object_expr, begin_expr=start_expr)

        rbracket = self.stream.expect(TokenKind.RBRACKET, "Expected ']' after index expression")
        return IndexExpr(
            object_expr=object_expr,
            index_expr=start_expr,
            span=SourceSpan(start=object_expr.span.start, end=rbracket.span.end),
        )

    def _finish_slice_expr(self, object_expr: Expression, *, begin_expr: Expression | None) -> Expression:
        end_expr: Expression | None = None
        if not self.stream.check(TokenKind.RBRACKET):
            end_expr = self.parse_expression()
        rbracket = self.stream.expect(TokenKind.RBRACKET, "Expected ']' after slice expression")
        return build_slice_expr(
            object_expr=object_expr, begin_expr=begin_expr, end_expr=end_expr, end_span=rbracket.span.end
        )

    def _parse_primary(self) -> Expression:
        if self.stream.check(TokenKind.FN):
            raise ParserError("Function literals/closures are not supported in MVP", self.stream.peek().span)

        if self.stream.match(
            TokenKind.INT_LIT,
            TokenKind.FLOAT_LIT,
            TokenKind.STRING_LIT,
            TokenKind.CHAR_LIT,
            TokenKind.TRUE,
            TokenKind.FALSE,
        ):
            token = self.stream.previous()
            try:
                return literal_expr_from_token(token)
            except ValueError as exc:
                raise ParserError(str(exc), token.span) from exc

        if self.stream.match(TokenKind.NULL):
            return NullExpr(span=self.stream.previous().span)

        if self._is_array_ctor_start():
            return self._parse_array_ctor_expr()

        if self.stream.match(TokenKind.IDENT):
            token = self.stream.previous()
            return IdentifierExpr(name=token.lexeme, span=token.span)

        if self.stream.match(TokenKind.LPAREN):
            expr = self.parse_expression()
            self.stream.expect(TokenKind.RPAREN, "Expected ')' after expression")
            return expr

        raise ParserError("Expected expression", self.stream.peek().span)

    def _is_array_ctor_start(self) -> bool:
        lookahead = lookahead_simple_type_ref(self.stream)
        if lookahead is None or not lookahead.has_array_suffix:
            return False
        return self.stream.peek(lookahead.next_offset).kind == TokenKind.LPAREN

    def _parse_array_ctor_expr(self) -> ArrayCtorExpr:
        element_type_ref = self._parse_type_ref()
        if not isinstance(element_type_ref, ArrayTypeRef):
            raise ParserError("Expected array constructor type suffix '[]'", self.stream.peek().span)

        self.stream.expect(TokenKind.LPAREN, "Expected '(' after array constructor type")
        if self.stream.check(TokenKind.RPAREN):
            raise ParserError("Expected array constructor length expression", self.stream.peek().span)
        length_expr = self.parse_expression()
        rparen = self.stream.expect(TokenKind.RPAREN, "Expected ')' after array constructor length")

        return ArrayCtorExpr(
            element_type_ref=element_type_ref,
            length_expr=length_expr,
            span=SourceSpan(start=element_type_ref.span.start, end=rparen.span.end),
        )

    def _is_cast_start(self) -> bool:
        if self.stream.peek().kind != TokenKind.LPAREN:
            return False

        lookahead = lookahead_simple_type_ref(self.stream, start_offset=1)
        if lookahead is None:
            return False
        if self.stream.peek(lookahead.next_offset).kind != TokenKind.RPAREN:
            return False

        return self.stream.peek(lookahead.next_offset + 1).kind in UNARY_START_TOKENS

    def _parse_left_associative(
        self, operand_parser: Callable[[], Expression], *operator_kinds: TokenKind
    ) -> Expression:
        expr = operand_parser()
        while self.stream.match(*operator_kinds):
            op = self.stream.previous()
            right = operand_parser()
            expr = self._build_binary_expr(expr, op, right)
        return expr

    @staticmethod
    def _build_binary_expr(left: Expression, op: Token, right: Expression) -> BinaryExpr:
        return BinaryExpr(
            left=left, operator=op.lexeme, right=right, span=SourceSpan(start=left.span.start, end=right.span.end)
        )
