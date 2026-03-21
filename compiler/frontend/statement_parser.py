from __future__ import annotations

from typing import Callable

from compiler.common.span import SourceSpan
from compiler.frontend.ast_nodes import *
from compiler.frontend.lexer import Token
from compiler.frontend.parser_sugar import ParserSugar, try_build_slice_write_stmt
from compiler.frontend.parser_support import ParserError, TokenStream
from compiler.frontend.tokens import TokenKind


ParseTypeRef = Callable[[], TypeRefNode]
ParseExpression = Callable[[], Expression]


class StatementParser:
    def __init__(
        self,
        stream: TokenStream,
        *,
        parse_type_ref: ParseTypeRef,
        parse_expression: ParseExpression,
        sugar: ParserSugar,
    ) -> None:
        self.stream = stream
        self._parse_type_ref = parse_type_ref
        self._parse_expression = parse_expression
        self._sugar = sugar

    def parse_block_stmt(self) -> BlockStmt:
        lbrace = self.stream.expect(TokenKind.LBRACE, "Expected '{' to start block")
        statements: list[Statement] = []

        while not self.stream.check(TokenKind.RBRACE):
            if self.stream.is_at_end():
                raise ParserError("Unterminated block", self.stream.peek().span)
            statements.append(self.parse_statement())

        rbrace = self.stream.expect(TokenKind.RBRACE, "Expected '}' after block")
        return BlockStmt(statements=statements, span=SourceSpan(start=lbrace.span.start, end=rbrace.span.end))

    def parse_statement(self) -> Statement:
        if self.stream.match(TokenKind.VAR):
            return self._parse_var_decl_stmt(var_token=self.stream.previous())

        if self.stream.match(TokenKind.IF):
            return self._parse_if_stmt(if_token=self.stream.previous())

        if self.stream.match(TokenKind.WHILE):
            return self._parse_while_stmt(while_token=self.stream.previous())

        if self.stream.match(TokenKind.FOR):
            return self._parse_for_in_stmt(for_token=self.stream.previous())

        if self.stream.match(TokenKind.RETURN):
            return self._parse_return_stmt(return_token=self.stream.previous())

        if self.stream.match(TokenKind.BREAK):
            return self._parse_break_stmt(break_token=self.stream.previous())

        if self.stream.match(TokenKind.CONTINUE):
            return self._parse_continue_stmt(continue_token=self.stream.previous())

        if self.stream.check(TokenKind.LBRACE):
            return self.parse_block_stmt()

        if self.stream.check(TokenKind.FN):
            raise ParserError("Nested functions/closures are not supported in MVP", self.stream.peek().span)

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
        then_branch = self.parse_block_stmt()
        else_branch: BlockStmt | IfStmt | None = None

        if self.stream.match(TokenKind.ELSE):
            if self.stream.match(TokenKind.IF):
                else_branch = self._parse_if_stmt(if_token=self.stream.previous())
            elif self.stream.check(TokenKind.LBRACE):
                else_branch = self.parse_block_stmt()
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
        body = self.parse_block_stmt()
        return WhileStmt(
            condition=condition, body=body, span=SourceSpan(start=while_token.span.start, end=body.span.end)
        )

    def _parse_for_in_stmt(self, *, for_token: Token) -> ForInStmt:
        element_token = self.stream.expect(TokenKind.IDENT, "Expected loop variable name after 'for'")
        self.stream.expect(TokenKind.IN, "Expected 'in' after loop variable name")
        collection_expr = self._parse_expression()
        body = self.parse_block_stmt()
        return self._sugar.build_for_in_stmt(
            for_token=for_token, element_token=element_token, collection_expr=collection_expr, body=body
        )

    def _parse_return_stmt(self, *, return_token: Token) -> ReturnStmt:
        value: Expression | None = None
        if not self.stream.check(TokenKind.SEMICOLON):
            value = self._parse_expression()
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after return statement")
        return ReturnStmt(value=value, span=SourceSpan(start=return_token.span.start, end=semicolon.span.end))

    def _parse_break_stmt(self, *, break_token: Token) -> BreakStmt:
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after break statement")
        return BreakStmt(span=SourceSpan(start=break_token.span.start, end=semicolon.span.end))

    def _parse_continue_stmt(self, *, continue_token: Token) -> ContinueStmt:
        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after continue statement")
        return ContinueStmt(span=SourceSpan(start=continue_token.span.start, end=semicolon.span.end))

    def _parse_expr_or_assign_stmt(self) -> Statement:
        expr = self._parse_expression()
        if self.stream.match(TokenKind.ASSIGN):
            value = self._parse_expression()
            semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after assignment")

            slice_write_stmt = try_build_slice_write_stmt(expr, value, semicolon.span.end)
            if slice_write_stmt is not None:
                return slice_write_stmt

            if not self._is_assignable_target(expr):
                raise ParserError("Invalid assignment target", expr.span)
            return AssignStmt(target=expr, value=value, span=SourceSpan(start=expr.span.start, end=semicolon.span.end))

        semicolon = self.stream.expect(TokenKind.SEMICOLON, "Expected ';' after expression statement")
        return ExprStmt(expression=expr, span=SourceSpan(start=expr.span.start, end=semicolon.span.end))

    @staticmethod
    def _is_assignable_target(expr: Expression) -> bool:
        return isinstance(expr, (IdentifierExpr, FieldAccessExpr, IndexExpr))
