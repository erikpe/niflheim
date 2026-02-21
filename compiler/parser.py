from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import *
from compiler.lexer import SourceSpan, Token
from compiler.tokens import TYPE_NAME_TOKENS, TokenKind


UNARY_START_TOKENS: set[TokenKind] = {
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
    TokenKind.BOXI64,
    TokenKind.BOXU64,
    TokenKind.BOXU8,
    TokenKind.BOXBOOL,
    TokenKind.BOXDOUBLE,
}


BUILTIN_CALLABLE_TYPE_TOKENS: tuple[TokenKind, ...] = (
    TokenKind.VEC,
    TokenKind.BOXI64,
    TokenKind.BOXU64,
    TokenKind.BOXU8,
    TokenKind.BOXBOOL,
    TokenKind.BOXDOUBLE,
)


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


class Parser:
    def __init__(self, tokens: list[Token]):
        self.stream = TokenStream(tokens)

    def parse_module(self) -> ModuleAst:
        imports: list[ImportDecl] = []
        classes: list[ClassDecl] = []
        functions: list[FunctionDecl] = []

        start = self.stream.peek().span.start

        while not self.stream.is_at_end():
            if self.stream.match(TokenKind.IMPORT):
                imports.append(self._parse_import_decl(is_export=False, import_token=self.stream.previous()))
                continue

            if self.stream.match(TokenKind.EXPORT):
                export_token = self.stream.previous()
                if self.stream.match(TokenKind.IMPORT):
                    imports.append(self._parse_import_decl(is_export=True, import_token=self.stream.previous(), export_token=export_token))
                    continue

                if self.stream.match(TokenKind.CLASS):
                    classes.append(self._parse_class_decl(is_export=True, class_token=self.stream.previous(), export_token=export_token))
                    continue

                if self.stream.match(TokenKind.FN):
                    functions.append(self._parse_function_decl(is_export=True, fn_token=self.stream.previous(), export_token=export_token))
                    continue

                if self.stream.match(TokenKind.EXTERN):
                    extern_token = self.stream.previous()
                    fn_token = self.stream.expect(TokenKind.FN, "Expected 'fn' after 'extern'")
                    functions.append(
                        self._parse_extern_function_decl(
                            is_export=True,
                            fn_token=fn_token,
                            extern_token=extern_token,
                            export_token=export_token,
                        )
                    )
                    continue

                raise ParserError("Expected 'import', 'class', 'fn', or 'extern fn' after 'export'", self.stream.peek().span)

            if self.stream.match(TokenKind.EXTERN):
                extern_token = self.stream.previous()
                fn_token = self.stream.expect(TokenKind.FN, "Expected 'fn' after 'extern'")
                functions.append(
                    self._parse_extern_function_decl(
                        is_export=False,
                        fn_token=fn_token,
                        extern_token=extern_token,
                    )
                )
                continue

            if self.stream.match(TokenKind.CLASS):
                classes.append(self._parse_class_decl(is_export=False, class_token=self.stream.previous()))
                continue

            if self.stream.match(TokenKind.FN):
                functions.append(self._parse_function_decl(is_export=False, fn_token=self.stream.previous()))
                continue

            raise ParserError("Unexpected token at module scope", self.stream.peek().span)

        end = self.stream.peek().span.end
        return ModuleAst(
            imports=imports,
            classes=classes,
            functions=functions,
            span=SourceSpan(start=start, end=end),
        )

    def parse_expression_root(self) -> Expression:
        expr = self._parse_expression()
        self.stream.expect(TokenKind.EOF, "Expected end of expression")
        return expr

    def _parse_import_decl(
        self,
        *,
        is_export: bool,
        import_token: Token,
        export_token: Token | None = None,
    ) -> ImportDecl:
        parts: list[str] = []
        first = self.stream.expect(TokenKind.IDENT, "Expected module path after import")
        parts.append(first.lexeme)

        while self.stream.match(TokenKind.DOT):
            part = self.stream.expect(TokenKind.IDENT, "Expected identifier after '.' in module path")
            parts.append(part.lexeme)

        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after import declaration")
        start_pos = export_token.span.start if export_token is not None else import_token.span.start
        span = SourceSpan(start=start_pos, end=semicolon.span.end)
        return ImportDecl(module_path=parts, is_export=is_export, span=span)

    def _parse_class_decl(
        self,
        *,
        is_export: bool,
        class_token: Token,
        export_token: Token | None = None,
    ) -> ClassDecl:
        name_token = self.stream.expect(TokenKind.IDENT, "Expected class name")
        self.stream.expect(TokenKind.LBRACE, "Expected '{' after class name")

        fields: list[FieldDecl] = []
        methods: list[MethodDecl] = []

        while not self.stream.check(TokenKind.RBRACE):
            if self.stream.is_at_end():
                raise ParserError("Unterminated class body", class_token.span)

            if self.stream.match(TokenKind.FN):
                methods.append(self._parse_method_decl(fn_token=self.stream.previous()))
                continue

            if self.stream.check(TokenKind.IDENT) and self.stream.peek(1).kind == TokenKind.COLON:
                fields.append(self._parse_field_decl())
                continue

            raise ParserError("Expected field or method declaration in class body", self.stream.peek().span)

        rbrace = self.stream.expect(TokenKind.RBRACE, "Expected '}' after class body")
        start_pos = export_token.span.start if export_token is not None else class_token.span.start
        span = SourceSpan(start=start_pos, end=rbrace.span.end)
        return ClassDecl(
            name=name_token.lexeme,
            fields=fields,
            methods=methods,
            is_export=is_export,
            span=span,
        )

    def _parse_field_decl(self) -> FieldDecl:
        name = self.stream.expect(TokenKind.IDENT, "Expected field name")
        self.stream.expect(TokenKind.COLON, "Expected ':' after field name")
        type_ref = self._parse_type_ref()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after field declaration")
        return FieldDecl(
            name=name.lexeme,
            type_ref=type_ref,
            span=SourceSpan(start=name.span.start, end=semicolon.span.end),
        )

    def _parse_method_decl(self, *, fn_token: Token) -> MethodDecl:
        name, params, return_type = self._parse_callable_signature()
        body = self._parse_block_stmt()
        return MethodDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            span=SourceSpan(start=fn_token.span.start, end=body.span.end),
        )

    def _parse_function_decl(
        self,
        *,
        is_export: bool,
        fn_token: Token,
        export_token: Token | None = None,
    ) -> FunctionDecl:
        name, params, return_type = self._parse_callable_signature()
        body = self._parse_block_stmt()
        start_pos = export_token.span.start if export_token is not None else fn_token.span.start
        return FunctionDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            is_export=is_export,
            is_extern=False,
            span=SourceSpan(start=start_pos, end=body.span.end),
        )

    def _parse_extern_function_decl(
        self,
        *,
        is_export: bool,
        fn_token: Token,
        extern_token: Token,
        export_token: Token | None = None,
    ) -> FunctionDecl:
        name, params, return_type = self._parse_callable_signature()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after extern function declaration")
        if export_token is not None:
            start_pos = export_token.span.start
        else:
            start_pos = extern_token.span.start
        return FunctionDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=None,
            is_export=is_export,
            is_extern=True,
            span=SourceSpan(start=start_pos, end=semicolon.span.end),
        )

    def _parse_callable_signature(self) -> tuple[str, list[ParamDecl], TypeRef]:
        name = self.stream.expect(TokenKind.IDENT, "Expected function name")
        self.stream.expect(TokenKind.LPAREN, "Expected '(' after function name")

        params: list[ParamDecl] = []
        if not self.stream.check(TokenKind.RPAREN):
            while True:
                params.append(self._parse_param())
                if not self.stream.match(TokenKind.COMMA):
                    break

        self.stream.expect(TokenKind.RPAREN, "Expected ')' after parameters")
        self.stream.expect(TokenKind.ARROW, "Expected '->' after parameter list")
        return_type = self._parse_type_ref()
        return name.lexeme, params, return_type

    def _parse_param(self) -> ParamDecl:
        name = self.stream.expect(TokenKind.IDENT, "Expected parameter name")
        self.stream.expect(TokenKind.COLON, "Expected ':' after parameter name")
        type_ref = self._parse_type_ref()
        return ParamDecl(
            name=name.lexeme,
            type_ref=type_ref,
            span=SourceSpan(start=name.span.start, end=type_ref.span.end),
        )

    def _parse_type_ref(self) -> TypeRef:
        token = self.stream.peek()
        if token.kind not in TYPE_NAME_TOKENS:
            raise ParserError("Expected type name", token.span)
        self.stream.advance()

        if token.kind != TokenKind.IDENT:
            return TypeRef(name=token.lexeme, span=token.span)

        parts = [token.lexeme]
        end = token.span.end
        while self.stream.match(TokenKind.DOT):
            segment = self.stream.expect(TokenKind.IDENT, "Expected type name after '.' in qualified type")
            parts.append(segment.lexeme)
            end = segment.span.end

        return TypeRef(
            name=".".join(parts),
            span=SourceSpan(start=token.span.start, end=end),
        )

    def _parse_block_stmt(self) -> BlockStmt:
        lbrace = self.stream.expect(TokenKind.LBRACE, "Expected '{' to start block")
        statements: list[Statement] = []

        while not self.stream.check(TokenKind.RBRACE):
            if self.stream.is_at_end():
                raise ParserError("Unterminated block", self.stream.peek().span)
            statements.append(self._parse_statement())

        rbrace = self.stream.expect(TokenKind.RBRACE, "Expected '}' after block")
        return BlockStmt(statements=statements, span=SourceSpan(start=lbrace.span.start, end=rbrace.span.end))

    def _parse_statement(self) -> Statement:
        if self.stream.match(TokenKind.VAR):
            return self._parse_var_decl_stmt(var_token=self.stream.previous())

        if self.stream.match(TokenKind.IF):
            return self._parse_if_stmt(if_token=self.stream.previous())

        if self.stream.match(TokenKind.WHILE):
            return self._parse_while_stmt(while_token=self.stream.previous())

        if self.stream.match(TokenKind.RETURN):
            return self._parse_return_stmt(return_token=self.stream.previous())

        if self.stream.check(TokenKind.LBRACE):
            return self._parse_block_stmt()

        return self._parse_expr_or_assign_stmt()

    def _parse_var_decl_stmt(self, *, var_token: Token) -> VarDeclStmt:
        name = self.stream.expect(TokenKind.IDENT, "Expected variable name after 'var'")
        self.stream.expect(TokenKind.COLON, "Expected ':' after variable name")
        type_ref = self._parse_type_ref()
        initializer: Expression | None = None

        if self.stream.match(TokenKind.ASSIGN):
            initializer = self._parse_expression()

        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after variable declaration")
        return VarDeclStmt(
            name=name.lexeme,
            type_ref=type_ref,
            initializer=initializer,
            span=SourceSpan(start=var_token.span.start, end=semicolon.span.end),
        )

    def _parse_if_stmt(self, *, if_token: Token) -> IfStmt:
        condition = self._parse_expression()
        then_branch = self._parse_block_stmt()
        else_branch: BlockStmt | IfStmt | None = None

        if self.stream.match(TokenKind.ELSE):
            if self.stream.match(TokenKind.IF):
                else_branch = self._parse_if_stmt(if_token=self.stream.previous())
            elif self.stream.check(TokenKind.LBRACE):
                else_branch = self._parse_block_stmt()
            else:
                raise ParserError("Expected 'if' or '{' after 'else'", self.stream.peek().span)

        end_pos = else_branch.span.end if else_branch is not None else then_branch.span.end
        return IfStmt(
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch,
            span=SourceSpan(start=if_token.span.start, end=end_pos),
        )

    def _parse_while_stmt(self, *, while_token: Token) -> WhileStmt:
        condition = self._parse_expression()
        body = self._parse_block_stmt()
        return WhileStmt(
            condition=condition,
            body=body,
            span=SourceSpan(start=while_token.span.start, end=body.span.end),
        )

    def _parse_return_stmt(self, *, return_token: Token) -> ReturnStmt:
        value: Expression | None = None
        if not self.stream.check(TokenKind.SEMICOLON):
            value = self._parse_expression()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after return statement")
        return ReturnStmt(value=value, span=SourceSpan(start=return_token.span.start, end=semicolon.span.end))

    def _parse_expr_or_assign_stmt(self) -> Statement:
        expr = self._parse_expression()
        if self.stream.match(TokenKind.ASSIGN):
            if not self._is_assignable_target(expr):
                raise ParserError("Invalid assignment target", expr.span)
            value = self._parse_expression()
            semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after assignment")
            return AssignStmt(
                target=expr,
                value=value,
                span=SourceSpan(start=expr.span.start, end=semicolon.span.end),
            )

        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after expression statement")
        return ExprStmt(expression=expr, span=SourceSpan(start=expr.span.start, end=semicolon.span.end))

    @staticmethod
    def _is_assignable_target(expr: Expression) -> bool:
        return isinstance(expr, (IdentifierExpr, FieldAccessExpr, IndexExpr))

    def _parse_expression(self) -> Expression:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> Expression:
        expr = self._parse_logical_and()
        while self.stream.match(TokenKind.OROR):
            op = self.stream.previous()
            right = self._parse_logical_and()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_logical_and(self) -> Expression:
        expr = self._parse_equality()
        while self.stream.match(TokenKind.ANDAND):
            op = self.stream.previous()
            right = self._parse_equality()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_equality(self) -> Expression:
        expr = self._parse_comparison()
        while self.stream.match(TokenKind.EQEQ, TokenKind.NEQ):
            op = self.stream.previous()
            right = self._parse_comparison()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_comparison(self) -> Expression:
        expr = self._parse_additive()
        while self.stream.match(TokenKind.LT, TokenKind.LTE, TokenKind.GT, TokenKind.GTE):
            op = self.stream.previous()
            right = self._parse_additive()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_additive(self) -> Expression:
        expr = self._parse_multiplicative()
        while self.stream.match(TokenKind.PLUS, TokenKind.MINUS):
            op = self.stream.previous()
            right = self._parse_multiplicative()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_multiplicative(self) -> Expression:
        expr = self._parse_unary()
        while self.stream.match(TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT):
            op = self.stream.previous()
            right = self._parse_unary()
            expr = BinaryExpr(
                left=expr,
                operator=op.lexeme,
                right=right,
                span=SourceSpan(start=expr.span.start, end=right.span.end),
            )
        return expr

    def _parse_unary(self) -> Expression:
        if self.stream.match(TokenKind.BANG, TokenKind.MINUS):
            op = self.stream.previous()
            operand = self._parse_unary()
            return UnaryExpr(
                operator=op.lexeme,
                operand=operand,
                span=SourceSpan(start=op.span.start, end=operand.span.end),
            )

        if self._is_cast_start():
            lparen = self.stream.expect(TokenKind.LPAREN, "Expected '(' to start cast")
            type_ref = self._parse_type_ref()
            self.stream.expect(TokenKind.RPAREN, "Expected ')' after cast type")
            operand = self._parse_unary()
            return CastExpr(
                type_ref=type_ref,
                operand=operand,
                span=SourceSpan(start=lparen.span.start, end=operand.span.end),
            )

        return self._parse_postfix()

    def _parse_postfix(self) -> Expression:
        expr = self._parse_primary()

        while True:
            if self.stream.match(TokenKind.LPAREN):
                args: list[Expression] = []
                if not self.stream.check(TokenKind.RPAREN):
                    while True:
                        args.append(self._parse_expression())
                        if not self.stream.match(TokenKind.COMMA):
                            break

                rparen = self.stream.expect(TokenKind.RPAREN, "Expected ')' after arguments")
                expr = CallExpr(
                    callee=expr,
                    arguments=args,
                    span=SourceSpan(start=expr.span.start, end=rparen.span.end),
                )
                continue

            if self.stream.match(TokenKind.DOT):
                field = self.stream.expect(TokenKind.IDENT, "Expected field name after '.'")
                expr = FieldAccessExpr(
                    object_expr=expr,
                    field_name=field.lexeme,
                    span=SourceSpan(start=expr.span.start, end=field.span.end),
                )
                continue

            if self.stream.match(TokenKind.LBRACKET):
                index_expr = self._parse_expression()
                rbracket = self.stream.expect(TokenKind.RBRACKET, "Expected ']' after index expression")
                expr = IndexExpr(
                    object_expr=expr,
                    index_expr=index_expr,
                    span=SourceSpan(start=expr.span.start, end=rbracket.span.end),
                )
                continue

            return expr

    def _parse_primary(self) -> Expression:
        if self.stream.match(TokenKind.INT_LIT, TokenKind.FLOAT_LIT, TokenKind.STRING_LIT, TokenKind.TRUE, TokenKind.FALSE):
            token = self.stream.previous()
            return LiteralExpr(value=token.lexeme, span=token.span)

        if self.stream.match(TokenKind.NULL):
            return NullExpr(span=self.stream.previous().span)

        if self.stream.match(TokenKind.IDENT, *BUILTIN_CALLABLE_TYPE_TOKENS):
            token = self.stream.previous()
            return IdentifierExpr(name=token.lexeme, span=token.span)

        if self.stream.match(TokenKind.LPAREN):
            expr = self._parse_expression()
            self.stream.expect(TokenKind.RPAREN, "Expected ')' after expression")
            return expr

        raise ParserError("Expected expression", self.stream.peek().span)

    def _is_cast_start(self) -> bool:
        if self.stream.peek().kind != TokenKind.LPAREN:
            return False

        lookahead = 1
        if self.stream.peek(lookahead).kind not in TYPE_NAME_TOKENS:
            return False
        first_type = self.stream.peek(lookahead)
        lookahead += 1

        if first_type.kind == TokenKind.IDENT:
            while self.stream.peek(lookahead).kind == TokenKind.DOT:
                if self.stream.peek(lookahead + 1).kind != TokenKind.IDENT:
                    return False
                lookahead += 2

        if self.stream.peek(lookahead).kind != TokenKind.RPAREN:
            return False
        lookahead += 1

        return self.stream.peek(lookahead).kind in UNARY_START_TOKENS


def parse(tokens: list[Token]) -> ModuleAst:
    return Parser(tokens).parse_module()


def parse_expression(tokens: list[Token]) -> Expression:
    return Parser(tokens).parse_expression_root()
