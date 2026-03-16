from __future__ import annotations

from compiler.ast_nodes import *
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.expressions import infer_expression_type as expressions_infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.statements import check_function_like as statements_check_function_like


class TypeChecker:
    def __init__(
        self,
        module_ast: ModuleAst,
        *,
        module_path: ModulePath | None = None,
        modules: dict[ModulePath, ModuleInfo] | None = None,
        module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] | None = None,
        module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None = None,
    ):
        functions: dict[str, FunctionSig]
        classes: dict[str, ClassInfo]
        if module_path is not None and module_function_sigs is not None and module_class_infos is not None:
            functions = module_function_sigs[module_path]
            classes = module_class_infos[module_path]
        else:
            functions = {}
            classes = {}

        self.declarations_collected = (
            module_path is not None and module_function_sigs is not None and module_class_infos is not None
        )
        self.ctx = TypeCheckContext(
            module_ast=module_ast,
            module_path=module_path,
            modules=modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            functions=functions,
            classes=classes,
        )
        self.functions = self.ctx.functions
        self.classes = self.ctx.classes

    def collect_declarations(self) -> None:
        if self.declarations_collected:
            return

        collect_module_declarations(self.ctx, self)
        self.declarations_collected = True

    def check_bodies(self) -> None:
        if not self.declarations_collected:
            collect_module_declarations(self.ctx, self)
            self.declarations_collected = True

        for fn_decl in self.ctx.module_ast.functions:
            if fn_decl.is_extern:
                continue
            fn_sig = self.functions[fn_decl.name]
            if fn_decl.body is None:
                raise TypeCheckError("Function declaration missing body", fn_decl.span)
            statements_check_function_like(self, fn_decl.params, fn_decl.body, fn_sig.return_type)

        for class_decl in self.ctx.module_ast.classes:
            class_info = self.classes[class_decl.name]
            for method_decl in class_decl.methods:
                method_sig = class_info.methods[method_decl.name]
                statements_check_function_like(
                    self,
                    method_decl.params,
                    method_decl.body,
                    method_sig.return_type,
                    receiver_type=None if method_sig.is_static else TypeInfo(name=class_info.name, kind="reference"),
                    owner_class_name=class_info.name,
                )

    def check(self) -> None:
        self.collect_declarations()
        self.check_bodies()

    def infer_expression_type(self, expr: Expression) -> TypeInfo:
        return expressions_infer_expression_type(self, expr)
