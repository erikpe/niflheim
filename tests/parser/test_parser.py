import pytest

from compiler.lexer import lex
from compiler.parser import ParserError, TokenStream
from compiler.tokens import TokenKind


def test_token_stream_peek_and_advance() -> None:
    tokens = lex("fn main() -> unit { return; }")
    stream = TokenStream(tokens)

    assert stream.peek().kind == TokenKind.FN
    assert stream.peek(1).kind == TokenKind.IDENT

    first = stream.advance()
    assert first.kind == TokenKind.FN
    assert stream.peek().kind == TokenKind.IDENT


def test_token_stream_match_and_expect() -> None:
    tokens = lex("return;")
    stream = TokenStream(tokens)

    assert stream.match(TokenKind.RETURN)
    semicolon = stream.expect(TokenKind.SEMICOLON, "Expected ';'")
    assert semicolon.kind == TokenKind.SEMICOLON
    assert stream.is_at_end()


def test_token_stream_expect_raises_with_location() -> None:
    tokens = lex("return", source_path="examples/missing_semicolon.nif")
    stream = TokenStream(tokens)
    stream.expect(TokenKind.RETURN, "Expected return")

    with pytest.raises(ParserError) as error:
        stream.expect(TokenKind.SEMICOLON, "Expected ';'")

    assert "examples/missing_semicolon.nif:1:7" in str(error.value)


def test_token_stream_previous_and_end_behavior() -> None:
    tokens = lex("var x: i64;", source_path="examples/sample.nif")
    stream = TokenStream(tokens)

    assert stream.previous().kind == TokenKind.VAR
    stream.advance()
    assert stream.previous().kind == TokenKind.VAR

    while not stream.is_at_end():
        stream.advance()

    eof1 = stream.peek()
    eof2 = stream.advance()
    assert eof1.kind == TokenKind.EOF
    assert eof2.kind == TokenKind.EOF
