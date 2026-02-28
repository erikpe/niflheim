from __future__ import annotations

from enum import Enum


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
    PRIVATE = "PRIVATE"
    FN = "FN"
    VAR = "VAR"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
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
    SLASH = "SLASH"
    PERCENT = "PERCENT"
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


KEYWORDS: dict[str, TokenKind] = {
    "import": TokenKind.IMPORT,
    "export": TokenKind.EXPORT,
    "extern": TokenKind.EXTERN,
    "class": TokenKind.CLASS,
    "private": TokenKind.PRIVATE,
    "fn": TokenKind.FN,
    "var": TokenKind.VAR,
    "if": TokenKind.IF,
    "else": TokenKind.ELSE,
    "while": TokenKind.WHILE,
    "static": TokenKind.STATIC,
    "break": TokenKind.BREAK,
    "continue": TokenKind.CONTINUE,
    "return": TokenKind.RETURN,
    "i64": TokenKind.I64,
    "u64": TokenKind.U64,
    "u8": TokenKind.U8,
    "bool": TokenKind.BOOL,
    "double": TokenKind.DOUBLE,
    "unit": TokenKind.UNIT,
    "Obj": TokenKind.OBJ,
    "true": TokenKind.TRUE,
    "false": TokenKind.FALSE,
    "null": TokenKind.NULL,
}


TWO_CHAR_TOKENS: dict[str, TokenKind] = {
    "->": TokenKind.ARROW,
    "==": TokenKind.EQEQ,
    "!=": TokenKind.NEQ,
    "<=": TokenKind.LTE,
    ">=": TokenKind.GTE,
    "&&": TokenKind.ANDAND,
    "||": TokenKind.OROR,
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
