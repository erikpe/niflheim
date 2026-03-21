from __future__ import annotations

from compiler.common.literals import is_hex_digits
from compiler.common.type_names import TYPE_NAME_U8
from compiler.frontend.ast_nodes import *
from compiler.frontend.lexer import SourceSpan, Token
from compiler.frontend.tokens import TokenKind


def _literal_expr(literal: LiteralValueNode, span: SourceSpan) -> LiteralExpr:
    return LiteralExpr(literal=literal, span=span)


def parse_int_literal_text(text: str) -> IntLiteralValue:
    if not text:
        raise ValueError("Expected integer literal text")

    suffix: str | None = None
    digits = text
    if text.endswith(TYPE_NAME_U8):
        suffix = TYPE_NAME_U8
        digits = text[:-2]
    elif text.endswith("u"):
        suffix = "u"
        digits = text[:-1]

    base = 10
    magnitude_digits = digits
    if digits.startswith(("0x", "0X")):
        base = 16
        magnitude_digits = digits[2:]
        if not magnitude_digits or not is_hex_digits(magnitude_digits):
            raise ValueError(f"Unsupported integer literal syntax: {text}")
    elif not digits or not digits.isdigit():
        raise ValueError(f"Unsupported integer literal syntax: {text}")

    return IntLiteralValue(raw_text=text, magnitude=int(magnitude_digits, base), base=base, suffix=suffix)


def parse_float_literal_text(text: str) -> FloatLiteralValue:
    if not text:
        raise ValueError("Expected floating-point literal text")

    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"Unsupported floating-point literal syntax: {text}") from exc

    return FloatLiteralValue(raw_text=text, value=value)


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
