from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from compiler.common.logging import get_logger
from compiler.frontend.ast_nodes import *
from compiler.common.span import SourceSpan
from compiler.frontend.lexer import lex
from compiler.frontend.parser import parse


ModulePath = tuple[str, ...]


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    kind: str
    is_export: bool
    span: SourceSpan
    owner_module_path: ModulePath


@dataclass(frozen=True)
class ImportInfo:
    module_path: ModulePath
    bind_path: ModulePath | None
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class BoundImportInfo:
    bind_path: ModulePath
    module_path: ModulePath
    span: SourceSpan


def _iter_import_infos(
    imports: dict[str, ImportInfo] | tuple[ImportInfo, ...] | list[ImportInfo],
):
    return imports.values() if isinstance(imports, dict) else imports


def _iter_bound_import_infos(
    bindings: tuple[BoundImportInfo, ...] | list[BoundImportInfo],
):
    return bindings


def match_bound_import_chain_prefix(
    bindings: tuple[BoundImportInfo, ...] | list[BoundImportInfo],
    chain: tuple[str, ...] | list[str],
) -> tuple[BoundImportInfo, int] | None:
    best_match: tuple[BoundImportInfo, int] | None = None
    best_length = -1
    parts = tuple(chain)

    for binding in _iter_bound_import_infos(bindings):
        prefix = binding.bind_path
        if len(parts) < len(prefix):
            continue
        if parts[: len(prefix)] != prefix:
            continue
        if len(prefix) > best_length:
            best_match = (binding, len(prefix))
            best_length = len(prefix)

    return best_match


def has_bound_import_chain_prefix(bindings: tuple[BoundImportInfo, ...] | list[BoundImportInfo], chain: tuple[str, ...] | list[str]) -> bool:
    parts = tuple(chain)
    for binding in _iter_bound_import_infos(bindings):
        prefix = binding.bind_path
        if len(parts) < len(prefix) and prefix[: len(parts)] == parts:
            return True

    return False


def has_bound_import_root(bindings: tuple[BoundImportInfo, ...] | list[BoundImportInfo], name: str) -> bool:
    return any(binding.bind_path and binding.bind_path[0] == name for binding in _iter_bound_import_infos(bindings))


@dataclass
class ModuleInfo:
    module_path: ModulePath
    file_path: Path
    ast: ModuleAst
    symbols: dict[str, SymbolInfo]
    exported_symbols: dict[str, SymbolInfo]
    imports: dict[str, ImportInfo]
    bound_imports: tuple[BoundImportInfo, ...]
    exported_imports: tuple[BoundImportInfo, ...]


def match_exported_import_chain_prefix(
    module_info: ModuleInfo, chain: tuple[str, ...] | list[str]
) -> tuple[BoundImportInfo, int] | None:
    return match_bound_import_chain_prefix(module_info.exported_imports, chain)


def has_exported_import_chain_prefix(module_info: ModuleInfo, chain: tuple[str, ...] | list[str]) -> bool:
    return has_bound_import_chain_prefix(module_info.exported_imports, chain)


@dataclass
class ProgramInfo:
    entry_module: ModulePath
    modules: dict[ModulePath, ModuleInfo]


@dataclass
class _ResolveStats:
    lexed_token_count: int = 0
    lexed_file_count: int = 0
    lex_total_ms: float = 0.0
    parsed_token_count: int = 0
    parsed_stream_count: int = 0
    parse_total_ms: float = 0.0

    def record_lex(self, token_count: int, duration_ms: float) -> None:
        self.lexed_token_count += token_count
        self.lexed_file_count += 1
        self.lex_total_ms += duration_ms

    def record_parse(self, token_count: int, duration_ms: float) -> None:
        self.parsed_token_count += token_count
        self.parsed_stream_count += 1
        self.parse_total_ms += duration_ms


