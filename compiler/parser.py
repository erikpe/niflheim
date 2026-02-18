from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ClassDecl,
    Expression,
    FieldDecl,
    FieldAccessExpr,
    FunctionDecl,
    IdentifierExpr,
    IndexExpr,
    ImportDecl,
    LiteralExpr,
    MethodDecl,
    ModuleAst,
    NullExpr,
    ParamDecl,
    TypeRef,
    UnaryExpr,
)
from compiler.lexer import SourceSpan, Token
from compiler.tokens import TokenKind


class ParserError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span


@dataclass
class TokenStream:
    tokens: list[Token]
    index: int = 0

    def __post_init__(self) -> None:
        if not self.tokens:
            raise ValueError("TokenStream requires at least one token (EOF)")

    def is_at_end(self) -> bool:
        return self.peek().kind == TokenKind.EOF

    def peek(self, offset: int = 0) -> Token:
        target = self.index + offset
        if target < 0:
            return self.tokens[0]
        if target >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[target]

    def previous(self) -> Token:
        return self.peek(-1)

    def advance(self) -> Token:
        current = self.peek()
        if not self.is_at_end():
            self.index += 1
        return current

    def check(self, kind: TokenKind) -> bool:
        return self.peek().kind == kind

    def check_any(self, *kinds: TokenKind) -> bool:
        return self.peek().kind in kinds

    def match(self, *kinds: TokenKind) -> bool:
        if self.check_any(*kinds):
            self.advance()
            return True
        return False

    def expect(self, kind: TokenKind, message: str) -> Token:
        if self.check(kind):
            return self.advance()
        raise ParserError(message, self.peek().span)


def parse(tokens: list[Token]):
    stream = TokenStream(tokens)
    imports: list[ImportDecl] = []
    classes: list[ClassDecl] = []
    functions: list[FunctionDecl] = []

    start = stream.peek().span.start

    while not stream.is_at_end():
        if stream.match(TokenKind.IMPORT):
            imports.append(_parse_import_decl(stream, is_export=False, import_token=stream.previous()))
            continue

        if stream.match(TokenKind.EXPORT):
            export_token = stream.previous()
            if stream.match(TokenKind.IMPORT):
                imports.append(_parse_import_decl(stream, is_export=True, import_token=stream.previous(), export_token=export_token))
                continue

            if stream.match(TokenKind.CLASS):
                classes.append(_parse_class_decl(stream, is_export=True, class_token=stream.previous(), export_token=export_token))
                continue

            if stream.match(TokenKind.FN):
                functions.append(_parse_function_decl(stream, is_export=True, fn_token=stream.previous(), export_token=export_token))
                continue

            raise ParserError("Expected 'import', 'class', or 'fn' after 'export'", stream.peek().span)

        if stream.match(TokenKind.CLASS):
            classes.append(_parse_class_decl(stream, is_export=False, class_token=stream.previous()))
            continue

        if stream.match(TokenKind.FN):
            functions.append(_parse_function_decl(stream, is_export=False, fn_token=stream.previous()))
            continue

        raise ParserError("Unexpected token at module scope", stream.peek().span)

    end = stream.peek().span.end
    return ModuleAst(
        imports=imports,
        classes=classes,
        functions=functions,
        span=SourceSpan(start=start, end=end),
    )


def parse_expression(tokens: list[Token]) -> Expression:
    stream = TokenStream(tokens)
    expr = _parse_expression(stream)
    stream.expect(TokenKind.EOF, "Expected end of expression")
    return expr


