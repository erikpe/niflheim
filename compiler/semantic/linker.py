from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_I64
from compiler.common.span import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.ir import SemanticClass, SemanticFunction, SemanticModule, SemanticProgram
from compiler.semantic.types import semantic_type_canonical_name


@dataclass(frozen=True)
class LinkedSemanticProgram:
    entry_module: ModulePath
    ordered_modules: tuple[SemanticModule, ...]
    classes: tuple[SemanticClass, ...]
    functions: tuple[SemanticFunction, ...]
    span: SourceSpan


def require_main_function(program: LinkedSemanticProgram) -> None:
    main_decl = next(
        (
            fn
            for fn in program.functions
            if fn.function_id.module_path == program.entry_module and fn.function_id.name == "main"
        ),
        None,
    )
    if main_decl is None:
        raise ValueError("Program entrypoint missing: expected 'fn main() -> i64'")
    if main_decl.is_extern or main_decl.body is None:
        raise ValueError("Invalid main signature: expected concrete definition 'fn main() -> i64'")
    if main_decl.params:
        raise ValueError("Invalid main signature: expected 'fn main() -> i64' (no parameters)")
    if semantic_type_canonical_name(main_decl.return_type_ref) != TYPE_NAME_I64:
        raise ValueError("Invalid main signature: expected return type 'i64'")


def link_semantic_program(program: SemanticProgram) -> LinkedSemanticProgram:
    entry_module = program.modules[program.entry_module]
    ordered_module_paths = [
        module_path for module_path in sorted(program.modules) if module_path != program.entry_module
    ]
    ordered_module_paths.append(program.entry_module)

    ordered_modules: list[SemanticModule] = []
    merged_functions: list[SemanticFunction] = []
    merged_classes: list[SemanticClass] = []

    for module_path in ordered_module_paths:
        module_info = program.modules[module_path]
        ordered_modules.append(module_info)

        for class_decl in module_info.classes:
            merged_classes.append(class_decl)

        for fn_decl in module_info.functions:
            merged_functions.append(fn_decl)

    return LinkedSemanticProgram(
        entry_module=program.entry_module,
        ordered_modules=tuple(ordered_modules),
        classes=tuple(merged_classes),
        functions=tuple(merged_functions),
        span=entry_module.span,
    )
