from __future__ import annotations

from dataclasses import dataclass

from compiler.common.span import SourceSpan


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
class ConstructorInfo:
    ordinal: int
    params: list[TypeInfo]
    param_names: list[str]
    is_private: bool


@dataclass(frozen=True)
class FieldMemberInfo:
    owner_class_name: str
    type_info: TypeInfo
    is_private: bool
    is_final: bool


@dataclass(frozen=True)
class MethodMemberInfo:
    owner_class_name: str
    signature: FunctionSig


@dataclass(frozen=True)
class ClassInfo:
    name: str
    type_name: str
    is_placeholder: bool
    superclass_name: str | None
    declared_fields: dict[str, TypeInfo]
    declared_field_order: list[str]
    fields: dict[str, TypeInfo]
    field_order: list[str]
    field_members: dict[str, FieldMemberInfo]
    constructors: list[ConstructorInfo]
    declared_methods: dict[str, FunctionSig]
    methods: dict[str, FunctionSig]
    method_members: dict[str, MethodMemberInfo]
    private_fields: set[str]
    final_fields: set[str]
    private_methods: set[str]
    declared_interfaces: set[str]
    implemented_interfaces: set[str]


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    methods: dict[str, FunctionSig]
    is_placeholder: bool = False


class TypeCheckError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span
