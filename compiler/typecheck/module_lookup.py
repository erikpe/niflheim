from __future__ import annotations

from compiler.frontend.ast_nodes import Expression, FieldAccessExpr, IdentifierExpr
from compiler.typecheck.context import TypeCheckContext
from compiler.frontend.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.model import ClassInfo, FunctionSig, InterfaceInfo, TypeCheckError


def current_module_info(ctx: TypeCheckContext) -> ModuleInfo | None:
    if ctx.modules is None or ctx.module_path is None:
        return None
    return ctx.modules[ctx.module_path]


def lookup_class_by_type_name(ctx: TypeCheckContext, type_name: str) -> ClassInfo | None:
    local = ctx.classes.get(type_name)
    if local is not None:
        return local

    if "::" not in type_name or ctx.module_class_infos is None:
        return None

    owner_dotted, class_name = type_name.split("::", 1)
    owner_module = tuple(owner_dotted.split("."))
    owner_classes = ctx.module_class_infos.get(owner_module)
    if owner_classes is None:
        return None
    return owner_classes.get(class_name)


def lookup_interface_by_type_name(ctx: TypeCheckContext, type_name: str) -> InterfaceInfo | None:
    local = ctx.interfaces.get(type_name)
    if local is not None:
        return local

    if "::" not in type_name or ctx.module_interface_infos is None:
        return None

    owner_dotted, interface_name = type_name.split("::", 1)
    owner_module = tuple(owner_dotted.split("."))
    owner_interfaces = ctx.module_interface_infos.get(owner_module)
    if owner_interfaces is None:
        return None
    return owner_interfaces.get(interface_name)


def _flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]

    if isinstance(expr, FieldAccessExpr):
        left = _flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]

    return None


