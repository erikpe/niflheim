from __future__ import annotations

from compiler.ast_nodes import ArrayTypeRef, ModuleAst, TypeRef
from compiler.resolver import ProgramInfo


def _type_ref_name(type_ref: TypeRef | ArrayTypeRef) -> str:
    if isinstance(type_ref, TypeRef):
        return type_ref.name
    return f"{_type_ref_name(type_ref.element_type)}[]"


def require_main_function(module_ast: ModuleAst) -> None:
    main_decl = next((fn for fn in module_ast.functions if fn.name == "main"), None)
    if main_decl is None:
        raise ValueError("Program entrypoint missing: expected 'fn main() -> i64'")
    if main_decl.is_extern or main_decl.body is None:
        raise ValueError("Invalid main signature: expected concrete definition 'fn main() -> i64'")
    if main_decl.params:
        raise ValueError("Invalid main signature: expected 'fn main() -> i64' (no parameters)")
    if _type_ref_name(main_decl.return_type) != "i64":
        raise ValueError("Invalid main signature: expected return type 'i64'")


def build_codegen_module(program: ProgramInfo) -> ModuleAst:
    entry_module = program.modules[program.entry_module]
    ordered_module_paths = [
        module_path
        for module_path in sorted(program.modules)
        if module_path != program.entry_module
    ]
    ordered_module_paths.append(program.entry_module)

    merged_functions = []
    merged_classes = []
    function_index_by_name: dict[str, int] = {}
    function_has_body: dict[str, bool] = {}
    function_owner_by_name: dict[str, tuple[str, ...]] = {}
    class_owner_by_name: dict[str, tuple[str, ...]] = {}

    for module_path in ordered_module_paths:
        module_info = program.modules[module_path]
        for class_decl in module_info.ast.classes:
            existing_owner = class_owner_by_name.get(class_decl.name)
            if existing_owner is not None:
                first_owner = ".".join(existing_owner)
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate class symbol '{class_decl.name}' across modules ({first_owner}, {current_owner})"
                )

            class_owner_by_name[class_decl.name] = module_path
            merged_classes.append(class_decl)

        for fn_decl in module_info.ast.functions:
            existing_index = function_index_by_name.get(fn_decl.name)
            has_body = fn_decl.body is not None

            if existing_index is None:
                function_index_by_name[fn_decl.name] = len(merged_functions)
                function_has_body[fn_decl.name] = has_body
                function_owner_by_name[fn_decl.name] = module_path
                merged_functions.append(fn_decl)
                continue

            if function_has_body[fn_decl.name] and has_body:
                first_owner = ".".join(function_owner_by_name[fn_decl.name])
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate function symbol '{fn_decl.name}' across modules ({first_owner}, {current_owner})"
                )

            if not function_has_body[fn_decl.name] and has_body:
                merged_functions[existing_index] = fn_decl
                function_has_body[fn_decl.name] = True
                function_owner_by_name[fn_decl.name] = module_path

    return ModuleAst(
        imports=entry_module.ast.imports,
        classes=merged_classes,
        functions=merged_functions,
        span=entry_module.ast.span,
    )
