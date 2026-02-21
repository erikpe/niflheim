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
    path: str
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
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span


class Lexer:
    def __init__(self, source: str, source_path: str = "<memory>"):
        self.source = source
        self.source_path = source_path
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

        if not is_float and not self._is_at_end() and self._peek() == "u":
            self._advance()

        lexeme = self.source[start.offset : self.index]
        kind = TokenKind.FLOAT_LIT if is_float else TokenKind.INT_LIT
        return Token(kind, lexeme, SourceSpan(start, self._pos()))

    def _read_string(self, start: SourcePos) -> Token:
        self._advance()

        while not self._is_at_end():
            ch = self._peek()
            if ch == "\n":
                raise LexerError("Unterminated string literal", SourceSpan(start, self._pos()))

            if ch == "\\":
                self._advance()

                if self._is_at_end():
                    raise LexerError("Unterminated string literal", SourceSpan(start, self._pos()))

                esc = self._peek()
                if esc in {'"', "\\", "n", "r", "t", "0"}:
                    self._advance()
                    continue

                if esc == "x":
                    self._advance()
                    first = self._peek()
                    second = self._peek_next()
                    if not self._is_hex_digit(first) or not self._is_hex_digit(second):
                        raise LexerError("Invalid string escape sequence", SourceSpan(start, self._pos()))
                    self._advance()
                    self._advance()
                    continue

                raise LexerError("Invalid string escape sequence", SourceSpan(start, self._pos()))

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
        return SourcePos(path=self.source_path, offset=self.index, line=self.line, column=self.column)

    @staticmethod
    def _is_ident_start(ch: str) -> bool:
        return ch.isalpha() or ch == "_"

    @staticmethod
    def _is_ident_part(ch: str) -> bool:
        return ch.isalnum() or ch == "_"

    @staticmethod
    def _is_hex_digit(ch: str) -> bool:
        return ch.isdigit() or ("a" <= ch <= "f") or ("A" <= ch <= "F")


def lex(source: str, source_path: str = "<memory>") -> list[Token]:
    return Lexer(source, source_path=source_path).lex()
