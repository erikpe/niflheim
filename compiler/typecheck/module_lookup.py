from __future__ import annotations

from compiler.ast_nodes import Expression, FieldAccessExpr, IdentifierExpr
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError


def current_module_info(
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
) -> ModuleInfo | None:
    if modules is None or module_path is None:
        return None
    return modules[module_path]


def lookup_class_by_type_name(
    type_name: str,
    *,
    local_classes: dict[str, ClassInfo],
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> ClassInfo | None:
    local = local_classes.get(type_name)
    if local is not None:
        return local

    if "::" not in type_name or module_class_infos is None:
        return None

    owner_dotted, class_name = type_name.split("::", 1)
    owner_module = tuple(owner_dotted.split("."))
    owner_classes = module_class_infos.get(owner_module)
    if owner_classes is None:
        return None
    return owner_classes.get(class_name)


def flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]

    if isinstance(expr, FieldAccessExpr):
        left = flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]

    return None


def resolve_imported_function_sig(
    fn_name: str,
    span: SourceSpan,
    *,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] | None,
) -> FunctionSig | None:
    current_module = current_module_info(modules, module_path)
    if current_module is None or modules is None or module_function_sigs is None:
        return None

    matches: list[ModulePath] = []
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = modules[imported_module_path]
        symbol = module_info.exported_symbols.get(fn_name)
        if symbol is not None and symbol.kind == "function":
            matches.append(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(
            f"Ambiguous imported function '{fn_name}' (matches: {candidates})",
            span,
        )

    return module_function_sigs[matches[0]][fn_name]


def resolve_unique_global_class_name(
    class_name: str,
    span: SourceSpan,
    *,
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> str | None:
    if module_class_infos is None:
        return None

    matches: list[ModulePath] = []
    for module_path, classes in module_class_infos.items():
        if class_name in classes:
            matches.append(module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(
            f"Ambiguous global class '{class_name}' (matches: {candidates})",
            span,
        )

    owner_dotted = ".".join(matches[0])
    return f"{owner_dotted}::{class_name}"


def resolve_unique_imported_class_module(
    class_name: str,
    span: SourceSpan,
    *,
    ambiguity_label: str,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
) -> ModulePath | None:
    current_module = current_module_info(modules, module_path)
    if current_module is None or modules is None:
        return None

    matches: list[ModulePath] = []
    for import_info in current_module.imports.values():
        imported_module_path = import_info.module_path
        module_info = modules[imported_module_path]
        symbol = module_info.exported_symbols.get(class_name)
        if symbol is not None and symbol.kind == "class":
            matches.append(imported_module_path)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(path) for path in matches))
        raise TypeCheckError(
            f"Ambiguous imported {ambiguity_label} '{class_name}' (matches: {candidates})",
            span,
        )

    return matches[0]


def resolve_imported_class_name(
    class_name: str,
    span: SourceSpan,
    *,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
) -> str | None:
    matched_module = resolve_unique_imported_class_module(
        class_name,
        span,
        ambiguity_label="type",
        modules=modules,
        module_path=module_path,
    )
    if matched_module is None:
        return None

    owner_dotted = ".".join(matched_module)
    return f"{owner_dotted}::{class_name}"


def resolve_qualified_imported_class_name(
    qualified_name: str,
    span: SourceSpan,
    *,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
) -> str | None:
    current_module = current_module_info(modules, module_path)
    if current_module is None or modules is None:
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
        module_info = modules[current_path]
        next_module = module_info.exported_modules.get(segment)
        if next_module is None:
            dotted = ".".join(current_path)
            raise TypeCheckError(
                f"Module '{dotted}' has no exported module '{segment}'",
                span,
            )
        current_path = next_module

    class_name = parts[-1]
    module_info = modules[current_path]
    symbol = module_info.exported_symbols.get(class_name)
    if symbol is None or symbol.kind != "class":
        dotted = ".".join(current_path)
        raise TypeCheckError(
            f"Module '{dotted}' has no exported class '{class_name}'",
            span,
        )

    owner_dotted = ".".join(current_path)
    return f"{owner_dotted}::{class_name}"


def resolve_module_member(
    expr: FieldAccessExpr,
    *,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_path: ModulePath | None,
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] | None,
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> tuple[str, ModulePath, str] | None:
    if modules is None or module_path is None:
        return None

    chain = flatten_field_chain(expr)
    if chain is None or len(chain) < 2:
        return None

    current_module = modules[module_path]
    import_info = current_module.imports.get(chain[0])
    if import_info is None:
        return None

    current_path = import_info.module_path
    for index, segment in enumerate(chain[1:]):
        module_info = modules[current_path]
        is_last = index == len(chain[1:]) - 1

        reexported = module_info.exported_modules.get(segment)
        if reexported is not None:
            current_path = reexported
            if is_last:
                return ("module", current_path, segment)
            continue

        exported_symbol = module_info.exported_symbols.get(segment)

        if (
            module_function_sigs is not None
            and segment in module_function_sigs[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "function"
        ):
            if is_last:
                return ("function", current_path, segment)
            return None

        if (
            module_class_infos is not None
            and segment in module_class_infos[current_path]
            and exported_symbol is not None
            and exported_symbol.kind == "class"
        ):
            if is_last:
                return ("class", current_path, segment)
            return None

        return None

    return None
