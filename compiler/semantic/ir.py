from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind
from compiler.common.type_names import TYPE_NAME_NULL, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.common.span import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.operations import (
    CastSemanticsKind,
    SemanticBinaryOp,
    SemanticUnaryOp,
    TypeTestSemanticsKind,
)
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    LocalId,
    LocalOwnerId,
    MethodId,
)
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_array_type_ref,
    semantic_null_type_ref,
    semantic_primitive_type_ref,
    semantic_type_display_name,
)


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
    return_type_ref: SemanticTypeRef
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
    type_ref: SemanticTypeRef
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


LocalBindingKind = Literal[
    "receiver",
    "param",
    "local",
    "for_in_element",
    "for_in_collection",
    "for_in_length",
    "for_in_index",
]


@dataclass(frozen=True)
class SemanticLocalInfo:
    local_id: LocalId
    owner_id: LocalOwnerId
    display_name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan
    binding_kind: LocalBindingKind


@dataclass(frozen=True)
class SemanticParam:
    name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class SemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_name: str
    return_type_ref: SemanticTypeRef
    body: "SemanticBlock | None"
    is_export: bool
    is_extern: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticMethod:
    method_id: MethodId
    params: list[SemanticParam]
    return_type_name: str
    return_type_ref: SemanticTypeRef
    body: "SemanticBlock"
    is_static: bool
    is_private: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)


SemanticFunctionLike = SemanticFunction | SemanticMethod


def local_info_for_owner(owner: SemanticFunctionLike, local_id: LocalId) -> SemanticLocalInfo | None:
    return owner.local_info_by_id.get(local_id)


def require_local_info_for_owner(owner: SemanticFunctionLike, local_id: LocalId) -> SemanticLocalInfo:
    local_info = local_info_for_owner(owner, local_id)
    if local_info is None:
        raise KeyError(f"Missing semantic local metadata for {local_id}")
    return local_info


def local_display_name_for_owner(owner: SemanticFunctionLike, local_id: LocalId) -> str:
    return require_local_info_for_owner(owner, local_id).display_name


def local_type_name_for_owner(owner: SemanticFunctionLike, local_id: LocalId) -> str:
    return require_local_info_for_owner(owner, local_id).type_name


def local_type_ref_for_owner(owner: SemanticFunctionLike, local_id: LocalId) -> SemanticTypeRef:
    return require_local_info_for_owner(owner, local_id).type_ref


def local_ref_expr_for_owner(owner: SemanticFunctionLike, local_id: LocalId, *, span: SourceSpan) -> "LocalRefExpr":
    local_info = require_local_info_for_owner(owner, local_id)
    return LocalRefExpr(
        local_id=local_id,
        type_ref=local_info.type_ref,
        span=span,
    )


@dataclass(frozen=True)
class SemanticBlock:
    statements: list["SemanticStmt"]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticVarDecl:
    local_id: LocalId
    initializer: "SemanticExpr | None"
    span: SourceSpan
    name: str | None = None
    type_ref: SemanticTypeRef | None = None


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
class RuntimeDispatch:
    operation: CollectionOpKind
    runtime_kind: ArrayRuntimeKind | None = None


@dataclass(frozen=True)
class MethodDispatch:
    method_id: MethodId


SemanticDispatch = RuntimeDispatch | MethodDispatch


@dataclass(frozen=True)
class SemanticForIn:
    element_name: str
    element_local_id: LocalId
    collection_local_id: LocalId
    length_local_id: LocalId
    index_local_id: LocalId
    collection: "SemanticExpr"
    iter_len_dispatch: SemanticDispatch
    iter_get_dispatch: SemanticDispatch
    element_type_name: str
    element_type_ref: SemanticTypeRef
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class LocalLValue:
    local_id: LocalId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class BoundMemberAccess:
    receiver: "SemanticExpr"
    receiver_type_name: str
    receiver_type_ref: SemanticTypeRef


@dataclass(frozen=True)
class FieldLValue:
    access: BoundMemberAccess
    owner_class_id: ClassId
    field_name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan

    @property
    def receiver(self) -> "SemanticExpr":
        return self.access.receiver

    @property
    def receiver_type_name(self) -> str:
        return self.access.receiver_type_name

    @property
    def receiver_type_ref(self) -> SemanticTypeRef:
        return self.access.receiver_type_ref


@dataclass(frozen=True)
class IndexLValue:
    target: "SemanticExpr"
    index: "SemanticExpr"
    value_type_name: str
    value_type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class SliceLValue:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    value_type_name: str
    value_type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class LocalRefExpr:
    local_id: LocalId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class FunctionRefExpr:
    function_id: FunctionId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class ClassRefExpr:
    class_id: ClassId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class MethodRefExpr:
    method_id: MethodId
    receiver: "SemanticExpr | None"
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class IntConstant:
    value: int
    type_name: str


@dataclass(frozen=True)
class FloatConstant:
    value: float
    type_name: str


@dataclass(frozen=True)
class BoolConstant:
    value: bool
    type_name: str