def _parse_import_decl(
    stream: TokenStream,
    *,
    is_export: bool,
    import_token: Token,
    export_token: Token | None = None,
) -> ImportDecl:
    parts: list[str] = []
    first = stream.expect(TokenKind.IDENT, "Expected module path after import")
    parts.append(first.lexeme)

    while stream.match(TokenKind.DOT):
        part = stream.expect(TokenKind.IDENT, "Expected identifier after '.' in module path")
        parts.append(part.lexeme)

    semicolon = stream.expect(TokenKind.SEMICOLON, "Expected ';' after import declaration")
    start_pos = export_token.span.start if export_token is not None else import_token.span.start
    span = SourceSpan(start=start_pos, end=semicolon.span.end)
    return ImportDecl(module_path=parts, is_export=is_export, span=span)


def _parse_class_decl(
    stream: TokenStream,
    *,
    is_export: bool,
    class_token: Token,
    export_token: Token | None = None,
) -> ClassDecl:
    name_token = stream.expect(TokenKind.IDENT, "Expected class name")
    stream.expect(TokenKind.LBRACE, "Expected '{' after class name")

    fields: list[FieldDecl] = []
    methods: list[MethodDecl] = []

    while not stream.check(TokenKind.RBRACE):
        if stream.is_at_end():
            raise ParserError("Unterminated class body", class_token.span)

        if stream.match(TokenKind.FN):
            methods.append(_parse_method_decl(stream, fn_token=stream.previous()))
            continue

        if stream.check(TokenKind.IDENT) and stream.peek(1).kind == TokenKind.COLON:
            fields.append(_parse_field_decl(stream))
            continue

        raise ParserError("Expected field or method declaration in class body", stream.peek().span)

    rbrace = stream.expect(TokenKind.RBRACE, "Expected '}' after class body")
    start_pos = export_token.span.start if export_token is not None else class_token.span.start
    span = SourceSpan(start=start_pos, end=rbrace.span.end)
    return ClassDecl(
        name=name_token.lexeme,
        fields=fields,
        methods=methods,
        is_export=is_export,
        span=span,
    )


def _parse_field_decl(stream: TokenStream) -> FieldDecl:
    name = stream.expect(TokenKind.IDENT, "Expected field name")
    stream.expect(TokenKind.COLON, "Expected ':' after field name")
    type_ref = _parse_type_ref(stream)
    semicolon = stream.expect(TokenKind.SEMICOLON, "Expected ';' after field declaration")
    return FieldDecl(
        name=name.lexeme,
        type_ref=type_ref,
        span=SourceSpan(start=name.span.start, end=semicolon.span.end),
    )


def _parse_method_decl(stream: TokenStream, *, fn_token: Token) -> MethodDecl:
    name, params, return_type = _parse_callable_signature(stream)
    body_span = _consume_block_span(stream)
    return MethodDecl(
        name=name,
        params=params,
        return_type=return_type,
        body_span=body_span,
        span=SourceSpan(start=fn_token.span.start, end=body_span.end),
    )


def _parse_function_decl(
    stream: TokenStream,
    *,
    is_export: bool,
    fn_token: Token,
    export_token: Token | None = None,
) -> FunctionDecl:
    name, params, return_type = _parse_callable_signature(stream)
    body_span = _consume_block_span(stream)
    start_pos = export_token.span.start if export_token is not None else fn_token.span.start
    return FunctionDecl(
        name=name,
        params=params,
        return_type=return_type,
        body_span=body_span,
        is_export=is_export,
        span=SourceSpan(start=start_pos, end=body_span.end),
    )


def _parse_callable_signature(stream: TokenStream) -> tuple[str, list[ParamDecl], TypeRef]:
    name = stream.expect(TokenKind.IDENT, "Expected function name")
    stream.expect(TokenKind.LPAREN, "Expected '(' after function name")

    params: list[ParamDecl] = []
    if not stream.check(TokenKind.RPAREN):
        while True:
            params.append(_parse_param(stream))
            if not stream.match(TokenKind.COMMA):
                break

    stream.expect(TokenKind.RPAREN, "Expected ')' after parameters")
    stream.expect(TokenKind.ARROW, "Expected '->' after parameter list")
    return_type = _parse_type_ref(stream)
    return name.lexeme, params, return_type


