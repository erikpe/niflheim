import pytest

from compiler.lexer import LexerError, TokenKind, lex


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


def test_lex_error_includes_path_row_col() -> None:
    with pytest.raises(LexerError) as error:
        lex('"unterminated', source_path="examples/bad.nif")

    assert "examples/bad.nif:1:1" in str(error.value)
