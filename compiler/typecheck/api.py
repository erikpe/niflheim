from __future__ import annotations

from compiler.ast_nodes import ModuleAst
from compiler.resolver import ModulePath, ProgramInfo
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.engine import TypeChecker
from compiler.typecheck.model import ClassInfo, FunctionSig


def typecheck_program(program: ProgramInfo) -> None:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {
        module_path: {}
        for module_path in program.modules
    }
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {
        module_path: {}
        for module_path in program.modules
    }
    checkers: list[TypeChecker] = []

    for module_path, module_info in program.modules.items():
        checker = TypeChecker(
            module_info.ast,
            module_path=module_path,
            modules=program.modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
        )
        checkers.append(checker)

    for checker in checkers:
        collect_module_declarations(checker)

    for checker in checkers:
        checker.check_bodies()


def typecheck(module_ast: ModuleAst) -> None:
    checker = TypeChecker(module_ast)
    collect_module_declarations(checker)
    checker.check_bodies()
