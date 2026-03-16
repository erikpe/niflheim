from __future__ import annotations

from dataclasses import dataclass, field

from compiler.ast_nodes import ModuleAst
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo


@dataclass
class TypeCheckContext:
    module_ast: ModuleAst
    module_path: ModulePath | None = None
    modules: dict[ModulePath, ModuleInfo] | None = None
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] | None = None
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None = None
    functions: dict[str, FunctionSig] = field(default_factory=dict)
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    scope_stack: list[dict[str, TypeInfo]] = field(default_factory=list)
    function_local_names_stack: list[set[str]] = field(default_factory=list)
    loop_depth: int = 0
    current_private_owner_type: str | None = None


def push_scope(ctx: TypeCheckContext) -> None:
    ctx.scope_stack.append({})


def pop_scope(ctx: TypeCheckContext) -> None:
    ctx.scope_stack.pop()


def declare_variable(ctx: TypeCheckContext, name: str, var_type: TypeInfo, span: SourceSpan) -> None:
    if ctx.function_local_names_stack:
        function_local_names = ctx.function_local_names_stack[-1]
        if name in function_local_names:
            raise TypeCheckError(f"Duplicate local variable '{name}'", span)
        function_local_names.add(name)

    scope = ctx.scope_stack[-1]
    if name in scope:
        raise TypeCheckError(f"Duplicate local variable '{name}'", span)
    scope[name] = var_type


def lookup_variable(ctx: TypeCheckContext, name: str) -> TypeInfo | None:
    for scope in reversed(ctx.scope_stack):
        if name in scope:
            return scope[name]
    return None
