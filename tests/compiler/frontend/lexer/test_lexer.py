import pytest

from compiler.frontend.lexer import LexerError, TokenKind, lex


def test_lex_basic_function_signature_and_keywords() -> None:
    source = "export fn main() -> unit { return; }"
    kinds = [token.kind for token in lex(source)]
    assert kinds == [
        TokenKind.EXPORT,
        TokenKind.FN,
        TokenKind.IDENT,
        TokenKind.LPAREN,
        TokenKind.RPAREN,
        TokenKind.ARROW,
        TokenKind.UNIT,
        TokenKind.LBRACE,
        TokenKind.RETURN,
        TokenKind.SEMICOLON,
        TokenKind.RBRACE,
        TokenKind.EOF,
    ]


def test_lex_extern_keyword() -> None:
    source = "extern fn rt_gc_collect(ts: Obj) -> unit;"
    kinds = [token.kind for token in lex(source)]
    assert kinds == [
        TokenKind.EXTERN,
        TokenKind.FN,
        TokenKind.IDENT,
        TokenKind.LPAREN,
        TokenKind.IDENT,
        TokenKind.COLON,
        TokenKind.OBJ,
        TokenKind.RPAREN,
        TokenKind.ARROW,
        TokenKind.UNIT,
        TokenKind.SEMICOLON,
        TokenKind.EOF,
    ]


def test_lex_static_keyword() -> None:
    source = "class C { static fn f() -> unit { return; } }"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.STATIC in kinds


def test_lex_private_keyword() -> None:
    source = "class C { private value: i64; private fn f() -> unit { return; } }"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.PRIVATE in kinds


def test_lex_final_keyword() -> None:
    source = "class C { final value: i64; }"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.FINAL in kinds


def test_lex_override_keyword() -> None:
    source = "class C { override fn f() -> unit { return; } }"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.OVERRIDE in kinds


def test_lex_remaining_keywords_and_punctuation_tokens() -> None:
    source = "import util; if true && false || !null { while a < b { break; } } else { continue; } [x, y].field == z != w <= q >= r"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.IMPORT in kinds
    assert TokenKind.IF in kinds
    assert TokenKind.TRUE in kinds
    assert TokenKind.ANDAND in kinds
    assert TokenKind.FALSE in kinds
    assert TokenKind.OROR in kinds
    assert TokenKind.BANG in kinds
    assert TokenKind.NULL in kinds
    assert TokenKind.WHILE in kinds
    assert TokenKind.LT in kinds
    assert TokenKind.BREAK in kinds
    assert TokenKind.ELSE in kinds
    assert TokenKind.CONTINUE in kinds
    assert TokenKind.LBRACKET in kinds
    assert TokenKind.COMMA in kinds
    assert TokenKind.RBRACKET in kinds
    assert TokenKind.DOT in kinds
    assert TokenKind.EQEQ in kinds
    assert TokenKind.NEQ in kinds
    assert TokenKind.LTE in kinds
    assert TokenKind.GTE in kinds


def test_lex_interface_and_implements_keywords() -> None:
    source = "export interface Hashable { fn hash_code() -> u64; } class Key implements Hashable {}"
    kinds = [token.kind for token in lex(source)]

    assert TokenKind.INTERFACE in kinds
    assert TokenKind.IMPLEMENTS in kinds


def test_lex_skips_whitespace_and_line_comments() -> None:
    source = "// first\nvar x: i64 = 1; // second\n"
    tokens = lex(source)
    assert [t.kind for t in tokens] == [
        TokenKind.VAR,
        TokenKind.IDENT,
        TokenKind.COLON,
        TokenKind.I64,
        TokenKind.ASSIGN,
        TokenKind.INT_LIT,
        TokenKind.SEMICOLON,
        TokenKind.EOF,
    ]


def test_lex_skips_trailing_comment_without_newline() -> None:
    source = "var x: i64 = 1; // trailing"
    tokens = lex(source)
    assert [t.kind for t in tokens] == [
        TokenKind.VAR,
        TokenKind.IDENT,
        TokenKind.COLON,
        TokenKind.I64,
        TokenKind.ASSIGN,
        TokenKind.INT_LIT,
        TokenKind.SEMICOLON,
        TokenKind.EOF,
    ]


def test_lex_numbers_and_string_literal() -> None:
    source = 'var a: double = 12.5; var s: Str = "hi\\n";'
    tokens = lex(source)
    kinds = [t.kind for t in tokens]
    assert TokenKind.FLOAT_LIT in kinds
    assert TokenKind.STRING_LIT in kinds
    float_token = next(t for t in tokens if t.kind == TokenKind.FLOAT_LIT)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING_LIT)
    assert float_token.lexeme == "12.5"
    assert string_token.lexeme == '"hi\\n"'


def test_lex_u64_suffixed_integer_literal() -> None:
    source = "var x: u64 = 42u;"
    tokens = lex(source)
    int_token = next(t for t in tokens if t.kind == TokenKind.INT_LIT)
    assert int_token.lexeme == "42u"


def test_lex_u8_suffixed_integer_literal() -> None:
    source = "var x: u8 = 113u8;"
    tokens = lex(source)
    int_token = next(t for t in tokens if t.kind == TokenKind.INT_LIT)
    assert int_token.lexeme == "113u8"


