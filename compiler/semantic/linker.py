from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_I64
from compiler.common.span import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.ir import SemanticClass, SemanticFunction, SemanticModule, SemanticProgram


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
    if main_decl.return_type_name != TYPE_NAME_I64:
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
    function_index_by_name: dict[str, int] = {}
    function_has_body: dict[str, bool] = {}
    function_owner_by_name: dict[str, ModulePath] = {}
    class_owner_by_name: dict[str, ModulePath] = {}

    for module_path in ordered_module_paths:
        module_info = program.modules[module_path]
        ordered_modules.append(module_info)

        for class_decl in module_info.classes:
            class_name = class_decl.class_id.name
            existing_owner = class_owner_by_name.get(class_name)
            if existing_owner is not None:
                first_owner = ".".join(existing_owner)
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate class symbol '{class_name}' across modules ({first_owner}, {current_owner})"
                )

            class_owner_by_name[class_name] = module_path
            merged_classes.append(class_decl)

        for fn_decl in module_info.functions:
            fn_name = fn_decl.function_id.name
            existing_index = function_index_by_name.get(fn_name)
            has_body = fn_decl.body is not None

            if existing_index is None:
                function_index_by_name[fn_name] = len(merged_functions)
                function_has_body[fn_name] = has_body
                function_owner_by_name[fn_name] = module_path
                merged_functions.append(fn_decl)
                continue

            if function_has_body[fn_name] and has_body:
                first_owner = ".".join(function_owner_by_name[fn_name])
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate function symbol '{fn_name}' across modules ({first_owner}, {current_owner})"
                )

            if not function_has_body[fn_name] and has_body:
                merged_functions[existing_index] = fn_decl
                function_has_body[fn_name] = True
                function_owner_by_name[fn_name] = module_path

    return LinkedSemanticProgram(
        entry_module=program.entry_module,
        ordered_modules=tuple(ordered_modules),
        classes=tuple(merged_classes),
        functions=tuple(merged_functions),
        span=entry_module.span,
    )
