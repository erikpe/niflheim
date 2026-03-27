from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from compiler.common.span import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.ir import (
    SemanticClass,
    SemanticDispatch,
    SemanticExpr,
    SemanticFunction,
    SemanticInterface,
    SemanticVarDecl,
    SemanticAssign,
    SemanticExprStmt,
    SemanticReturn,
    SemanticBreak,
    SemanticContinue,
)
from compiler.semantic.symbols import LocalId
from compiler.semantic.types import SemanticTypeRef


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
    classes: list[SemanticClass]
    functions: list[SemanticFunction]
    span: SourceSpan
    interfaces: list[SemanticInterface]


@dataclass(frozen=True)
class LoweredLinkedSemanticProgram:
    entry_module: ModulePath
    ordered_modules: tuple[LoweredSemanticModule, ...]
    classes: tuple[SemanticClass, ...]
    functions: tuple[SemanticFunction, ...]
    span: SourceSpan
