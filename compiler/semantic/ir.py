from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from compiler.frontend.lexer import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, InterfaceMethodId, MethodId, SyntheticId


@dataclass(frozen=True)
class SemanticProgram:
    entry_module: ModulePath
    modules: dict[ModulePath, "SemanticModule"]


@dataclass(frozen=True)
class SemanticModule:
    module_path: ModulePath
    file_path: Path
    classes: list["SemanticClass"]
    functions: list["SemanticFunction"]
    span: SourceSpan
    interfaces: list["SemanticInterface"] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticInterfaceMethod:
    method_id: InterfaceMethodId
    params: list["SemanticParam"]
    return_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SemanticInterface:
    interface_id: InterfaceId
    is_export: bool
    methods: list[SemanticInterfaceMethod]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticField:
    name: str
    type_name: str
    initializer: "SemanticExpr | None"
    is_private: bool
    is_final: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticClass:
    class_id: ClassId
    is_export: bool
    fields: list[SemanticField]
    methods: list["SemanticMethod"]
    span: SourceSpan
    implemented_interfaces: list[InterfaceId] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticParam:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_name: str
    body: "SemanticBlock | None"
    is_export: bool
    is_extern: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticMethod:
    method_id: MethodId
    params: list[SemanticParam]
    return_type_name: str
    body: "SemanticBlock"
    is_static: bool
    is_private: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticBlock:
    statements: list["SemanticStmt"]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticVarDecl:
    name: str
    type_name: str
    initializer: "SemanticExpr | None"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticAssign:
    target: "SemanticLValue"
    value: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticExprStmt:
    expr: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticReturn:
    value: "SemanticExpr | None"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticIf:
    condition: "SemanticExpr"
    then_block: SemanticBlock
    else_block: SemanticBlock | None
    span: SourceSpan


@dataclass(frozen=True)
class SemanticWhile:
    condition: "SemanticExpr"
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class SemanticBreak:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticContinue:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticForIn:
    element_name: str
    collection: "SemanticExpr"
    iter_len_method: MethodId | None
    iter_get_method: MethodId | None
    element_type_name: str
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class LocalLValue:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldLValue:
    receiver: "SemanticExpr"
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IndexLValue:
    target: "SemanticExpr"
    index: "SemanticExpr"
    value_type_name: str
    set_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceLValue:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    value_type_name: str
    set_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class LocalRefExpr:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionRefExpr:
    function_id: FunctionId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ClassRefExpr:
    class_id: ClassId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class MethodRefExpr:
    method_id: MethodId
    receiver: "SemanticExpr | None"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class LiteralExprS:
    value: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class NullExprS:
    span: SourceSpan


@dataclass(frozen=True)
class UnaryExprS:
    operator: str
    operand: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExprS:
    operator: str
    left: "SemanticExpr"
    right: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CastExprS:
    operand: "SemanticExpr"
    target_type_name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldReadExpr:
    receiver: "SemanticExpr"
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionCallExpr:
    function_id: FunctionId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class StaticMethodCallExpr:
    method_id: MethodId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class InstanceMethodCallExpr:
    method_id: MethodId
    receiver: "SemanticExpr"
    receiver_type_name: str
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class InterfaceMethodCallExpr:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    receiver: "SemanticExpr"
    receiver_type_name: str
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ConstructorCallExpr:
    constructor_id: ConstructorId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CallableValueCallExpr:
    callee: "SemanticExpr"
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ArrayLenExpr:
    target: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class IndexReadExpr:
    target: "SemanticExpr"
    index: "SemanticExpr"
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceReadExpr:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class ArrayCtorExprS:
    element_type_name: str
    length_expr: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SyntheticExpr:
    synthetic_id: SyntheticId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


SemanticStmt = (
    SemanticBlock
    | SemanticVarDecl
    | SemanticAssign
    | SemanticExprStmt
    | SemanticReturn
    | SemanticIf
    | SemanticWhile
    | SemanticForIn
    | SemanticBreak
    | SemanticContinue
)


SemanticLValue = LocalLValue | FieldLValue | IndexLValue | SliceLValue


SemanticExpr = (
    LocalRefExpr
    | FunctionRefExpr
    | ClassRefExpr
    | MethodRefExpr
    | LiteralExprS
    | NullExprS
    | UnaryExprS
    | BinaryExprS
    | CastExprS
    | FieldReadExpr
    | FunctionCallExpr
    | StaticMethodCallExpr
    | InstanceMethodCallExpr
    | InterfaceMethodCallExpr
    | ConstructorCallExpr
    | CallableValueCallExpr
    | ArrayLenExpr
    | IndexReadExpr
    | SliceReadExpr
    | ArrayCtorExprS
    | SyntheticExpr
)
