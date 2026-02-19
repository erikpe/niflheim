from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from compiler.ast_nodes import *
from compiler.lexer import SourceSpan, lex
from compiler.parser import parse


ModulePath = tuple[str, ...]


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    kind: str
    is_export: bool
    span: SourceSpan


@dataclass(frozen=True)
class ImportInfo:
    alias: str
    module_path: ModulePath
    is_export: bool
    span: SourceSpan


@dataclass
class ModuleInfo:
    module_path: ModulePath
    file_path: Path
    ast: ModuleAst
    symbols: dict[str, SymbolInfo]
    exported_symbols: dict[str, SymbolInfo]
    imports: dict[str, ImportInfo]
    exported_modules: dict[str, ModulePath]


@dataclass
class ProgramInfo:
    entry_module: ModulePath
    modules: dict[ModulePath, ModuleInfo]


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
    symbols, _ = _build_symbol_tables(module_ast)
    return symbols


def resolve_program(entry_file: str | Path, project_root: str | Path | None = None) -> ProgramInfo:
    entry_path = Path(entry_file).resolve()
    root_path = Path(project_root).resolve() if project_root is not None else entry_path.parent.resolve()

    if not entry_path.exists():
        raise ResolveError("Entry file does not exist", file_path=entry_path)

    entry_module = _file_path_to_module_path(entry_path, root_path)
    modules: dict[ModulePath, ModuleInfo] = {}
    visiting: set[ModulePath] = set()

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

        source_text = file_path.read_text(encoding="utf-8")
        tokens = lex(source_text, source_path=file_path.as_posix())
        module_ast = parse(tokens)

        symbols, exported_symbols = _build_symbol_tables(module_ast)
        imports, exported_modules = _build_import_tables(module_ast)

        module_info = ModuleInfo(
            module_path=module_path,
            file_path=file_path,
            ast=module_ast,
            symbols=symbols,
            exported_symbols=exported_symbols,
            imports=imports,
            exported_modules=exported_modules,
        )
        modules[module_path] = module_info

        for import_info in imports.values():
            load_module(import_info.module_path)

        visiting.remove(module_path)
        return module_info

    load_module(entry_module)

    for module_info in modules.values():
        _validate_module_visibility(module_info, modules)

    return ProgramInfo(entry_module=entry_module, modules=modules)


def _build_symbol_tables(module_ast: ModuleAst) -> tuple[dict[str, SymbolInfo], dict[str, SymbolInfo]]:
    symbols: dict[str, SymbolInfo] = {}
    exported: dict[str, SymbolInfo] = {}

    def add_symbol(name: str, kind: str, is_export: bool, span: SourceSpan) -> None:
        if name in symbols:
            raise ResolveError(f"Duplicate declaration '{name}'", span=span)

        info = SymbolInfo(name=name, kind=kind, is_export=is_export, span=span)
        symbols[name] = info
        if is_export:
            exported[name] = info

    for class_decl in module_ast.classes:
        add_symbol(class_decl.name, "class", class_decl.is_export, class_decl.span)

    for fn_decl in module_ast.functions:
        add_symbol(fn_decl.name, "function", fn_decl.is_export, fn_decl.span)

    return symbols, exported


def _build_import_tables(module_ast: ModuleAst) -> tuple[dict[str, ImportInfo], dict[str, ModulePath]]:
    imports: dict[str, ImportInfo] = {}
    exported_modules: dict[str, ModulePath] = {}

    for import_decl in module_ast.imports:
        module_path = tuple(import_decl.module_path)
        alias = module_path[-1]
        if alias in imports:
            raise ResolveError(f"Duplicate import alias '{alias}'", span=import_decl.span)

        info = ImportInfo(
            alias=alias,
            module_path=module_path,
            is_export=import_decl.is_export,
            span=import_decl.span,
        )
        imports[alias] = info

        if import_decl.is_export:
            exported_modules[alias] = module_path

    return imports, exported_modules


def _validate_module_visibility(module_info: ModuleInfo, modules: dict[ModulePath, ModuleInfo]) -> None:
    for fn_decl in module_info.ast.functions:
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
    expr: FieldAccessExpr,
    module_info: ModuleInfo,
    modules: dict[ModulePath, ModuleInfo],
) -> ModuleInfo | None:
    left = expr.object_expr

    if isinstance(left, IdentifierExpr):
        import_info = module_info.imports.get(left.name)
        if import_info is None:
            return None

        target_module = modules[import_info.module_path]
        return _resolve_exported_member(target_module, expr.field_name, expr.span, modules)

    if isinstance(left, FieldAccessExpr):
        base_module = _resolve_module_chain(left, module_info, modules)
        if base_module is None:
            return None
        return _resolve_exported_member(base_module, expr.field_name, expr.span, modules)

    return None


def _resolve_exported_member(
    target_module: ModuleInfo,
    member_name: str,
    span: SourceSpan,
    modules: dict[ModulePath, ModuleInfo],
) -> ModuleInfo | None:
    if member_name in target_module.exported_symbols:
        return None

    module_path = target_module.exported_modules.get(member_name)
    if module_path is not None:
        return modules[module_path]

    dotted = ".".join(target_module.module_path)
    raise ResolveError(f"Module '{dotted}' has no exported member '{member_name}'", span=span)


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