class ResolveError(ValueError):
    def __init__(self, message: str, span: SourceSpan | None = None, file_path: Path | None = None):
        if span is not None:
            super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        elif file_path is not None:
            super().__init__(f"{message} at {file_path.as_posix()}")
        else:
            super().__init__(message)
        self.message = message
        self.span = span
        self.file_path = file_path


def resolve(module_ast: ModuleAst) -> dict[str, SymbolInfo]:
    symbols, _ = _build_symbol_tables(module_ast, ())
    return symbols


def resolve_program(entry_file: str | Path, project_root: str | Path | None = None) -> ProgramInfo:
    logger = get_logger(__name__)
    entry_path = Path(entry_file).resolve()
    root_path = Path(project_root).resolve() if project_root is not None else entry_path.parent.resolve()

    if not entry_path.exists():
        raise ResolveError("Entry file does not exist", file_path=entry_path)

    entry_module = _file_path_to_module_path(entry_path, root_path)
    modules: dict[ModulePath, ModuleInfo] = {}
    visiting: set[ModulePath] = set()
    stats = _ResolveStats()

    def load_module(module_path: ModulePath) -> ModuleInfo:
        if module_path in modules:
            return modules[module_path]

        if module_path in visiting:
            cycle = ".".join(module_path)
            raise ResolveError(f"Import cycle detected at module '{cycle}'")

        visiting.add(module_path)
        file_path = _module_path_to_file_path(module_path, root_path)
        if not file_path.exists():
            dotted = ".".join(module_path)
            raise ResolveError(f"Module '{dotted}' not found", file_path=file_path)

        logger.debugv(1, "Resolver loading module %s from %s", ".".join(module_path), file_path.as_posix())

        source_text = file_path.read_text(encoding="utf-8")
        lex_start = perf_counter()
        tokens = lex(source_text, source_path=file_path.as_posix())
        stats.record_lex(len(tokens), (perf_counter() - lex_start) * 1000.0)

        parse_start = perf_counter()
        module_ast = parse(tokens)
        stats.record_parse(len(tokens), (perf_counter() - parse_start) * 1000.0)

        symbols, exported_symbols = _build_symbol_tables(module_ast, module_path)
        imports = _build_import_tables(module_ast)

        module_info = ModuleInfo(
            module_path=module_path,
            file_path=file_path,
            ast=module_ast,
            symbols=symbols,
            exported_symbols=exported_symbols,
            imports=imports,
            bound_imports=(),
            exported_imports=(),
        )
        modules[module_path] = module_info

        for import_info in imports.values():
            load_module(import_info.module_path)

        visiting.remove(module_path)
        return module_info

    load_module(entry_module)

    _populate_module_surfaces(modules)

    for module_info in modules.values():
        _validate_module_visibility(module_info, modules)

    logger.debugv(
        1,
        "Resolver lexed %d tokens from %d files in %.2f ms",
        stats.lexed_token_count,
        stats.lexed_file_count,
        stats.lex_total_ms,
    )
    logger.debugv(
        1,
        "Resolver parsed %d tokens from %d token streams in %.2f ms",
        stats.parsed_token_count,
        stats.parsed_stream_count,
        stats.parse_total_ms,
    )

    return ProgramInfo(entry_module=entry_module, modules=modules)


def _build_symbol_tables(module_ast: ModuleAst, module_path: ModulePath) -> tuple[dict[str, SymbolInfo], dict[str, SymbolInfo]]:
    symbols: dict[str, SymbolInfo] = {}
    exported: dict[str, SymbolInfo] = {}

    def add_symbol(name: str, kind: str, is_export: bool, span: SourceSpan) -> None:
        if name in symbols:
            raise ResolveError(f"Duplicate declaration '{name}'", span=span)

        info = SymbolInfo(name=name, kind=kind, is_export=is_export, span=span, owner_module_path=module_path)
        symbols[name] = info
        if is_export:
            exported[name] = info

    for class_decl in module_ast.classes:
        add_symbol(class_decl.name, "class", class_decl.is_export, class_decl.span)

    for interface_decl in module_ast.interfaces:
        add_symbol(interface_decl.name, "interface", interface_decl.is_export, interface_decl.span)

    for fn_decl in module_ast.functions:
        add_symbol(fn_decl.name, "function", fn_decl.is_export, fn_decl.span)

    return symbols, exported