def resolve_imported_function_sig(ctx: TypeCheckContext, fn_name: str, span: SourceSpan) -> FunctionSig | None:
    current_module = current_module_info(ctx)
    if current_module is None or ctx.modules is None or ctx.module_function_sigs is None:
        return None

    matches: list[ModulePath] = []
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = ctx.modules[imported_module_path]
        symbol = module_info.exported_symbols.get(fn_name)
        if symbol is not None and symbol.kind == "function":
            matches.append(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(f"Ambiguous imported function '{fn_name}' (matches: {candidates})", span)

    return ctx.module_function_sigs[matches[0]][fn_name]


def _resolve_unique_imported_symbol_module(
    ctx: TypeCheckContext, symbol_name: str, span: SourceSpan, *, symbol_kind: str, ambiguity_label: str
) -> ModulePath | None:
    current_module = current_module_info(ctx)
    if current_module is None or ctx.modules is None:
        return None

    matches: list[ModulePath] = []
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = ctx.modules[imported_module_path]
        symbol = module_info.exported_symbols.get(symbol_name)
        if symbol is not None and symbol.kind == symbol_kind:
            matches.append(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(f"Ambiguous imported {ambiguity_label} '{symbol_name}' (matches: {candidates})", span)

    return matches[0]


def resolve_unique_global_class_name(ctx: TypeCheckContext, class_name: str, span: SourceSpan) -> str | None:
    if ctx.module_class_infos is None:
        return None

    matches: list[ModulePath] = []
    for module_path, classes in ctx.module_class_infos.items():
        if class_name in classes:
            matches.append(module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(f"Ambiguous global class '{class_name}' (matches: {candidates})", span)

    owner_dotted = ".".join(matches[0])
    return f"{owner_dotted}::{class_name}"


def _resolve_unique_imported_class_module(
    ctx: TypeCheckContext, class_name: str, span: SourceSpan, *, ambiguity_label: str
) -> ModulePath | None:
    return _resolve_unique_imported_symbol_module(
        ctx, class_name, span, symbol_kind="class", ambiguity_label=ambiguity_label
    )


def resolve_imported_class_name(ctx: TypeCheckContext, class_name: str, span: SourceSpan) -> str | None:
    matched_module = _resolve_unique_imported_class_module(ctx, class_name, span, ambiguity_label="type")
    if matched_module is None:
        return None

    owner_dotted = ".".join(matched_module)
    return f"{owner_dotted}::{class_name}"


def resolve_imported_interface_name(ctx: TypeCheckContext, interface_name: str, span: SourceSpan) -> str | None:
    matched_module = _resolve_unique_imported_symbol_module(
        ctx, interface_name, span, symbol_kind="interface", ambiguity_label="interface"
    )
    if matched_module is None:
        return None

    owner_dotted = ".".join(matched_module)
    return f"{owner_dotted}::{interface_name}"


def _resolve_qualified_imported_symbol_name(
    ctx: TypeCheckContext,
    qualified_name: str,
    span: SourceSpan,
    *,
    symbol_kind: str,
    symbol_label: str,
    allow_missing: bool = False,
) -> str | None:
    current_module = current_module_info(ctx)
    if current_module is None or ctx.modules is None:
        return None

    parts = qualified_name.split(".")
    if len(parts) < 2:
        return None

    import_alias = parts[0]
    import_info = current_module.imports.get(import_alias)
    if import_info is None:
        return None

    current_path = import_info.module_path
    for segment in parts[1:-1]:
        module_info = ctx.modules[current_path]
        next_module = module_info.exported_modules.get(segment)
        if next_module is None:
            dotted = ".".join(current_path)
            raise TypeCheckError(f"Module '{dotted}' has no exported module '{segment}'", span)
        current_path = next_module

    symbol_name = parts[-1]
    module_info = ctx.modules[current_path]
    symbol = module_info.exported_symbols.get(symbol_name)
    if symbol is None:
        if allow_missing:
            return None
        dotted = ".".join(current_path)
        raise TypeCheckError(f"Module '{dotted}' has no exported {symbol_label} '{symbol_name}'", span)

    if symbol.kind != symbol_kind:
        if allow_missing:
            return None
        dotted = ".".join(current_path)
        raise TypeCheckError(f"Module '{dotted}' has no exported {symbol_label} '{symbol_name}'", span)

    owner_dotted = ".".join(current_path)
    return f"{owner_dotted}::{symbol_name}"


def resolve_qualified_imported_class_name(ctx: TypeCheckContext, qualified_name: str, span: SourceSpan) -> str | None:
    return _resolve_qualified_imported_symbol_name(
        ctx, qualified_name, span, symbol_kind="class", symbol_label="class"
    )


def resolve_qualified_imported_interface_name(
    ctx: TypeCheckContext, qualified_name: str, span: SourceSpan, *, allow_missing: bool = False
) -> str | None:
    return _resolve_qualified_imported_symbol_name(
        ctx,
        qualified_name,
        span,
        symbol_kind="interface",
        symbol_label="interface",
        allow_missing=allow_missing,
    )


def resolve_module_member(ctx: TypeCheckContext, expr: FieldAccessExpr) -> tuple[str, ModulePath, str] | None:
    if ctx.modules is None or ctx.module_path is None:
        return None

    chain = _flatten_field_chain(expr)
    if chain is None or len(chain) < 2:
        return None

    current_module = ctx.modules[ctx.module_path]
    import_info = current_module.imports.get(chain[0])
    if import_info is None:
        return None

    current_path = import_info.module_path
    for index, segment in enumerate(chain[1:]):
        module_info = ctx.modules[current_path]
        is_last = index == len(chain[1:]) - 1

        reexported = module_info.exported_modules.get(segment)
        if reexported is not None:
            current_path = reexported
            if is_last:
                return ("module", current_path, segment)
            continue

        exported_symbol = module_info.exported_symbols.get(segment)

        if (
            ctx.module_function_sigs is not None
            and segment in ctx.module_function_sigs[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "function"
        ):
            if is_last:
                return ("function", current_path, segment)
            return None

        if (
            ctx.module_class_infos is not None
            and segment in ctx.module_class_infos[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "class"
        ):
            if is_last:
                return ("class", current_path, segment)
            return None

        return None

    return None
