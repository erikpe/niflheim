from __future__ import annotations

from enum import StrEnum


INT_LITERAL_SUFFIX_U64 = "u"
INT_LITERAL_SUFFIX_U8 = "u8"
INT_LITERAL_HEX_PREFIXES = ("0x", "0X")


class IntLiteralKind(StrEnum):
    UNSUFFIXED = "unsuffixed"
    U64 = "u64"
    U8 = "u8"


def split_int_literal_suffix(text: str) -> tuple[str, str | None]:
    if text.endswith(INT_LITERAL_SUFFIX_U8):
        return text[:-len(INT_LITERAL_SUFFIX_U8)], INT_LITERAL_SUFFIX_U8
    if text.endswith(INT_LITERAL_SUFFIX_U64):
        return text[:-len(INT_LITERAL_SUFFIX_U64)], INT_LITERAL_SUFFIX_U64
    return text, None


def _int_literal_kind_from_suffix(suffix: str | None) -> IntLiteralKind:
    if suffix == INT_LITERAL_SUFFIX_U8:
        return IntLiteralKind.U8
    if suffix == INT_LITERAL_SUFFIX_U64:
        return IntLiteralKind.U64
    return IntLiteralKind.UNSUFFIXED


def parse_int_literal(text: str) -> tuple[int, IntLiteralKind]:
    if not text:
        raise ValueError("Expected integer literal text")

    digits, suffix = split_int_literal_suffix(text)
    kind = _int_literal_kind_from_suffix(suffix)
    if not digits:
        raise ValueError(f"Unsupported integer literal syntax: {text}")

    if digits.startswith(INT_LITERAL_HEX_PREFIXES):
        magnitude_digits = digits[2:]
        if not magnitude_digits or not is_hex_digits(magnitude_digits):
            raise ValueError(f"Unsupported integer literal syntax: {text}")
        return int(magnitude_digits, 16), kind

    if not digits.isdigit():
        raise ValueError(f"Unsupported integer literal syntax: {text}")

    return int(digits, 10), kind


def parse_float_literal(text: str) -> float:
    if not text:
        raise ValueError("Expected floating-point literal text")

    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Unsupported floating-point literal syntax: {text}") from exc


def is_hex_digit(ch: str) -> bool:
    return ch.isdigit() or ("a" <= ch <= "f") or ("A" <= ch <= "F")


def is_hex_digits(text: str) -> bool:
    return all(is_hex_digit(ch) for ch in text)


def decode_string_literal(lexeme: str) -> bytes:
    if len(lexeme) < 2 or not lexeme.startswith('"') or not lexeme.endswith('"'):
        raise ValueError(f"invalid string literal lexeme: {lexeme!r}")

    payload = lexeme[1:-1]
    out = bytearray()
    index = 0
    while index < len(payload):
        ch = payload[index]
        if ch != "\\":
            out.append(ord(ch))
            index += 1
            continue

        index += 1
        if index >= len(payload):
            raise ValueError("invalid trailing backslash in string literal")

        esc = payload[index]
        if esc == '"':
            out.append(ord('"'))
            index += 1
            continue
        if esc == "\\":
            out.append(ord("\\"))
            index += 1
            continue
        if esc == "n":
            out.append(0x0A)
            index += 1
            continue
        if esc == "r":
            out.append(0x0D)
            index += 1
            continue
        if esc == "t":
            out.append(0x09)
            index += 1
            continue
        if esc == "0":
            out.append(0x00)
            index += 1
            continue
        if esc == "x":
            if index + 2 >= len(payload):
                raise ValueError("invalid \\x escape in string literal")
            hex_text = payload[index + 1 : index + 3]
            out.append(int(hex_text, 16))
            index += 3
            continue

        raise ValueError(f"unsupported string escape \\{esc}")

    return bytes(out)


def decode_char_literal(lexeme: str) -> int:
    if len(lexeme) < 3 or not lexeme.startswith("'") or not lexeme.endswith("'"):
        raise ValueError(f"invalid char literal lexeme: {lexeme!r}")

    payload = lexeme[1:-1]
    if len(payload) == 1:
        return ord(payload)

    if not payload.startswith("\\"):
        raise ValueError(f"invalid char literal payload: {lexeme!r}")

    if len(payload) == 2:
        esc = payload[1]
        if esc == "n":
            return 0x0A
        if esc == "r":
            return 0x0D
        if esc == "t":
            return 0x09
        if esc == "0":
            return 0x00
        if esc == "\\":
            return 0x5C
        if esc == "'":
            return 0x27
        if esc == '"':
            return 0x22
        raise ValueError(f"unsupported char escape: {lexeme!r}")

    if len(payload) == 4 and payload[1] == "x":
        return int(payload[2:], 16)

    raise ValueError(f"invalid char literal payload: {lexeme!r}")
