from __future__ import annotations

from dataclasses import dataclass

from compiler.common.span import SourceSpan
from compiler.frontend.ast_nodes import ArrayTypeRef, FunctionTypeRef, TypeRef, TypeRefNode
from compiler.frontend.parser_support import expect_symbol_name, ParserError, TokenStream
from compiler.frontend.tokens import TYPE_NAME_TOKENS, TokenKind


@dataclass(frozen=True)
class SimpleTypeLookahead:
    next_offset: int
    has_array_suffix: bool


def parse_type_ref(stream: TokenStream) -> TypeRefNode:
    if stream.match(TokenKind.FN):
        fn_token = stream.previous()
        stream.expect(TokenKind.LPAREN, "Expected '(' after 'fn' in function type")

        param_types: list[TypeRefNode] = []
        if not stream.check(TokenKind.RPAREN):
            while True:
                param_types.append(parse_type_ref(stream))
                if not stream.match(TokenKind.COMMA):
                    break

        stream.expect(TokenKind.RPAREN, "Expected ')' after function type parameters")
        stream.expect(TokenKind.ARROW, "Expected '->' after function type parameter list")
        return_type = parse_type_ref(stream)
        fn_type = FunctionTypeRef(
            param_types=param_types,
            return_type=return_type,
            span=SourceSpan(start=fn_token.span.start, end=return_type.span.end),
        )
        if stream.check(TokenKind.LBRACKET):
            raise ParserError("Array function types are not supported yet", stream.peek().span)
        return fn_type

    token = stream.peek()
    if token.kind not in TYPE_NAME_TOKENS:
        raise ParserError("Expected type name", token.span)
    stream.advance()

    base_ref: TypeRef
    if token.kind != TokenKind.IDENT:
        base_ref = TypeRef(name=token.lexeme, span=token.span)
    else:
        parts = [token.lexeme]
        end = token.span.end
        while stream.match(TokenKind.DOT):
            segment = expect_symbol_name(stream, "Expected type name after '.' in qualified type")
            parts.append(segment.lexeme)
            end = segment.span.end

        base_ref = TypeRef(name=".".join(parts), span=SourceSpan(start=token.span.start, end=end))

    type_ref: TypeRefNode = base_ref
    while stream.match(TokenKind.LBRACKET):
        stream.expect(TokenKind.RBRACKET, "Expected ']' after '[' in array type")
        type_ref = ArrayTypeRef(
            element_type=type_ref, span=SourceSpan(start=type_ref.span.start, end=stream.previous().span.end)
        )

    return type_ref


def lookahead_simple_type_ref(stream: TokenStream, start_offset: int = 0) -> SimpleTypeLookahead | None:
    token = stream.peek(start_offset)
    if token.kind not in TYPE_NAME_TOKENS or token.kind == TokenKind.FN:
        return None

    lookahead = start_offset + 1
    has_array_suffix = False
    if token.kind == TokenKind.IDENT:
        while stream.peek(lookahead).kind == TokenKind.DOT:
            if stream.peek(lookahead + 1).kind != TokenKind.IDENT:
                return None
            lookahead += 2

    while stream.peek(lookahead).kind == TokenKind.LBRACKET:
        if stream.peek(lookahead + 1).kind != TokenKind.RBRACKET:
            return None
        has_array_suffix = True
        lookahead += 2

    return SimpleTypeLookahead(next_offset=lookahead, has_array_suffix=has_array_suffix)
