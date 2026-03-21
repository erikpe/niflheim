from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_shapes import PRIMITIVE_TYPE_NAMES
from compiler.frontend.lexer import SourceSpan


REFERENCE_BUILTIN_TYPE_NAMES = {"Obj"}
NUMERIC_TYPE_NAMES = {"i64", "u64", "u8", "double"}


@dataclass(frozen=True)
class TypeInfo:
    name: str
    kind: str
    element_type: "TypeInfo | None" = None
    callable_params: list["TypeInfo"] | None = None
    callable_return: "TypeInfo | None" = None


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
    constructor_param_order: list[str]
    methods: dict[str, FunctionSig]
    private_fields: set[str]
    final_fields: set[str]
    private_methods: set[str]
    constructor_is_private: bool
    implemented_interfaces: set[str]


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    methods: dict[str, FunctionSig]


class TypeCheckError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span
