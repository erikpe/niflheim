from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from compiler.common.span import SourceSpan
from compiler.common.type_names import *


class TokenKind(str, Enum):
    EOF = "EOF"

    IDENT = "IDENT"
    INT_LIT = "INT_LIT"
    FLOAT_LIT = "FLOAT_LIT"
    STRING_LIT = "STRING_LIT"
    CHAR_LIT = "CHAR_LIT"

    IMPORT = "IMPORT"
    EXPORT = "EXPORT"
    EXTERN = "EXTERN"
    CLASS = "CLASS"
    CONSTRUCTOR = "CONSTRUCTOR"
    INTERFACE = "INTERFACE"
    IMPLEMENTS = "IMPLEMENTS"
    PRIVATE = "PRIVATE"
    FINAL = "FINAL"
    FN = "FN"
    VAR = "VAR"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    IN = "IN"
    IS = "IS"
    STATIC = "STATIC"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    RETURN = "RETURN"

    I64 = "I64"
    U64 = "U64"
    U8 = "U8"
    BOOL = "BOOL"
    DOUBLE = "DOUBLE"
    UNIT = "UNIT"

    OBJ = "OBJ"

    TRUE = "TRUE"
    FALSE = "FALSE"
    NULL = "NULL"

    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    SEMICOLON = "SEMICOLON"
    DOT = "DOT"
    COLON = "COLON"

    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    POW = "POW"
    SLASH = "SLASH"
    PERCENT = "PERCENT"
    AMP = "AMP"
    PIPE = "PIPE"
    CARET = "CARET"
    LSHIFT = "LSHIFT"
    RSHIFT = "RSHIFT"
    TILDE = "TILDE"
    ASSIGN = "ASSIGN"
    BANG = "BANG"

    EQEQ = "EQEQ"
    NEQ = "NEQ"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    ANDAND = "ANDAND"
    OROR = "OROR"
    ARROW = "ARROW"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    lexeme: str
    span: SourceSpan


KEYWORDS: dict[str, TokenKind] = {
    "import": TokenKind.IMPORT,
    "export": TokenKind.EXPORT,
    "extern": TokenKind.EXTERN,
    "class": TokenKind.CLASS,
    "constructor": TokenKind.CONSTRUCTOR,
    "interface": TokenKind.INTERFACE,
    "implements": TokenKind.IMPLEMENTS,
    "private": TokenKind.PRIVATE,
    "final": TokenKind.FINAL,
    "fn": TokenKind.FN,
    "var": TokenKind.VAR,
    "if": TokenKind.IF,
    "else": TokenKind.ELSE,
    "while": TokenKind.WHILE,
    "for": TokenKind.FOR,
    "in": TokenKind.IN,
    "is": TokenKind.IS,
    "static": TokenKind.STATIC,
    "break": TokenKind.BREAK,
    "continue": TokenKind.CONTINUE,
    "return": TokenKind.RETURN,
    TYPE_NAME_I64: TokenKind.I64,
    TYPE_NAME_U64: TokenKind.U64,
    TYPE_NAME_U8: TokenKind.U8,
    TYPE_NAME_BOOL: TokenKind.BOOL,
    TYPE_NAME_DOUBLE: TokenKind.DOUBLE,
    TYPE_NAME_UNIT: TokenKind.UNIT,
    TYPE_NAME_OBJ: TokenKind.OBJ,
    "true": TokenKind.TRUE,
    "false": TokenKind.FALSE,
    TYPE_NAME_NULL: TokenKind.NULL,
}


TWO_CHAR_TOKENS: dict[str, TokenKind] = {
    "->": TokenKind.ARROW,
    "==": TokenKind.EQEQ,
    "!=": TokenKind.NEQ,
    "<=": TokenKind.LTE,
    ">=": TokenKind.GTE,
    "&&": TokenKind.ANDAND,
    "||": TokenKind.OROR,
    "<<": TokenKind.LSHIFT,
    ">>": TokenKind.RSHIFT,
    "**": TokenKind.POW,
}


ONE_CHAR_TOKENS: dict[str, TokenKind] = {
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
    ",": TokenKind.COMMA,
    ";": TokenKind.SEMICOLON,
    ".": TokenKind.DOT,
    ":": TokenKind.COLON,
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "&": TokenKind.AMP,
    "|": TokenKind.PIPE,
    "^": TokenKind.CARET,
    "~": TokenKind.TILDE,
    "=": TokenKind.ASSIGN,
    "!": TokenKind.BANG,
    "<": TokenKind.LT,
    ">": TokenKind.GT,
}


TYPE_NAME_TOKENS: set[TokenKind] = {
    TokenKind.IDENT,
    TokenKind.I64,
    TokenKind.U64,
    TokenKind.U8,
    TokenKind.BOOL,
    TokenKind.DOUBLE,
    TokenKind.UNIT,
    TokenKind.OBJ,
}


UNARY_START_TOKENS: set[TokenKind] = {
    TokenKind.BANG,
    TokenKind.MINUS,
    TokenKind.TILDE,
    TokenKind.LPAREN,
    TokenKind.IDENT,
    TokenKind.INT_LIT,
    TokenKind.FLOAT_LIT,
    TokenKind.STRING_LIT,
    TokenKind.CHAR_LIT,
    TokenKind.TRUE,
    TokenKind.FALSE,
    TokenKind.NULL,
}
