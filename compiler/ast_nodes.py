from __future__ import annotations

from dataclasses import dataclass

from compiler.lexer import SourceSpan


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
    body_span: SourceSpan
    span: SourceSpan


@dataclass(frozen=True)
class FunctionDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRef
    body_span: SourceSpan
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
