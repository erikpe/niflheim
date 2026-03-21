from __future__ import annotations

from compiler.frontend.ast_nodes import *
from compiler.frontend.declaration_parser import DeclarationParser
from compiler.frontend.expression_parser import ExpressionParser
from compiler.frontend.parser_sugar import ParserSugar
from compiler.frontend.parser_support import ParserError, TokenStream
from compiler.frontend.statement_parser import StatementParser
from compiler.frontend.type_parser import parse_type_ref
from compiler.frontend.tokens import Token, TokenKind


class Parser:
    def __init__(self, tokens: list[Token]):
        self.stream = TokenStream(tokens)
        self.sugar = ParserSugar()

    def parse_module(self) -> ModuleAst:
        return DeclarationParser(
            self.stream,
            parse_type_ref=self._parse_type_ref,
            parse_expression=self._parse_expression,
            parse_block_stmt=self._parse_block_stmt,
        ).parse_module()

    def parse_expression_root(self) -> Expression:
        expr = self._parse_expression()
        self.stream.expect(TokenKind.EOF, "Expected end of expression")
        return expr

    def _statement_parser(self) -> StatementParser:
        return StatementParser(
            self.stream, parse_type_ref=self._parse_type_ref, parse_expression=self._parse_expression, sugar=self.sugar
        )

    def _expression_parser(self) -> ExpressionParser:
        return ExpressionParser(self.stream, parse_type_ref=self._parse_type_ref)

    def _parse_type_ref(self) -> TypeRefNode:
        return parse_type_ref(self.stream)

    def _parse_block_stmt(self) -> BlockStmt:
        return self._statement_parser().parse_block_stmt()

    def _parse_statement(self) -> Statement:
        return self._statement_parser().parse_statement()

    def _parse_expression(self) -> Expression:
        return self._expression_parser().parse_expression()


def parse(tokens: list[Token]) -> ModuleAst:
    return Parser(tokens).parse_module()


def parse_expression(tokens: list[Token]) -> Expression:
    return Parser(tokens).parse_expression_root()