@dataclass(frozen=True)
class CharConstant:
    value: int
    type_name: str


SemanticConstant = IntConstant | FloatConstant | BoolConstant | CharConstant


@dataclass(frozen=True)
class LiteralExprS:
    constant: SemanticConstant
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class NullExprS:
    span: SourceSpan
    type_name: str = TYPE_NAME_NULL
    type_ref: SemanticTypeRef = field(default_factory=semantic_null_type_ref)


@dataclass(frozen=True)
class UnaryExprS:
    op: SemanticUnaryOp
    operand: "SemanticExpr"
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExprS:
    op: SemanticBinaryOp
    left: "SemanticExpr"
    right: "SemanticExpr"
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class CastExprS:
    operand: "SemanticExpr"
    cast_kind: CastSemanticsKind
    target_type_name: str
    target_type_ref: SemanticTypeRef
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class TypeTestExprS:
    operand: "SemanticExpr"
    test_kind: TypeTestSemanticsKind
    target_type_name: str
    target_type_ref: SemanticTypeRef
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class FieldReadExpr:
    access: BoundMemberAccess
    owner_class_id: ClassId
    field_name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan

    @property
    def receiver(self) -> "SemanticExpr":
        return self.access.receiver

    @property
    def receiver_type_name(self) -> str:
        return self.access.receiver_type_name

    @property
    def receiver_type_ref(self) -> SemanticTypeRef:
        return self.access.receiver_type_ref


@dataclass(frozen=True)
class FunctionCallTarget:
    function_id: FunctionId


@dataclass(frozen=True)
class StaticMethodCallTarget:
    method_id: MethodId


@dataclass(frozen=True)
class InstanceMethodCallTarget:
    method_id: MethodId
    access: BoundMemberAccess


@dataclass(frozen=True)
class InterfaceMethodCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    access: BoundMemberAccess


@dataclass(frozen=True)
class ConstructorCallTarget:
    constructor_id: ConstructorId


@dataclass(frozen=True)
class CallableValueCallTarget:
    callee: "SemanticExpr"


SemanticCallTarget = (
    FunctionCallTarget
    | StaticMethodCallTarget
    | InstanceMethodCallTarget
    | InterfaceMethodCallTarget
    | ConstructorCallTarget
    | CallableValueCallTarget
)


CallDispatchMode = Literal[
    "function",
    "static_method",
    "instance_method",
    "interface_method",
    "constructor",
    "callable_value",
]


def call_target_dispatch_mode(target: SemanticCallTarget) -> CallDispatchMode:
    if isinstance(target, FunctionCallTarget):
        return "function"
    if isinstance(target, StaticMethodCallTarget):
        return "static_method"
    if isinstance(target, InstanceMethodCallTarget):
        return "instance_method"
    if isinstance(target, InterfaceMethodCallTarget):
        return "interface_method"
    if isinstance(target, ConstructorCallTarget):
        return "constructor"
    return "callable_value"


def call_target_receiver_access(target: SemanticCallTarget) -> BoundMemberAccess | None:
    if isinstance(target, (InstanceMethodCallTarget, InterfaceMethodCallTarget)):
        return target.access
    return None


@dataclass(frozen=True)
class CallExprS:
    target: SemanticCallTarget
    args: list["SemanticExpr"]
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class ArrayLenExpr:
    target: "SemanticExpr"
    span: SourceSpan
    type_name: str = TYPE_NAME_U64
    type_ref: SemanticTypeRef = field(default_factory=lambda: semantic_primitive_type_ref(TYPE_NAME_U64))


@dataclass(frozen=True)
class IndexReadExpr:
    target: "SemanticExpr"
    index: "SemanticExpr"
    type_name: str
    type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class SliceReadExpr:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    type_name: str
    type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


def dispatch_method_id(dispatch: SemanticDispatch) -> MethodId | None:
    if isinstance(dispatch, MethodDispatch):
        return dispatch.method_id
    return None


@dataclass(frozen=True)
class ArrayCtorExprS:
    element_type_name: str
    element_type_ref: SemanticTypeRef
    length_expr: "SemanticExpr"
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class StringLiteralBytesExpr:
    literal_text: str
    span: SourceSpan
    type_name: str = f"{TYPE_NAME_U8}[]"
    type_ref: SemanticTypeRef = field(
        default_factory=lambda: semantic_array_type_ref(semantic_primitive_type_ref(TYPE_NAME_U8))
    )


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
    | TypeTestExprS
    | FieldReadExpr
    | CallExprS
    | ArrayLenExpr
    | IndexReadExpr
    | SliceReadExpr
    | ArrayCtorExprS
    | StringLiteralBytesExpr
)


def expression_type_name(expr: SemanticExpr) -> str:
    if isinstance(expr, (LocalRefExpr, FunctionRefExpr, ClassRefExpr, MethodRefExpr)):
        return semantic_type_display_name(expr.type_ref)
    return expr.type_name


def expression_type_ref(expr: SemanticExpr) -> SemanticTypeRef:
    return expr.type_ref
