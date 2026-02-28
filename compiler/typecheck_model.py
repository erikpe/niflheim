from __future__ import annotations

from dataclasses import dataclass

from compiler.lexer import SourceSpan


PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
REFERENCE_BUILTIN_TYPE_NAMES = {
    "Obj",
    "Map",
}
NUMERIC_TYPE_NAMES = {"i64", "u64", "u8", "double"}
BUILTIN_INDEX_RESULT_TYPE_NAMES = {
}


@dataclass(frozen=True)
class TypeInfo:
    name: str
    kind: str
    element_type: "TypeInfo | None" = None


@dataclass(frozen=True)
class FunctionSig:
    name: str
    params: list[TypeInfo]
    return_type: TypeInfo
    is_static: bool = False
    is_private: bool = False


@dataclass(frozen=True)
class ClassInfo:
    name: str
    fields: dict[str, TypeInfo]
    field_order: list[str]
    methods: dict[str, FunctionSig]
    private_fields: set[str]
    private_methods: set[str]


class TypeCheckError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span
