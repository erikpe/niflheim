from __future__ import annotations

from compiler.frontend.ast_nodes import ModuleAst
from compiler.resolver import ModulePath, ProgramInfo
from compiler.typecheck.bodies import check_bodies
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.declarations import collect_module_declarations, validate_interface_conformance
from compiler.typecheck.model import ClassInfo, FunctionSig, InterfaceInfo


def typecheck_program(program: ProgramInfo) -> None:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {
        module_path: {} for module_path in program.modules
    }
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {module_path: {} for module_path in program.modules}
    module_interface_infos: dict[ModulePath, dict[str, InterfaceInfo]] = {module_path: {} for module_path in program.modules}
    contexts: list[TypeCheckContext] = []

    for module_path, module_info in program.modules.items():
        contexts.append(
            TypeCheckContext(
                module_ast=module_info.ast,
                module_path=module_path,
                modules=program.modules,
                module_function_sigs=module_function_sigs,
                module_class_infos=module_class_infos,
                module_interface_infos=module_interface_infos,
                functions=module_function_sigs[module_path],
                classes=module_class_infos[module_path],
                interfaces=module_interface_infos[module_path],
            )
        )

    for ctx in contexts:
        collect_module_declarations(ctx)

    for ctx in contexts:
        validate_interface_conformance(ctx)

    for ctx in contexts:
        check_bodies(ctx)


def typecheck(module_ast: ModuleAst) -> None:
    ctx = TypeCheckContext(module_ast=module_ast)
    collect_module_declarations(ctx)
    validate_interface_conformance(ctx)
    check_bodies(ctx)