def _parse_param(stream: TokenStream) -> ParamDecl:
    name = stream.expect(TokenKind.IDENT, "Expected parameter name")
    stream.expect(TokenKind.COLON, "Expected ':' after parameter name")
    type_ref = _parse_type_ref(stream)
    return ParamDecl(
        name=name.lexeme,
        type_ref=type_ref,
        span=SourceSpan(start=name.span.start, end=type_ref.span.end),
    )


def _parse_type_ref(stream: TokenStream) -> TypeRef:
    allowed = {
        TokenKind.IDENT,
        TokenKind.I64,
        TokenKind.U64,
        TokenKind.U8,
        TokenKind.BOOL,
        TokenKind.DOUBLE,
        TokenKind.UNIT,
        TokenKind.OBJ,
        TokenKind.STR,
        TokenKind.VEC,
        TokenKind.MAP,
        TokenKind.BOXI64,
        TokenKind.BOXU64,
        TokenKind.BOXU8,
        TokenKind.BOXBOOL,
        TokenKind.BOXDOUBLE,
    }
    token = stream.peek()
    if token.kind not in allowed:
        raise ParserError("Expected type name", token.span)
    stream.advance()
    return TypeRef(name=token.lexeme, span=token.span)


def _consume_block_span(stream: TokenStream) -> SourceSpan:
    lbrace = stream.expect(TokenKind.LBRACE, "Expected '{' to start block")
    depth = 1
    last = lbrace

    while depth > 0:
        token = stream.advance()
        last = token

        if token.kind == TokenKind.EOF:
            raise ParserError("Unterminated block", token.span)

        if token.kind == TokenKind.LBRACE:
            depth += 1
            continue

        if token.kind == TokenKind.RBRACE:
            depth -= 1

    return SourceSpan(start=lbrace.span.start, end=last.span.end)


def _parse_expression(stream: TokenStream) -> Expression:
    return _parse_logical_or(stream)


