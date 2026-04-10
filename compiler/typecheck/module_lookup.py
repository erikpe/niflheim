from __future__ import annotations

from compiler.frontend.ast_nodes import Expression, FieldAccessExpr, IdentifierExpr
from compiler.typecheck.context import TypeCheckContext
from compiler.common.span import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath, match_exported_import_chain_prefix, match_import_chain_prefix
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

    matches: set[ModulePath] = set()
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = ctx.modules[imported_module_path]
        symbol = module_info.exported_symbols.get(fn_name)
        if symbol is not None and symbol.kind == "function":
            matches.add(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(f"Ambiguous imported function '{fn_name}' (matches: {candidates})", span)

    matched_module = next(iter(matches))
    return ctx.module_function_sigs[matched_module][fn_name]


def _resolve_unique_imported_symbol_module(
    ctx: TypeCheckContext, symbol_name: str, span: SourceSpan, *, symbol_kind: str, ambiguity_label: str
) -> ModulePath | None:
    current_module = current_module_info(ctx)
    if current_module is None or ctx.modules is None:
        return None

    matches: set[ModulePath] = set()
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = ctx.modules[imported_module_path]
        symbol = module_info.exported_symbols.get(symbol_name)
        if symbol is not None and symbol.kind == symbol_kind:
            matches.add(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(f"Ambiguous imported {ambiguity_label} '{symbol_name}' (matches: {candidates})", span)

    return next(iter(matches))


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

    matched_import = match_import_chain_prefix(current_module.imports, parts)
    if matched_import is None:
        return None

    import_info, consumed = matched_import
    current_path = import_info.module_path
    remaining_module_segments = tuple(parts[consumed:-1])
    while remaining_module_segments:
        module_info = ctx.modules[current_path]
        matched_export = match_exported_import_chain_prefix(module_info, remaining_module_segments)
        if matched_export is None:
            dotted = ".".join(current_path)
            raise TypeCheckError(f"Module '{dotted}' has no exported module '{remaining_module_segments[0]}'", span)
        export_info, export_consumed = matched_export
        current_path = export_info.module_path
        remaining_module_segments = remaining_module_segments[export_consumed:]

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
    matched_import = match_import_chain_prefix(current_module.imports, chain)
    if matched_import is None:
        return None

    import_info, consumed = matched_import
    current_path = import_info.module_path
    remaining_segments = tuple(chain[consumed:])
    if not remaining_segments:
        return ("module", current_path, current_path[-1])

    while remaining_segments:
        module_info = ctx.modules[current_path]
        matched_export = match_exported_import_chain_prefix(module_info, remaining_segments)
        if matched_export is not None:
            export_info, export_consumed = matched_export
            current_path = export_info.module_path
            remaining_segments = remaining_segments[export_consumed:]
            if not remaining_segments:
                return ("module", current_path, current_path[-1])
            continue

        if len(remaining_segments) != 1:
            return None

        segment = remaining_segments[0]

        exported_symbol = module_info.exported_symbols.get(segment)

        if (
            ctx.module_function_sigs is not None
            and segment in ctx.module_function_sigs[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "function"
        ):
            return ("function", current_path, segment)

        if (
            ctx.module_class_infos is not None
            and segment in ctx.module_class_infos[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "class"
        ):
            return ("class", current_path, segment)

        return None

    return None
