import pytest

from compiler.ast_nodes import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ClassDecl,
    FieldAccessExpr,
    FunctionDecl,
    IdentifierExpr,
    ImportDecl,
    IndexExpr,
)
from compiler.lexer import lex
from compiler.parser import ParserError, TokenStream, parse, parse_expression
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


def test_parse_module_level_declarations() -> None:
    source = """
import a.b;
export import std.io;

class Point {
    x: i64;
    y: i64;

    fn reset() -> unit {
        return;
    }
}

export fn main() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/module.nif"))

    assert len(module.imports) == 2
    assert all(isinstance(item, ImportDecl) for item in module.imports)
    assert module.imports[0].module_path == ["a", "b"]
    assert module.imports[0].is_export is False
    assert module.imports[1].module_path == ["std", "io"]
    assert module.imports[1].is_export is True

    assert len(module.classes) == 1
    cls = module.classes[0]
    assert isinstance(cls, ClassDecl)
    assert cls.name == "Point"
    assert cls.is_export is False
    assert [field.name for field in cls.fields] == ["x", "y"]
    assert len(cls.methods) == 1
    assert cls.methods[0].name == "reset"

    assert len(module.functions) == 1
    fn = module.functions[0]
    assert isinstance(fn, FunctionDecl)
    assert fn.name == "main"
    assert fn.is_export is True
    assert fn.return_type.name == "unit"


def test_parse_export_requires_import_class_or_fn() -> None:
    source = "export return;"
    with pytest.raises(ParserError) as error:
        parse(lex(source, source_path="examples/bad_export.nif"))

    assert "Expected 'import', 'class', or 'fn' after 'export'" in str(error.value)
    assert "examples/bad_export.nif" in str(error.value)


def test_parse_unterminated_block_raises_parser_error() -> None:
    source = "fn main() -> unit {"
    with pytest.raises(ParserError) as error:
        parse(lex(source, source_path="examples/bad_block.nif"))

    assert "Unterminated block" in str(error.value)
    assert "examples/bad_block.nif" in str(error.value)


def test_parse_expression_precedence_multiplicative_over_additive() -> None:
    expr = parse_expression(lex("1 + 2 * 3", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "+"
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "*"


def test_parse_expression_precedence_logical_and_over_or() -> None:
    expr = parse_expression(lex("a || b && c", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "||"
    assert isinstance(expr.left, IdentifierExpr)
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "&&"


def test_parse_expression_postfix_binding_order() -> None:
    expr = parse_expression(lex("obj.field(1, 2)[0]", source_path="examples/expr.nif"))

    assert isinstance(expr, IndexExpr)
    assert isinstance(expr.object_expr, CallExpr)
    assert isinstance(expr.object_expr.callee, FieldAccessExpr)
    assert expr.object_expr.callee.field_name == "field"
    assert len(expr.object_expr.arguments) == 2


def test_parse_expression_cast_then_unary_operand() -> None:
    expr = parse_expression(lex("(i64)-x", source_path="examples/expr.nif"))

    assert isinstance(expr, CastExpr)
    assert expr.type_ref.name == "i64"


def test_parse_expression_invalid_missing_rhs() -> None:
    with pytest.raises(ParserError) as error:
        parse_expression(lex("1 +", source_path="examples/bad_expr.nif"))

    assert "Expected expression" in str(error.value)
    assert "examples/bad_expr.nif" in str(error.value)


def test_parse_expression_invalid_unclosed_group() -> None:
    with pytest.raises(ParserError) as error:
        parse_expression(lex("(1 + 2", source_path="examples/bad_expr.nif"))

    assert "Expected ')' after expression" in str(error.value)
    assert "examples/bad_expr.nif" in str(error.value)
