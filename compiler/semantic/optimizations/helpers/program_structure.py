from __future__ import annotations

from dataclasses import replace
from typing import Callable

from compiler.semantic.ir import (
    SemanticField,
    SemanticFunction,
    SemanticMethod,
    SemanticProgram,
    SemanticModule,
    SemanticClass,
)


FieldRewriter = Callable[[SemanticField], SemanticField]
FunctionRewriter = Callable[[SemanticFunction], SemanticFunction]
MethodRewriter = Callable[[SemanticMethod], SemanticMethod]


def rewrite_program_structure(
    program: SemanticProgram,
    *,
    rewrite_field: FieldRewriter,
    rewrite_function: FunctionRewriter,
    rewrite_method: MethodRewriter,
) -> SemanticProgram:
    return SemanticProgram(
        entry_module=program.entry_module,
        modules={
            module_path: _rewrite_module_structure(module, rewrite_field, rewrite_function, rewrite_method)
            for module_path, module in program.modules.items()
        },
    )


def _rewrite_module_structure(
    module: SemanticModule,
    rewrite_field: FieldRewriter,
    rewrite_function: FunctionRewriter,
    rewrite_method: MethodRewriter,
) -> SemanticModule:
    return replace(
        module,
        classes=[_rewrite_class_structure(cls, rewrite_field, rewrite_method) for cls in module.classes],
        functions=[rewrite_function(fn) for fn in module.functions],
        interfaces=list(module.interfaces),
    )


def _rewrite_class_structure(
    cls: SemanticClass, rewrite_field: FieldRewriter, rewrite_method: MethodRewriter
) -> SemanticClass:
    return replace(
        cls,
        fields=[rewrite_field(field) for field in cls.fields],
        methods=[rewrite_method(method) for method in cls.methods],
    )
