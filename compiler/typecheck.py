from __future__ import annotations

from compiler.ast_nodes import ModuleAst
from compiler.resolver import ProgramInfo, ModulePath
from compiler.typecheck_checker import TypeChecker
from compiler.typecheck_model import ClassInfo, FunctionSig


def typecheck_program(program: ProgramInfo) -> None:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {}
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {}

    for module_path, module_info in program.modules.items():
        checker = TypeChecker(module_info.ast)
        checker._collect_declarations()
        module_function_sigs[module_path] = checker.functions
        module_class_infos[module_path] = checker.classes

    for module_path, module_info in program.modules.items():
        checker = TypeChecker(
            module_info.ast,
            module_path=module_path,
            modules=program.modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            pre_collected=True,
        )
        checker.check()


def typecheck(module_ast: ModuleAst) -> None:
    TypeChecker(module_ast).check()
