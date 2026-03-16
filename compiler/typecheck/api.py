from __future__ import annotations

from compiler.ast_nodes import ModuleAst
from compiler.resolver import ModulePath, ProgramInfo
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.engine import TypeChecker
from compiler.typecheck.model import ClassInfo, FunctionSig


def typecheck_program(program: ProgramInfo) -> None:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {}
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {}

    for module_path, module_info in program.modules.items():
        checker = TypeChecker(
            module_info.ast,
            module_path=module_path,
            modules=program.modules,
        )
        collect_module_declarations(
            checker.ctx,
            infer_expression_type=checker._infer_expression_type,
            require_assignable=checker._require_assignable,
        )
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
