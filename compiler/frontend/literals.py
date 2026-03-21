from __future__ import annotations

from compiler.common.literals import parse_float_literal, parse_int_literal
from compiler.frontend.ast_nodes import *
from compiler.frontend.lexer import SourceSpan, Token
from compiler.frontend.tokens import TokenKind


def _literal_expr(literal: LiteralValueNode, span: SourceSpan) -> LiteralExpr:
    return LiteralExpr(literal=literal, span=span)


def parse_int_literal_text(text: str) -> IntLiteralValue:
    magnitude, kind = parse_int_literal(text)
    return IntLiteralValue(raw_text=text, magnitude=magnitude, kind=kind)


def parse_float_literal_text(text: str) -> FloatLiteralValue:
    return FloatLiteralValue(raw_text=text, value=parse_float_literal(text))


def literal_expr_from_token(token: Token) -> LiteralExpr:
    if token.kind == TokenKind.INT_LIT:
        return _literal_expr(parse_int_literal_text(token.lexeme), token.span)
    if token.kind == TokenKind.FLOAT_LIT:
        return _literal_expr(parse_float_literal_text(token.lexeme), token.span)
    if token.kind == TokenKind.STRING_LIT:
        return _literal_expr(StringLiteralValue(raw_text=token.lexeme), token.span)
    if token.kind == TokenKind.CHAR_LIT:
        return _literal_expr(CharLiteralValue(raw_text=token.lexeme), token.span)
    if token.kind == TokenKind.TRUE:
        return _literal_expr(BoolLiteralValue(value=True, raw_text=token.lexeme), token.span)
    if token.kind == TokenKind.FALSE:
        return _literal_expr(BoolLiteralValue(value=False, raw_text=token.lexeme), token.span)
    raise ValueError(f"Expected literal token, got {token.kind.name}")


def int_literal_expr(text: str, span: SourceSpan) -> LiteralExpr:
    return _literal_expr(parse_int_literal_text(text), span)
