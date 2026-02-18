from __future__ import annotations

from dataclasses import dataclass
from compiler.tokens import (
    KEYWORDS,
    ONE_CHAR_TOKENS,
    TWO_CHAR_TOKENS,
    TokenKind,
)


@dataclass(frozen=True)
class SourcePos:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceSpan:
    start: SourcePos
    end: SourcePos


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    lexeme: str
    span: SourceSpan


class LexerError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at line {span.start.line}, column {span.start.column}")
        self.message = message
        self.span = span


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.length = len(source)
        self.index = 0
        self.line = 1
        self.column = 1

    def lex(self) -> list[Token]:
        tokens: list[Token] = []

        while not self._is_at_end():
            self._skip_whitespace_and_comments()
            if self._is_at_end():
                break

            start = self._pos()

            if self._is_ident_start(self._peek()):
                tokens.append(self._read_identifier(start))
                continue

            if self._peek().isdigit():
                tokens.append(self._read_number(start))
                continue

            if self._peek() == '"':
                tokens.append(self._read_string(start))
                continue

            two = self.source[self.index : self.index + 2]
            if two in TWO_CHAR_TOKENS:
                self._advance()
                self._advance()
                tokens.append(Token(TWO_CHAR_TOKENS[two], two, SourceSpan(start, self._pos())))
                continue

            one = self._peek()
            token_kind = ONE_CHAR_TOKENS.get(one)
            if token_kind is not None:
                self._advance()
                tokens.append(Token(token_kind, one, SourceSpan(start, self._pos())))
                continue

            raise LexerError(f"Unexpected character '{one}'", SourceSpan(start, start))

        eof_pos = self._pos()
        tokens.append(Token(TokenKind.EOF, "", SourceSpan(eof_pos, eof_pos)))
        return tokens

    def _skip_whitespace_and_comments(self) -> None:
        while not self._is_at_end():
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
                continue

            if ch == "/" and self._peek_next() == "/":
                self._advance()
                self._advance()
                while not self._is_at_end() and self._peek() != "\n":
                    self._advance()
                continue

            return

    def _read_identifier(self, start: SourcePos) -> Token:
        while not self._is_at_end() and self._is_ident_part(self._peek()):
            self._advance()

        lexeme = self.source[start.offset : self.index]
        kind = KEYWORDS.get(lexeme, TokenKind.IDENT)
        return Token(kind, lexeme, SourceSpan(start, self._pos()))

    def _read_number(self, start: SourcePos) -> Token:
        while not self._is_at_end() and self._peek().isdigit():
            self._advance()

        is_float = False
        if (
            not self._is_at_end()
            and self._peek() == "."
            and self._peek_next().isdigit()
        ):
            is_float = True
            self._advance()
            while not self._is_at_end() and self._peek().isdigit():
                self._advance()

        lexeme = self.source[start.offset : self.index]
        kind = TokenKind.FLOAT_LIT if is_float else TokenKind.INT_LIT
        return Token(kind, lexeme, SourceSpan(start, self._pos()))

    def _read_string(self, start: SourcePos) -> Token:
        self._advance()
        escaped = False

        while not self._is_at_end():
            ch = self._peek()
            if ch == "\n":
                raise LexerError("Unterminated string literal", SourceSpan(start, self._pos()))

            if escaped:
                escaped = False
                self._advance()
                continue

            if ch == "\\":
                escaped = True
                self._advance()
                continue

            if ch == '"':
                self._advance()
                lexeme = self.source[start.offset : self.index]
                return Token(TokenKind.STRING_LIT, lexeme, SourceSpan(start, self._pos()))

            self._advance()

        raise LexerError("Unterminated string literal", SourceSpan(start, self._pos()))

    def _is_at_end(self) -> bool:
        return self.index >= self.length

    def _peek(self) -> str:
        return "\0" if self._is_at_end() else self.source[self.index]

    def _peek_next(self) -> str:
        next_index = self.index + 1
        return "\0" if next_index >= self.length else self.source[next_index]

    def _advance(self) -> str:
        ch = self.source[self.index]
        self.index += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _pos(self) -> SourcePos:
        return SourcePos(offset=self.index, line=self.line, column=self.column)

    @staticmethod
    def _is_ident_start(ch: str) -> bool:
        return ch.isalpha() or ch == "_"

    @staticmethod
    def _is_ident_part(ch: str) -> bool:
        return ch.isalnum() or ch == "_"


def lex(source: str) -> list[Token]:
    return Lexer(source).lex()
