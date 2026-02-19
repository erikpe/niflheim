from __future__ import annotations

from dataclasses import dataclass

from compiler.lexer import SourceSpan


__all__ = [
    "TypeRef",
    "ParamDecl",
    "ImportDecl",
    "FieldDecl",
    "MethodDecl",
    "FunctionDecl",
    "ClassDecl",
    "ModuleAst",
    "IdentifierExpr",
    "LiteralExpr",
    "NullExpr",
    "UnaryExpr",
    "BinaryExpr",
    "CastExpr",
    "CallExpr",
    "FieldAccessExpr",
    "IndexExpr",
    "Expression",
    "BlockStmt",
    "VarDeclStmt",
    "IfStmt",
    "WhileStmt",
    "ReturnStmt",
    "AssignStmt",
    "ExprStmt",
    "Statement",
]


@dataclass(frozen=True)
class TypeRef:
    name: str
    span: SourceSpan


@dataclass(frozen=True)
class ParamDecl:
    name: str
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True)
class ImportDecl:
    module_path: list[str]
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class FieldDecl:
    name: str
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True)
class MethodDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRef
    body: "BlockStmt"
    span: SourceSpan


@dataclass(frozen=True)
class FunctionDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRef
    body: "BlockStmt"
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class ClassDecl:
    name: str
    fields: list[FieldDecl]
    methods: list[MethodDecl]
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class ModuleAst:
    imports: list[ImportDecl]
    classes: list[ClassDecl]
    functions: list[FunctionDecl]
    span: SourceSpan


@dataclass(frozen=True)
class IdentifierExpr:
    name: str
    span: SourceSpan


@dataclass(frozen=True)
class LiteralExpr:
    value: str
    span: SourceSpan


@dataclass(frozen=True)
class NullExpr:
    span: SourceSpan


@dataclass(frozen=True)
class UnaryExpr:
    operator: str
    operand: "Expression"
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExpr:
    left: "Expression"
    operator: str
    right: "Expression"
    span: SourceSpan


@dataclass(frozen=True)
class CastExpr:
    type_ref: TypeRef
    operand: "Expression"
    span: SourceSpan


@dataclass(frozen=True)
class CallExpr:
    callee: "Expression"
    arguments: list["Expression"]
    span: SourceSpan


@dataclass(frozen=True)
class FieldAccessExpr:
    object_expr: "Expression"
    field_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IndexExpr:
    object_expr: "Expression"
    index_expr: "Expression"
    span: SourceSpan


Expression = (
    IdentifierExpr
    | LiteralExpr
    | NullExpr
    | UnaryExpr
    | BinaryExpr
    | CastExpr
    | CallExpr
    | FieldAccessExpr
    | IndexExpr
)


@dataclass(frozen=True)
class BlockStmt:
    statements: list["Statement"]
    span: SourceSpan


@dataclass(frozen=True)
class VarDeclStmt:
    name: str
    type_ref: TypeRef
    initializer: Expression | None
    span: SourceSpan


@dataclass(frozen=True)
class IfStmt:
    condition: Expression
    then_branch: BlockStmt
    else_branch: "BlockStmt | IfStmt | None"
    span: SourceSpan


@dataclass(frozen=True)
class WhileStmt:
    condition: Expression
    body: BlockStmt
    span: SourceSpan


@dataclass(frozen=True)
class ReturnStmt:
    value: Expression | None
    span: SourceSpan


@dataclass(frozen=True)
class AssignStmt:
    target: Expression
    value: Expression
    span: SourceSpan


@dataclass(frozen=True)
class ExprStmt:
    expression: Expression
    span: SourceSpan


Statement = (
    BlockStmt
    | VarDeclStmt
    | IfStmt
    | WhileStmt
    | ReturnStmt
    | AssignStmt
    | ExprStmt
)
