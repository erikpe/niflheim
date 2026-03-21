from compiler.common.literals import decode_char_literal, decode_string_literal, is_hex_digit, is_hex_digits


def test_hex_digit_helpers_cover_single_chars_and_sequences() -> None:
    assert is_hex_digit("0")
    assert is_hex_digit("a")
    assert is_hex_digit("F")
    assert not is_hex_digit("g")

    assert is_hex_digits("2A0f")
    assert not is_hex_digits("2Ag")


def test_decode_string_literal_handles_simple_and_hex_escapes() -> None:
    assert decode_string_literal('"A\\n\\x42\\0"') == b"A\nB\0"


def test_decode_char_literal_handles_plain_and_escaped_values() -> None:
    assert decode_char_literal("'q'") == ord("q")
    assert decode_char_literal("'\\n'") == 0x0A
    assert decode_char_literal("'\\x71'") == 0x71