def _effective_bind_path(import_info: ImportInfo) -> ModulePath:
    if import_info.bind_path is not None:
        return import_info.bind_path
    return import_info.module_path


def _populate_module_surfaces(modules: dict[ModulePath, ModuleInfo]) -> None:
    populated: set[ModulePath] = set()
    visiting: set[ModulePath] = set()

    def merge_symbol(
        merged_symbols: dict[str, SymbolInfo],
        merged_bindings: dict[ModulePath, BoundImportInfo],
        local_symbols: dict[str, SymbolInfo],
        symbol: SymbolInfo,
        *,
        conflict_span: SourceSpan,
        error_label: str,
    ) -> None:
        existing = merged_symbols.get(symbol.name)
        if existing is not None:
            if existing.kind == symbol.kind and existing.owner_module_path == symbol.owner_module_path:
                return
            raise ResolveError(f"Duplicate {error_label} '{symbol.name}'", span=conflict_span)

        if symbol.name in local_symbols:
            raise ResolveError(f"Duplicate {error_label} '{symbol.name}'", span=conflict_span)

        if any(binding.bind_path[0] == symbol.name for binding in merged_bindings.values()):
            raise ResolveError(f"Duplicate {error_label} '{symbol.name}'", span=conflict_span)

        merged_symbols[symbol.name] = symbol

    def merge_bound_path(
        merged_bindings: dict[ModulePath, BoundImportInfo],
        merged_symbols: dict[str, SymbolInfo],
        local_symbols: dict[str, SymbolInfo],
        bound_info: BoundImportInfo,
        *,
        conflict_span: SourceSpan,
        error_label: str,
    ) -> None:
        if not bound_info.bind_path:
            raise ResolveError("Internal error: bound import path must be non-empty", span=conflict_span)

        existing = merged_bindings.get(bound_info.bind_path)
        if existing is not None:
            if existing.module_path == bound_info.module_path:
                return
            dotted = ".".join(bound_info.bind_path)
            raise ResolveError(f"Duplicate {error_label} '{dotted}'", span=conflict_span)

        if bound_info.bind_path[0] in merged_symbols:
            dotted = ".".join(bound_info.bind_path)
            raise ResolveError(f"Duplicate {error_label} '{dotted}'", span=conflict_span)

        if bound_info.bind_path[0] in local_symbols:
            dotted = ".".join(bound_info.bind_path)
            raise ResolveError(f"Duplicate {error_label} '{dotted}'", span=conflict_span)

        merged_bindings[bound_info.bind_path] = bound_info

    def populate(module_path: ModulePath) -> None:
        if module_path in populated:
            return
        if module_path in visiting:
            dotted = ".".join(module_path)
            raise ResolveError(f"Import cycle detected at module '{dotted}'")

        visiting.add(module_path)
        module_info = modules[module_path]
        merged_symbols = dict(module_info.exported_symbols)
        merged_local_flattened_symbols: dict[str, SymbolInfo] = {}
        merged_bound_imports: dict[ModulePath, BoundImportInfo] = {}
        merged_exported_imports: dict[ModulePath, BoundImportInfo] = {}

        for import_info in module_info.imports.values():
            bind_path = _effective_bind_path(import_info)

            if bind_path:
                local_module_error_label = "exported module" if import_info.is_export else "import path"
                merge_bound_path(
                    merged_bound_imports,
                    merged_local_flattened_symbols,
                    module_info.symbols,
                    BoundImportInfo(bind_path=bind_path, module_path=import_info.module_path, span=import_info.span),
                    conflict_span=import_info.span,
                    error_label=local_module_error_label,
                )
            else:
                populate(import_info.module_path)
                imported_module = modules[import_info.module_path]
                local_symbol_error_label = "exported symbol" if import_info.is_export else "imported symbol"
                local_module_error_label = "exported module" if import_info.is_export else "import path"
                for symbol in imported_module.exported_symbols.values():
                    merge_symbol(
                        merged_local_flattened_symbols,
                        merged_bound_imports,
                        module_info.symbols,
                        symbol,
                        conflict_span=import_info.span,
                        error_label=local_symbol_error_label,
                    )
                for exported_import in imported_module.exported_imports:
                    merge_bound_path(
                        merged_bound_imports,
                        merged_local_flattened_symbols,
                        module_info.symbols,
                        exported_import,
                        conflict_span=import_info.span,
                        error_label=local_module_error_label,
                    )

            if not import_info.is_export:
                continue

            if bind_path:
                merge_bound_path(
                    merged_exported_imports,
                    merged_symbols,
                    module_info.symbols,
                    BoundImportInfo(bind_path=bind_path, module_path=import_info.module_path, span=import_info.span),
                    conflict_span=import_info.span,
                    error_label="exported module",
                )
                continue

            # `as .` merges the imported module's exported surface directly into this module root.
            imported_module = modules[import_info.module_path]
            for symbol in imported_module.exported_symbols.values():
                merge_symbol(
                    merged_symbols,
                    merged_exported_imports,
                    module_info.symbols,
                    symbol,
                    conflict_span=import_info.span,
                    error_label="exported symbol",
                )
            for exported_import in imported_module.exported_imports:
                merge_bound_path(
                    merged_exported_imports,
                    merged_symbols,
                    module_info.symbols,
                    exported_import,
                    conflict_span=import_info.span,
                    error_label="exported module",
                )

        module_info.bound_imports = tuple(merged_bound_imports[path] for path in sorted(merged_bound_imports))
        module_info.exported_symbols = merged_symbols
        module_info.exported_imports = tuple(merged_exported_imports[path] for path in sorted(merged_exported_imports))
        visiting.remove(module_path)
        populated.add(module_path)

    for module_path in modules:
        populate(module_path)