def _parse_logical_or(stream: TokenStream) -> Expression:
    expr = _parse_logical_and(stream)
    while stream.match(TokenKind.OROR):
        op = stream.previous()
        right = _parse_logical_and(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_logical_and(stream: TokenStream) -> Expression:
    expr = _parse_equality(stream)
    while stream.match(TokenKind.ANDAND):
        op = stream.previous()
        right = _parse_equality(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_equality(stream: TokenStream) -> Expression:
    expr = _parse_comparison(stream)
    while stream.match(TokenKind.EQEQ, TokenKind.NEQ):
        op = stream.previous()
        right = _parse_comparison(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_comparison(stream: TokenStream) -> Expression:
    expr = _parse_additive(stream)
    while stream.match(TokenKind.LT, TokenKind.LTE, TokenKind.GT, TokenKind.GTE):
        op = stream.previous()
        right = _parse_additive(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_additive(stream: TokenStream) -> Expression:
    expr = _parse_multiplicative(stream)
    while stream.match(TokenKind.PLUS, TokenKind.MINUS):
        op = stream.previous()
        right = _parse_multiplicative(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_multiplicative(stream: TokenStream) -> Expression:
    expr = _parse_unary(stream)
    while stream.match(TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT):
        op = stream.previous()
        right = _parse_unary(stream)
        expr = BinaryExpr(
            left=expr,
            operator=op.lexeme,
            right=right,
            span=SourceSpan(start=expr.span.start, end=right.span.end),
        )
    return expr


def _parse_unary(stream: TokenStream) -> Expression:
    if stream.match(TokenKind.BANG, TokenKind.MINUS):
        op = stream.previous()
        operand = _parse_unary(stream)
        return UnaryExpr(
            operator=op.lexeme,
            operand=operand,
            span=SourceSpan(start=op.span.start, end=operand.span.end),
        )

    if _is_cast_start(stream):
        lparen = stream.expect(TokenKind.LPAREN, "Expected '(' to start cast")
        type_ref = _parse_type_ref(stream)
        stream.expect(TokenKind.RPAREN, "Expected ')' after cast type")
        operand = _parse_unary(stream)
        return CastExpr(
            type_ref=type_ref,
            operand=operand,
            span=SourceSpan(start=lparen.span.start, end=operand.span.end),
        )

    return _parse_postfix(stream)


def _parse_postfix(stream: TokenStream) -> Expression:
    expr = _parse_primary(stream)

    while True:
        if stream.match(TokenKind.LPAREN):
            lparen = stream.previous()
            args: list[Expression] = []
            if not stream.check(TokenKind.RPAREN):
                while True:
                    args.append(_parse_expression(stream))
                    if not stream.match(TokenKind.COMMA):
                        break

            rparen = stream.expect(TokenKind.RPAREN, "Expected ')' after arguments")
            expr = CallExpr(
                callee=expr,
                arguments=args,
                span=SourceSpan(start=expr.span.start, end=rparen.span.end),
            )
            continue

        if stream.match(TokenKind.DOT):
            field = stream.expect(TokenKind.IDENT, "Expected field name after '.'")
            expr = FieldAccessExpr(
                object_expr=expr,
                field_name=field.lexeme,
                span=SourceSpan(start=expr.span.start, end=field.span.end),
            )
            continue

        if stream.match(TokenKind.LBRACKET):
            index_expr = _parse_expression(stream)
            rbracket = stream.expect(TokenKind.RBRACKET, "Expected ']' after index expression")
            expr = IndexExpr(
                object_expr=expr,
                index_expr=index_expr,
                span=SourceSpan(start=expr.span.start, end=rbracket.span.end),
            )
            continue

        return expr


def _parse_primary(stream: TokenStream) -> Expression:
    if stream.match(TokenKind.INT_LIT, TokenKind.FLOAT_LIT, TokenKind.STRING_LIT, TokenKind.TRUE, TokenKind.FALSE):
        token = stream.previous()
        return LiteralExpr(value=token.lexeme, span=token.span)

    if stream.match(TokenKind.NULL):
        return NullExpr(span=stream.previous().span)

    if stream.match(TokenKind.IDENT):
        token = stream.previous()
        return IdentifierExpr(name=token.lexeme, span=token.span)

    if stream.match(TokenKind.LPAREN):
        expr = _parse_expression(stream)
        stream.expect(TokenKind.RPAREN, "Expected ')' after expression")
        return expr

    raise ParserError("Expected expression", stream.peek().span)


def _is_cast_start(stream: TokenStream) -> bool:
    if stream.peek().kind != TokenKind.LPAREN:
        return False

    if not _is_type_token(stream.peek(1).kind):
        return False

    if stream.peek(2).kind != TokenKind.RPAREN:
        return False

    return _can_start_unary(stream.peek(3).kind)


def _is_type_token(kind: TokenKind) -> bool:
    return kind in {
        TokenKind.IDENT,
        TokenKind.I64,
        TokenKind.U64,
        TokenKind.U8,
        TokenKind.BOOL,
        TokenKind.DOUBLE,
        TokenKind.UNIT,
        TokenKind.OBJ,
        TokenKind.STR,
        TokenKind.VEC,
        TokenKind.MAP,
        TokenKind.BOXI64,
        TokenKind.BOXU64,
        TokenKind.BOXU8,
        TokenKind.BOXBOOL,
        TokenKind.BOXDOUBLE,
    }


def _can_start_unary(kind: TokenKind) -> bool:
    return kind in {
        TokenKind.BANG,
        TokenKind.MINUS,
        TokenKind.LPAREN,
        TokenKind.IDENT,
        TokenKind.INT_LIT,
        TokenKind.FLOAT_LIT,
        TokenKind.STRING_LIT,
        TokenKind.TRUE,
        TokenKind.FALSE,
        TokenKind.NULL,
    }
