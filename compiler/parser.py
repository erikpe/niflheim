from __future__ import annotations

from dataclasses import dataclass

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
    raise NotImplementedError("parser not implemented yet")
