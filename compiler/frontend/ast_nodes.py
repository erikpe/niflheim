from __future__ import annotations

from dataclasses import dataclass, field

from compiler.common.literals import IntLiteralKind
from compiler.common.span import SourceSpan


@dataclass(frozen=True)
class TypeRef:
    name: str
    span: SourceSpan


@dataclass(frozen=True)
class ArrayTypeRef:
    element_type: "TypeRefNode"
    span: SourceSpan


@dataclass(frozen=True)
class FunctionTypeRef:
    param_types: list["TypeRefNode"]
    return_type: "TypeRefNode"
    span: SourceSpan


TypeRefNode = TypeRef | ArrayTypeRef | FunctionTypeRef


@dataclass(frozen=True)
class ParamDecl:
    name: str
    type_ref: TypeRefNode
    span: SourceSpan


@dataclass(frozen=True)
class InterfaceMethodDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRefNode
    span: SourceSpan


@dataclass(frozen=True)
class InterfaceDecl:
    name: str
    methods: list[InterfaceMethodDecl]
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class ImportDecl:
    module_path: list[str]
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class FieldDecl:
    name: str
    type_ref: TypeRefNode
    initializer: "Expression | None"
    is_private: bool
    is_final: bool
    span: SourceSpan


@dataclass(frozen=True)
class MethodDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRefNode
    body: "BlockStmt"
    is_static: bool
    is_private: bool
    span: SourceSpan


@dataclass(frozen=True)
class ConstructorDecl:
    params: list[ParamDecl]
    body: "BlockStmt"
    is_private: bool
    span: SourceSpan


@dataclass(frozen=True)
class FunctionDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRefNode
    body: "BlockStmt | None"
    is_export: bool
    is_extern: bool
    span: SourceSpan


@dataclass(frozen=True)
class ClassDecl:
    name: str
    fields: list[FieldDecl]
    methods: list[MethodDecl]
    is_export: bool
    span: SourceSpan
    implements: list[TypeRefNode] = field(default_factory=list)
    constructors: list[ConstructorDecl] = field(default_factory=list)


@dataclass(frozen=True)
class ModuleAst:
    imports: list[ImportDecl]
    classes: list[ClassDecl]
    functions: list[FunctionDecl]
    span: SourceSpan
    interfaces: list[InterfaceDecl] = field(default_factory=list)


@dataclass(frozen=True)
class IntLiteralValue:
    raw_text: str
    magnitude: int
    kind: IntLiteralKind


@dataclass(frozen=True)
class FloatLiteralValue:
    raw_text: str
    value: float


@dataclass(frozen=True)
class BoolLiteralValue:
    value: bool
    raw_text: str


@dataclass(frozen=True)
class CharLiteralValue:
    raw_text: str


@dataclass(frozen=True)
class StringLiteralValue:
    raw_text: str


LiteralValueNode = IntLiteralValue | FloatLiteralValue | BoolLiteralValue | CharLiteralValue | StringLiteralValue


@dataclass(frozen=True)
class IdentifierExpr:
    name: str
    span: SourceSpan


@dataclass(frozen=True)
class LiteralExpr:
    literal: LiteralValueNode
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
    type_ref: TypeRefNode
    operand: "Expression"
    span: SourceSpan


@dataclass(frozen=True)
class TypeTestExpr:
    operand: "Expression"
    type_ref: TypeRefNode
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


@dataclass(frozen=True)
class ArrayCtorExpr:
    element_type_ref: TypeRefNode
    length_expr: "Expression"
    span: SourceSpan


Expression = (
    IdentifierExpr
    | LiteralExpr
    | NullExpr
    | UnaryExpr
    | BinaryExpr
    | CastExpr
    | TypeTestExpr
    | CallExpr
    | FieldAccessExpr
    | IndexExpr
    | ArrayCtorExpr
)


@dataclass(frozen=True)
class BlockStmt:
    statements: list["Statement"]
    span: SourceSpan


@dataclass(frozen=True)
class VarDeclStmt:
    name: str
    type_ref: TypeRefNode
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
class BreakStmt:
    span: SourceSpan


@dataclass(frozen=True)
class ContinueStmt:
    span: SourceSpan


@dataclass(frozen=True)
class ForInStmt:
    element_name: str
    collection_expr: Expression
    body: BlockStmt
    coll_temp_name: str
    len_temp_name: str
    index_temp_name: str
    collection_type_name: str
    element_type_name: str
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
    | ForInStmt
    | ReturnStmt
    | BreakStmt
    | ContinueStmt
    | AssignStmt
    | ExprStmt
)