def _build_import_tables(module_ast: ModuleAst) -> dict[str, ImportInfo]:
    imports: dict[str, ImportInfo] = {}
    bound_paths: set[ModulePath] = set()

    for index, import_decl in enumerate(module_ast.imports):
        module_path = tuple(import_decl.module_path)
        info = ImportInfo(
            module_path=module_path,
            bind_path=None if import_decl.bind_path is None else tuple(import_decl.bind_path),
            is_export=import_decl.is_export,
            span=import_decl.span,
        )
        effective_bind_path = _effective_bind_path(info)
        if effective_bind_path:
            if effective_bind_path in bound_paths:
                dotted = ".".join(effective_bind_path)
                raise ResolveError(f"Duplicate import path '{dotted}'", span=import_decl.span)
            bound_paths.add(effective_bind_path)

        import_key = f"{index}:{'.'.join(module_path)}"
        imports[import_key] = info

    return imports


def _validate_module_visibility(module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]) -> None:
    for fn_decl in module_info.ast.functions:
        if fn_decl.body is None:
            continue
        _validate_block(fn_decl.body, module_info, modules)

    for class_decl in module_info.ast.classes:
        for method in class_decl.methods:
            _validate_block(method.body, module_info, modules)


def _validate_block(block: BlockStmt, module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]) -> None:
    for stmt in block.statements:
        _validate_statement(stmt, module_info, modules)


