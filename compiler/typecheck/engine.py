from __future__ import annotations

from compiler.ast_nodes import *
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.context import (
    TypeCheckContext,
    lookup_variable as context_lookup_variable,
)
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.expressions import infer_expression_type as expressions_infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name as lookup_lookup_class_by_type_name
from compiler.typecheck.relations import (
    check_explicit_cast as relation_check_explicit_cast,
    is_comparable as relation_is_comparable,
    require_array_size_type as relation_require_array_size_type,
)
from compiler.typecheck.statements import (
    check_function_like as statements_check_function_like,
)
from compiler.typecheck.structural import (
    ensure_index_assignment as structural_ensure_index_assignment,
    ensure_structural_set_method_available_for_index_assignment as structural_ensure_structural_set_method_available_for_index_assignment,
    resolve_for_in_element_type as structural_resolve_for_in_element_type,
    resolve_structural_set_slice_method_result_type as structural_resolve_structural_set_slice_method_result_type,
    resolve_structural_slice_method_result_type as structural_resolve_structural_slice_method_result_type,
)
from compiler.typecheck.type_resolution import resolve_type_ref as resolution_resolve_type_ref


class TypeChecker:
    def __init__(
        self,
        module_ast: ModuleAst,
        *,
        module_path: ModulePath | None = None,
        modules: dict[ModulePath, ModuleInfo] | None = None,
        module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] | None = None,
        module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None = None,
        pre_collected: bool = False,
    ):
        functions: dict[str, FunctionSig]
        classes: dict[str, ClassInfo]
        if module_path is not None and module_function_sigs is not None and module_class_infos is not None:
            functions = module_function_sigs[module_path]
            classes = module_class_infos[module_path]
        else:
            functions = {}
            classes = {}

        self.pre_collected = pre_collected
        self.ctx = TypeCheckContext(
            module_ast=module_ast,
            module_path=module_path,
            modules=modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            pre_collected=pre_collected,
            functions=functions,
            classes=classes,
        )
        self.functions = self.ctx.functions
        self.classes = self.ctx.classes

    def check(self) -> None:
        if not self.pre_collected:
            collect_module_declarations(self.ctx, self)

        for fn_decl in self.ctx.module_ast.functions:
            if fn_decl.is_extern:
                continue
            fn_sig = self.functions[fn_decl.name]
            if fn_decl.body is None:
                raise TypeCheckError("Function declaration missing body", fn_decl.span)
            self._check_function_like(fn_decl.params, fn_decl.body, fn_sig.return_type)

        for class_decl in self.ctx.module_ast.classes:
            class_info = self.classes[class_decl.name]
            for method_decl in class_decl.methods:
                method_sig = class_info.methods[method_decl.name]
                self._check_function_like(
                    method_decl.params,
                    method_decl.body,
                    method_sig.return_type,
                    receiver_type=None if method_sig.is_static else TypeInfo(name=class_info.name, kind="reference"),
                    owner_class_name=class_info.name,
                )

    def _check_function_like(
        self,
        params: list[ParamDecl],
        body: BlockStmt,
        return_type: TypeInfo,
        *,
        receiver_type: TypeInfo | None = None,
        owner_class_name: str | None = None,
    ) -> None:
        statements_check_function_like(
            self,
            params,
            body,
            return_type,
            receiver_type=receiver_type,
            owner_class_name=owner_class_name,
        )

    def infer_expression_type(self, expr: Expression) -> TypeInfo:
        return expressions_infer_expression_type(self, expr)

    def lookup_variable(self, name: str) -> TypeInfo | None:
        return context_lookup_variable(self.ctx, name)

    def require_type_name(self, actual: TypeInfo, expected_name: str, span: SourceSpan) -> None:
        from compiler.typecheck.relations import require_type_name

        require_type_name(actual, expected_name, span)

    def require_array_size_type(self, actual: TypeInfo, span: SourceSpan) -> None:
        relation_require_array_size_type(actual, span)

    def is_comparable(self, left: TypeInfo, right: TypeInfo) -> bool:
        return relation_is_comparable(self.ctx, left, right)

    def check_explicit_cast(self, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
        relation_check_explicit_cast(self.ctx, source, target, span)

    def resolve_for_in_element_type(self, collection_type: TypeInfo, span: SourceSpan) -> TypeInfo:
        return structural_resolve_for_in_element_type(self, collection_type, span)

    def ensure_structural_set_method_available_for_index_assignment(
        self,
        object_type: TypeInfo,
        span: SourceSpan,
    ) -> FunctionSig:
        return structural_ensure_structural_set_method_available_for_index_assignment(self, object_type, span)

    def ensure_index_assignment(
        self,
        object_type: TypeInfo,
        index_expr: Expression,
        value_type: TypeInfo,
        span: SourceSpan,
    ) -> None:
        structural_ensure_index_assignment(self, object_type, index_expr, value_type, span)

    def resolve_structural_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        return structural_resolve_structural_slice_method_result_type(self, object_type, class_info, args, span)

    def resolve_structural_set_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        return structural_resolve_structural_set_slice_method_result_type(self, object_type, class_info, args, span)
