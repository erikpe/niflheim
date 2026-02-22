from __future__ import annotations

from dataclasses import dataclass

from compiler.lexer import SourceSpan


__all__ = [
    "PRIMITIVE_TYPE_NAMES",
    "REFERENCE_BUILTIN_TYPE_NAMES",
    "NUMERIC_TYPE_NAMES",
    "BUILTIN_INDEX_RESULT_TYPE_NAMES",
    "TypeInfo",
    "FunctionSig",
    "ClassInfo",
    "TypeCheckError",
]


PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
REFERENCE_BUILTIN_TYPE_NAMES = {
    "Obj",
    "Vec",
    "Map",
    "BoxI64",
    "BoxU64",
    "BoxU8",
    "BoxBool",
    "BoxDouble",
}
NUMERIC_TYPE_NAMES = {"i64", "u64", "u8", "double"}
BUILTIN_INDEX_RESULT_TYPE_NAMES = {
    "Vec": "Obj",
}


@dataclass(frozen=True)
class TypeInfo:
    name: str
    kind: str


@dataclass(frozen=True)
class FunctionSig:
    name: str
    params: list[TypeInfo]
    return_type: TypeInfo
    is_static: bool = False


@dataclass(frozen=True)
class ClassInfo:
    name: str
    fields: dict[str, TypeInfo]
    field_order: list[str]
    methods: dict[str, FunctionSig]


class TypeCheckError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span
