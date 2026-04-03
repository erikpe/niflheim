from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from compiler.common.span import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.ir import (
    SemanticDispatch,
    SemanticConstructor,
    SemanticExpr,
    SemanticInterface,
    SemanticLocalInfo,
    SemanticParam,
    SemanticVarDecl,
    SemanticAssign,
    SemanticExprStmt,
    SemanticReturn,
    SemanticBreak,
    SemanticContinue,
)
from compiler.semantic.symbols import ClassId, FunctionId, InterfaceId, LocalId, MethodId
from compiler.semantic.symbols import ConstructorId
from compiler.semantic.types import SemanticTypeRef


class LoweredSemanticForInStrategy(Enum):
    ARRAY_DIRECT = "array_direct"
    ARRAY_RUNTIME_DISPATCH = "array_runtime_dispatch"
    COLLECTION_PROTOCOL_DISPATCH = "collection_protocol_dispatch"


@dataclass(frozen=True)
class LoweredSemanticBlock:
    statements: list["LoweredSemanticStmt"]
    span: SourceSpan


@dataclass(frozen=True)
class LoweredSemanticForIn:
    element_name: str
    element_local_id: LocalId
    collection_local_id: LocalId
    length_local_id: LocalId
    index_local_id: LocalId
    collection: SemanticExpr
    iter_len_dispatch: SemanticDispatch
    iter_get_dispatch: SemanticDispatch
    element_type_ref: SemanticTypeRef
    body: LoweredSemanticBlock
    span: SourceSpan
    strategy: LoweredSemanticForInStrategy = LoweredSemanticForInStrategy.COLLECTION_PROTOCOL_DISPATCH


@dataclass(frozen=True)
class LoweredSemanticIf:
    condition: SemanticExpr
    then_block: LoweredSemanticBlock
    else_block: LoweredSemanticBlock | None
    span: SourceSpan


@dataclass(frozen=True)
class LoweredSemanticWhile:
    condition: SemanticExpr
    body: LoweredSemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class LoweredSemanticField:
    name: str
    type_ref: SemanticTypeRef
    initializer: SemanticExpr | None
    is_private: bool
    is_final: bool
    span: SourceSpan


@dataclass(frozen=True)
class LoweredSemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_ref: SemanticTypeRef
    body: LoweredSemanticBlock | None
    is_export: bool
    is_extern: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class LoweredSemanticMethod:
    method_id: MethodId
    params: list[SemanticParam]
    return_type_ref: SemanticTypeRef
    body: LoweredSemanticBlock
    is_static: bool
    is_private: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class LoweredSemanticConstructor:
    constructor_id: ConstructorId
    params: list[SemanticParam]
    body: LoweredSemanticBlock | None
    is_private: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)
    super_constructor_id: ConstructorId | None = None


@dataclass(frozen=True)
class LoweredSemanticClass:
    class_id: ClassId
    is_export: bool
    fields: list[LoweredSemanticField]
    methods: list[LoweredSemanticMethod]
    span: SourceSpan
    superclass_id: ClassId | None = None
    implemented_interfaces: list[InterfaceId] = field(default_factory=list)
    constructors: list[LoweredSemanticConstructor] = field(default_factory=list)


LoweredSemanticFunctionLike = LoweredSemanticFunction | LoweredSemanticMethod | LoweredSemanticConstructor


LoweredSemanticStmt = (
    LoweredSemanticBlock
    | SemanticVarDecl
    | SemanticAssign
    | SemanticExprStmt
    | SemanticReturn
    | LoweredSemanticIf
    | LoweredSemanticWhile
    | LoweredSemanticForIn
    | SemanticBreak
    | SemanticContinue
)


@dataclass(frozen=True)
class LoweredSemanticModule:
    module_path: ModulePath
    file_path: Path
    classes: list[LoweredSemanticClass]
    functions: list[LoweredSemanticFunction]
    span: SourceSpan
    interfaces: list[SemanticInterface]


@dataclass(frozen=True)
class LoweredLinkedSemanticProgram:
    entry_module: ModulePath
    ordered_modules: tuple[LoweredSemanticModule, ...]
    classes: tuple[LoweredSemanticClass, ...]
    functions: tuple[LoweredSemanticFunction, ...]
    span: SourceSpan