def test_lex_hex_integer_literals() -> None:
    source = "var a: i64 = 0x2a; var b: u64 = 0x2Au; var c: u8 = 0xffu8;"
    tokens = [token for token in lex(source) if token.kind == TokenKind.INT_LIT]

    assert [token.lexeme for token in tokens] == ["0x2a", "0x2Au", "0xffu8"]


@pytest.mark.parametrize(
    ("literal_text", "expected_lexeme"),
    [
        ("0x", "0x"),
        ("0xu", "0xu"),
        ("0xu8", "0xu8"),
        ("0xg", "0xg"),
        ("0x1g", "0x1g"),
        ("0x1gu8", "0x1gu8"),
    ],
)
def test_lex_invalid_hex_integer_spelling_stays_single_token(literal_text: str, expected_lexeme: str) -> None:
    tokens = [
        token
        for token in lex(f"var x: i64 = {literal_text};", source_path="examples/hex_bad.nif")
        if token.kind == TokenKind.INT_LIT
    ]

    assert [token.lexeme for token in tokens] == [expected_lexeme]


def test_lex_char_literal_and_escape_literal() -> None:
    source = "var a: u8 = 'q'; var b: u8 = '\\x71';"
    tokens = lex(source)
    char_tokens = [t for t in tokens if t.kind == TokenKind.CHAR_LIT]
    assert len(char_tokens) == 2
    assert char_tokens[0].lexeme == "'q'"
    assert char_tokens[1].lexeme == "'\\x71'"


def test_lex_string_literal_allows_hex_escape() -> None:
    source = 'var s: Str = "A\\x42\\0";'
    tokens = lex(source)
    string_token = next(t for t in tokens if t.kind == TokenKind.STRING_LIT)
    assert string_token.lexeme == '"A\\x42\\0"'


def test_lex_token_span_line_and_column() -> None:
    source = "\n\n  fn id(x: i64) -> i64 { return x; }"
    tokens = lex(source)
    fn_token = tokens[0]
    assert fn_token.kind == TokenKind.FN
    assert fn_token.span.start.line == 3
    assert fn_token.span.start.column == 3


def test_lex_raises_on_unterminated_string() -> None:
    with pytest.raises(LexerError) as error:
        lex('var s: Str = "unterminated')

    assert "Unterminated string literal" in str(error.value)


def test_lex_raises_on_invalid_string_escape() -> None:
    with pytest.raises(LexerError, match="Invalid string escape sequence"):
        lex('var s: Str = "bad\\q";')


def test_lex_raises_on_invalid_hex_escape() -> None:
    with pytest.raises(LexerError, match="Invalid string escape sequence"):
        lex('var s: Str = "bad\\xG1";')


def test_lex_raises_on_invalid_char_escape() -> None:
    with pytest.raises(LexerError, match="Invalid character escape sequence"):
        lex("var c: u8 = '\\q';")


def test_lex_raises_on_multi_char_literal() -> None:
    with pytest.raises(LexerError, match="Character literal must contain exactly one byte"):
        lex("var c: u8 = 'ab';")


def test_lex_error_includes_path_row_col() -> None:
    with pytest.raises(LexerError) as error:
        lex('"unterminated', source_path="examples/bad.nif")

    assert "examples/bad.nif:1:1" in str(error.value)


def test_lex_identifier_allows_leading_underscore_and_digits_after_start() -> None:
    tokens = lex("var _value2: i64 = 1;")
    ident_token = next(token for token in tokens if token.kind == TokenKind.IDENT)
    assert ident_token.lexeme == "_value2"


def test_lex_vec_is_identifier_not_keyword() -> None:
    tokens = lex("var v: Vec = Vec.new();")
    vec_tokens = [token for token in tokens if token.lexeme == "Vec"]

    assert len(vec_tokens) == 2
    assert all(token.kind == TokenKind.IDENT for token in vec_tokens)


def test_lex_bitwise_operator_tokens() -> None:
    source = "var x: u64 = (1u & 2u) | (3u ^ ~4u);"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.AMP in kinds
    assert TokenKind.PIPE in kinds
    assert TokenKind.CARET in kinds
    assert TokenKind.TILDE in kinds


def test_lex_shift_operator_tokens() -> None:
    source = "var x: u64 = 1u << 3u; var y: i64 = 8 >> 1u;"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.LSHIFT in kinds
    assert TokenKind.RSHIFT in kinds


def test_lex_for_in_keywords() -> None:
    source = "for elem in coll { return; }"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.FOR in kinds
    assert TokenKind.IN in kinds


def test_lex_power_operator_token() -> None:
    source = "var x: u64 = 2u ** 10u;"
    kinds = [token.kind for token in lex(source)]
    assert TokenKind.POW in kinds


def test_lex_raises_on_unterminated_string_before_newline() -> None:
    with pytest.raises(LexerError, match="Unterminated string literal"):
        lex('var s: Str = "bad\nnext')


def test_lex_raises_on_invalid_char_hex_escape() -> None:
    with pytest.raises(LexerError, match="Invalid character escape sequence"):
        lex("var c: u8 = '\\xG1';")


def test_lex_raises_on_empty_char_literal() -> None:
    with pytest.raises(LexerError, match="Empty character literal"):
        lex("var c: u8 = '';")


def test_lex_raises_on_unterminated_char_literal() -> None:
    with pytest.raises(LexerError, match="Unterminated character literal"):
        lex("var c: u8 = '")


def test_lex_raises_on_unexpected_character() -> None:
    with pytest.raises(LexerError, match="Unexpected character '@'"):
        lex("@")