def _validate_statement(stmt: Statement, module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]) -> None:
    if isinstance(stmt, BlockStmt):
        _validate_block(stmt, module_info, modules)
        return

    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            _validate_expression(stmt.initializer, module_info, modules)
        return

    if isinstance(stmt, IfStmt):
        _validate_expression(stmt.condition, module_info, modules)
        _validate_block(stmt.then_branch, module_info, modules)
        if isinstance(stmt.else_branch, BlockStmt):
            _validate_block(stmt.else_branch, module_info, modules)
        elif isinstance(stmt.else_branch, IfStmt):
            _validate_statement(stmt.else_branch, module_info, modules)
        return

    if isinstance(stmt, WhileStmt):
        _validate_expression(stmt.condition, module_info, modules)
        _validate_block(stmt.body, module_info, modules)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _validate_expression(stmt.value, module_info, modules)
        return

    if isinstance(stmt, AssignStmt):
        _validate_expression(stmt.target, module_info, modules)
        _validate_expression(stmt.value, module_info, modules)
        return

    if isinstance(stmt, ExprStmt):
        _validate_expression(stmt.expression, module_info, modules)


def _validate_expression(expr: Expression, module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]) -> None:
    if isinstance(expr, BinaryExpr):
        _validate_expression(expr.left, module_info, modules)
        _validate_expression(expr.right, module_info, modules)
        return

    if isinstance(expr, UnaryExpr):
        _validate_expression(expr.operand, module_info, modules)
        return

    if isinstance(expr, CastExpr):
        _validate_expression(expr.operand, module_info, modules)
        return

    if isinstance(expr, TypeTestExpr):
        _validate_expression(expr.operand, module_info, modules)
        return

    if isinstance(expr, CallExpr):
        _validate_expression(expr.callee, module_info, modules)
        for arg in expr.arguments:
            _validate_expression(arg, module_info, modules)
        return

    if isinstance(expr, FieldAccessExpr):
        _validate_expression(expr.object_expr, module_info, modules)
        _resolve_module_chain(expr, module_info, modules)
        return

    if isinstance(expr, IndexExpr):
        _validate_expression(expr.object_expr, module_info, modules)
        _validate_expression(expr.index_expr, module_info, modules)
        return


def _resolve_module_chain(
    expr: FieldAccessExpr, module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]
) -> ModuleInfo | None:
    chain = _flatten_field_chain(expr)
    if chain is None or len(chain) < 2:
        return None

    matched_import = match_bound_import_chain_prefix(module_info.bound_imports, chain)
    if matched_import is None:
        return None

    import_info, consumed = matched_import
    current_module = modules[import_info.module_path]
    return _resolve_module_chain_tail(current_module, chain[consumed:], expr.span, modules)


def _flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]
    if isinstance(expr, FieldAccessExpr):
        left = _flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]
    return None


def _resolve_module_chain_tail(
    current_module: ModuleInfo,
    remaining_segments: list[str] | tuple[str, ...],
    span: SourceSpan,
    modules: dict[ModulePath, ModuleInfo],
) -> ModuleInfo | None:
    remaining = tuple(remaining_segments)
    if not remaining:
        return current_module

    while remaining:
        matched_export = match_exported_import_chain_prefix(current_module, remaining)
        if matched_export is not None:
            export_info, consumed = matched_export
            current_module = modules[export_info.module_path]
            remaining = remaining[consumed:]
            if not remaining:
                return current_module
            continue

        if has_exported_import_chain_prefix(current_module, remaining):
            return current_module

        if remaining[0] in current_module.exported_symbols:
            return None

        dotted = ".".join(current_module.module_path)
        raise ResolveError(f"Module '{dotted}' has no exported member '{remaining[0]}'", span=span)

    return current_module


def _file_path_to_module_path(file_path: Path, root_path: Path) -> ModulePath:
    rel = file_path.relative_to(root_path)
    if rel.suffix != ".nif":
        raise ResolveError("Expected .nif source file", file_path=file_path)
    parts = rel.with_suffix("").parts
    if not parts:
        raise ResolveError("Invalid module path", file_path=file_path)
    return tuple(parts)


def _module_path_to_file_path(module_path: ModulePath, root_path: Path) -> Path:
    return root_path.joinpath(*module_path).with_suffix(".nif")
