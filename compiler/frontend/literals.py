from __future__ import annotations

from compiler.frontend.ast_nodes import FloatLiteralValue, IntLiteralValue


def parse_int_literal_text(text: str) -> IntLiteralValue:
    if not text:
        raise ValueError("Expected integer literal text")

    suffix: str | None = None
    digits = text
    if text.endswith("u8"):
        suffix = "u8"
        digits = text[:-2]
    elif text.endswith("u"):
        suffix = "u"
        digits = text[:-1]

    if not digits or not digits.isdigit():
        raise ValueError(f"Unsupported integer literal syntax: {text}")

    return IntLiteralValue(raw_text=text, magnitude=int(digits), base=10, suffix=suffix)


def parse_float_literal_text(text: str) -> FloatLiteralValue:
    if not text:
        raise ValueError("Expected floating-point literal text")

    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"Unsupported floating-point literal syntax: {text}") from exc

    return FloatLiteralValue(raw_text=text, value=value)