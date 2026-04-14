from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from compiler.common.span import SourceSpan
from compiler.frontend.ast_nodes import *
from compiler.frontend.parser_support import expect_symbol_name, ParserError, TokenStream
from compiler.frontend.tokens import Token, TokenKind


ParseTypeRef = Callable[[], TypeRefNode]
ParseExpression = Callable[[], Expression]
ParseBlockStmt = Callable[[], BlockStmt]


@dataclass(frozen=True)
class ClassMemberModifiers:
    is_private: bool
    is_final: bool
    is_override: bool
    start_token: Token | None


TopLevelDecl = ImportDecl | ClassDecl | InterfaceDecl | FunctionDecl


class DeclarationParser:
    def __init__(
        self,
        stream: TokenStream,
        *,
        parse_type_ref: ParseTypeRef,
        parse_expression: ParseExpression,
        parse_block_stmt: ParseBlockStmt,
    ) -> None:
        self.stream = stream
        self._parse_type_ref = parse_type_ref
        self._parse_expression = parse_expression
        self._parse_block_stmt = parse_block_stmt

    def parse_module(self) -> ModuleAst:
        imports: list[ImportDecl] = []
        classes: list[ClassDecl] = []
        functions: list[FunctionDecl] = []
        interfaces: list[InterfaceDecl] = []

        start = self.stream.peek().span.start
        while not self.stream.is_at_end():
            decl = self._parse_top_level_decl()
            if isinstance(decl, ImportDecl):
                imports.append(decl)
            elif isinstance(decl, ClassDecl):
                classes.append(decl)
            elif isinstance(decl, InterfaceDecl):
                interfaces.append(decl)
            else:
                functions.append(decl)

        end = self.stream.peek().span.end
        return ModuleAst(
            imports=imports,
            classes=classes,
            functions=functions,
            span=SourceSpan(start=start, end=end),
            interfaces=interfaces,
        )

    def _parse_top_level_decl(self) -> TopLevelDecl:
        if self.stream.match(TokenKind.EXPORT):
            return self._parse_exported_top_level_decl(self.stream.previous())

        if self.stream.match(TokenKind.IMPORT):
            return self._parse_import_decl(is_export=False, import_token=self.stream.previous())

        if self.stream.match(TokenKind.EXTERN):
            extern_token = self.stream.previous()
            fn_token = self.stream.expect(TokenKind.FN, "Expected 'fn' after 'extern'")
            return self._parse_extern_function_decl(is_export=False, fn_token=fn_token, extern_token=extern_token)

        if self.stream.match(TokenKind.CLASS):
            return self._parse_class_decl(is_export=False, class_token=self.stream.previous())

        if self.stream.match(TokenKind.INTERFACE):
            return self._parse_interface_decl(is_export=False, interface_token=self.stream.previous())

        if self.stream.match(TokenKind.FN):
            return self._parse_function_decl(is_export=False, fn_token=self.stream.previous())

        raise ParserError("Unexpected token at module scope", self.stream.peek().span)

    def _parse_exported_top_level_decl(self, export_token: Token) -> TopLevelDecl:
        if self.stream.match(TokenKind.IMPORT):
            return self._parse_import_decl(
                is_export=True, import_token=self.stream.previous(), export_token=export_token
            )

        if self.stream.match(TokenKind.CLASS):
            return self._parse_class_decl(is_export=True, class_token=self.stream.previous(), export_token=export_token)

        if self.stream.match(TokenKind.INTERFACE):
            return self._parse_interface_decl(
                is_export=True, interface_token=self.stream.previous(), export_token=export_token
            )

        if self.stream.match(TokenKind.FN):
            return self._parse_function_decl(is_export=True, fn_token=self.stream.previous(), export_token=export_token)

        if self.stream.match(TokenKind.EXTERN):
            extern_token = self.stream.previous()
            fn_token = self.stream.expect(TokenKind.FN, "Expected 'fn' after 'extern'")
            return self._parse_extern_function_decl(
                is_export=True, fn_token=fn_token, extern_token=extern_token, export_token=export_token
            )

        raise ParserError(
            "Expected 'import', 'class', 'interface', 'fn', or 'extern fn' after 'export'", self.stream.peek().span
        )

    def _parse_import_decl(
        self, *, is_export: bool, import_token: Token, export_token: Token | None = None
    ) -> ImportDecl:
        parts: list[str] = []
        first = self.stream.expect(TokenKind.IDENT, "Expected module path after import")
        parts.append(first.lexeme)

        while self.stream.match(TokenKind.DOT):
            part = expect_symbol_name(self.stream, "Expected identifier after '.' in module path")
            parts.append(part.lexeme)

        bind_path: list[str] | None = None
        if self.stream.match(TokenKind.AS):
            if self.stream.match(TokenKind.DOT):
                bind_path = []
            else:
                bind_path = [expect_symbol_name(self.stream, "Expected bind path after 'as'").lexeme]
                while self.stream.match(TokenKind.DOT):
                    bind_path.append(expect_symbol_name(self.stream, "Expected identifier after '.' in bind path").lexeme)

        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after import declaration")
        start_pos = export_token.span.start if export_token is not None else import_token.span.start
        return ImportDecl(
            module_path=parts,
            bind_path=bind_path,
            is_export=is_export,
            span=SourceSpan(start=start_pos, end=semicolon.span.end),
        )

    def _parse_class_decl(self, *, is_export: bool, class_token: Token, export_token: Token | None = None) -> ClassDecl:
        name_token = expect_symbol_name(self.stream, "Expected class name")
        base_class: TypeRefNode | None = None
        if self.stream.match(TokenKind.EXTENDS):
            base_class = self._parse_type_ref()
        implements: list[TypeRefNode] = []
        if self.stream.match(TokenKind.IMPLEMENTS):
            while True:
                implements.append(self._parse_type_ref())
                if not self.stream.match(TokenKind.COMMA):
                    break
        self.stream.expect(TokenKind.LBRACE, "Expected '{' after class name")

        fields: list[FieldDecl] = []
        methods: list[MethodDecl] = []
        constructors: list[ConstructorDecl] = []
        while not self.stream.check(TokenKind.RBRACE):
            if self.stream.is_at_end():
                raise ParserError("Unterminated class body", class_token.span)

            member = self._parse_class_member(class_token)
            if isinstance(member, FieldDecl):
                fields.append(member)
            elif isinstance(member, ConstructorDecl):
                constructors.append(member)
            else:
                methods.append(member)

        rbrace = self.stream.expect(TokenKind.RBRACE, "Expected '}' after class body")
        start_pos = export_token.span.start if export_token is not None else class_token.span.start
        return ClassDecl(
            name=name_token.lexeme,
            fields=fields,
            methods=methods,
            is_export=is_export,
            span=SourceSpan(start=start_pos, end=rbrace.span.end),
            base_class=base_class,
            implements=implements,
            constructors=constructors,
        )

    def _parse_class_member(self, class_token: Token) -> FieldDecl | ConstructorDecl | MethodDecl:
        modifiers = self._parse_class_member_modifiers()

        if self.stream.match(TokenKind.STATIC):
            if self.stream.check(TokenKind.CONSTRUCTOR):
                raise ParserError("'static' modifier is not allowed on constructors", self.stream.peek().span)
            return self._parse_static_method_decl(modifiers)

        if self.stream.match(TokenKind.CONSTRUCTOR):
            return self._parse_constructor_decl(modifiers)

        if self.stream.match(TokenKind.FN):
            return self._parse_instance_method_decl(modifiers)

        if self.stream.check(TokenKind.IDENT) and self.stream.peek(1).kind == TokenKind.COLON:
            return self._parse_field_decl(modifiers)

        raise ParserError("Expected field or method declaration in class body", self.stream.peek().span)

    def _parse_class_member_modifiers(self) -> ClassMemberModifiers:
        private_token: Token | None = None
        final_token: Token | None = None
        override_token: Token | None = None

        while True:
            if self.stream.match(TokenKind.PRIVATE):
                if private_token is not None:
                    raise ParserError("Duplicate 'private' modifier", self.stream.previous().span)
                private_token = self.stream.previous()
                continue
            if self.stream.match(TokenKind.FINAL):
                if final_token is not None:
                    raise ParserError("Duplicate 'final' modifier", self.stream.previous().span)
                final_token = self.stream.previous()
                continue
            if self.stream.match(TokenKind.OVERRIDE):
                if override_token is not None:
                    raise ParserError("Duplicate 'override' modifier", self.stream.previous().span)
                override_token = self.stream.previous()
                continue
            break

        start_token = private_token
        if start_token is None:
            start_token = final_token
        if start_token is None:
            start_token = override_token

        return ClassMemberModifiers(
            is_private=private_token is not None,
            is_final=final_token is not None,
            is_override=override_token is not None,
            start_token=start_token,
        )

    def _parse_static_method_decl(self, modifiers: ClassMemberModifiers) -> MethodDecl:
        if modifiers.is_final:
            raise ParserError("'final' modifier is only allowed on fields", modifiers.start_token.span)
        if modifiers.is_override:
            raise ParserError("'override' modifier is not allowed on static methods", modifiers.start_token.span)
        static_token = self.stream.previous()
        fn_token = self.stream.expect(TokenKind.FN, "Expected 'fn' after 'static' in class body")
        return self._parse_method_decl(
            fn_token=fn_token,
            is_static=True,
            is_private=modifiers.is_private,
            is_override=False,
            start_token=modifiers.start_token if modifiers.start_token is not None else static_token,
        )

    def _parse_instance_method_decl(self, modifiers: ClassMemberModifiers) -> MethodDecl:
        if modifiers.is_final:
            raise ParserError("'final' modifier is only allowed on fields", modifiers.start_token.span)
        return self._parse_method_decl(
            fn_token=self.stream.previous(),
            is_static=False,
            is_private=modifiers.is_private,
            is_override=modifiers.is_override,
            start_token=modifiers.start_token,
        )

    def _parse_constructor_decl(self, modifiers: ClassMemberModifiers) -> ConstructorDecl:
        if modifiers.is_final:
            raise ParserError("'final' modifier is not allowed on constructors", modifiers.start_token.span)
        if modifiers.is_override:
            raise ParserError("'override' modifier is not allowed on constructors", modifiers.start_token.span)
        constructor_token = self.stream.previous()
        params = self._parse_param_list("Expected '(' after 'constructor'")
        if self.stream.check(TokenKind.ARROW):
            raise ParserError("Constructors cannot declare a return type", self.stream.peek().span)
        body = self._parse_block_stmt()
        start = modifiers.start_token.span.start if modifiers.start_token is not None else constructor_token.span.start
        return ConstructorDecl(
            params=params,
            body=body,
            is_private=modifiers.is_private,
            span=SourceSpan(start=start, end=body.span.end),
        )

    def _parse_interface_decl(
        self, *, is_export: bool, interface_token: Token, export_token: Token | None = None
    ) -> InterfaceDecl:
        name_token = expect_symbol_name(self.stream, "Expected interface name")
        self.stream.expect(TokenKind.LBRACE, "Expected '{' after interface name")

        methods: list[InterfaceMethodDecl] = []
        while not self.stream.check(TokenKind.RBRACE):
            if self.stream.is_at_end():
                raise ParserError("Unterminated interface body", interface_token.span)
            fn_token = self.stream.expect(TokenKind.FN, "Expected method declaration in interface body")
            methods.append(self._parse_interface_method_decl(fn_token=fn_token))

        rbrace = self.stream.expect(TokenKind.RBRACE, "Expected '}' after interface body")
        start_pos = export_token.span.start if export_token is not None else interface_token.span.start
        return InterfaceDecl(
            name=name_token.lexeme,
            methods=methods,
            is_export=is_export,
            span=SourceSpan(start=start_pos, end=rbrace.span.end),
        )

    def _parse_interface_method_decl(self, *, fn_token: Token) -> InterfaceMethodDecl:
        name, params, return_type = self._parse_callable_signature()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after interface method signature")
        return InterfaceMethodDecl(
            name=name,
            params=params,
            return_type=return_type,
            span=SourceSpan(start=fn_token.span.start, end=semicolon.span.end),
        )

    def _parse_field_decl(self, modifiers: ClassMemberModifiers) -> FieldDecl:
        if modifiers.is_override:
            raise ParserError("'override' modifier is only allowed on methods", modifiers.start_token.span)
        name = self.stream.expect(TokenKind.IDENT, "Expected field name")
        self.stream.expect(TokenKind.COLON, "Expected ':' after field name")
        type_ref = self._parse_type_ref()
        initializer: Expression | None = None
        if self.stream.match(TokenKind.ASSIGN):
            initializer = self._parse_expression()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after field declaration")
        start = modifiers.start_token.span.start if modifiers.start_token is not None else name.span.start
        return FieldDecl(
            name=name.lexeme,
            type_ref=type_ref,
            initializer=initializer,
            is_private=modifiers.is_private,
            is_final=modifiers.is_final,
            span=SourceSpan(start=start, end=semicolon.span.end),
        )

    def _parse_method_decl(
        self,
        *,
        fn_token: Token,
        is_static: bool,
        is_private: bool,
        is_override: bool,
        start_token: Token | None = None,
    ) -> MethodDecl:
        name, params, return_type = self._parse_callable_signature()
        body = self._parse_block_stmt()
        return MethodDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            is_static=is_static,
            is_private=is_private,
            is_override=is_override,
            span=SourceSpan(
                start=(start_token.span.start if start_token is not None else fn_token.span.start), end=body.span.end
            ),
        )

    def _parse_function_decl(
        self, *, is_export: bool, fn_token: Token, export_token: Token | None = None
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
        self, *, is_export: bool, fn_token: Token, extern_token: Token, export_token: Token | None = None
    ) -> FunctionDecl:
        name, params, return_type = self._parse_callable_signature()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after extern function declaration")
        start_pos = export_token.span.start if export_token is not None else extern_token.span.start
        return FunctionDecl(
            name=name,
            params=params,
            return_type=return_type,
            body=None,
            is_export=is_export,
            is_extern=True,
            span=SourceSpan(start=start_pos, end=semicolon.span.end),
        )

    def _parse_callable_signature(self) -> tuple[str, list[ParamDecl], TypeRefNode]:
        name = self.stream.expect(TokenKind.IDENT, "Expected function name")
        params = self._parse_param_list("Expected '(' after function name")
        self.stream.expect(TokenKind.ARROW, "Expected '->' after parameter list")
        return_type = self._parse_type_ref()
        return name.lexeme, params, return_type

    def _parse_param_list(self, lparen_message: str) -> list[ParamDecl]:
        self.stream.expect(TokenKind.LPAREN, lparen_message)

        params: list[ParamDecl] = []
        if not self.stream.check(TokenKind.RPAREN):
            while True:
                params.append(self._parse_param())
                if not self.stream.match(TokenKind.COMMA):
                    break

        self.stream.expect(TokenKind.RPAREN, "Expected ')' after parameters")
        return params

    def _parse_param(self) -> ParamDecl:
        name = self.stream.expect(TokenKind.IDENT, "Expected parameter name")
        self.stream.expect(TokenKind.COLON, "Expected ':' after parameter name")
        type_ref = self._parse_type_ref()
        return ParamDecl(
            name=name.lexeme, type_ref=type_ref, span=SourceSpan(start=name.span.start, end=type_ref.span.end)
        )
