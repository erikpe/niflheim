from __future__ import annotations

from compiler.ast_nodes import *
from compiler.codegen.strings import STR_CLASS_NAME, is_str_type_name
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.constants import (
    ARRAY_METHOD_NAMES,
    BITWISE_TYPE_NAMES,
    I64_MAX_LITERAL,
    I64_MIN_MAGNITUDE_LITERAL,
    U64_MAX_LITERAL,
)
from compiler.typecheck.calls import (
    callable_type_from_signature as calls_callable_type_from_signature,
    check_call_arguments as calls_check_call_arguments,
    class_type_name_from_callable as calls_class_type_name_from_callable,
    infer_call_type as calls_infer_call_type,
    infer_constructor_call_type as calls_infer_constructor_call_type,
)
from compiler.typecheck.context import (
    TypeCheckContext,
    declare_variable as context_declare_variable,
    lookup_variable as context_lookup_variable,
    pop_scope as context_pop_scope,
    push_scope as context_push_scope,
)
from compiler.typecheck.declarations import (
    check_constant_field_initializer as declarations_check_constant_field_initializer,
    collect_module_declarations as declarations_collect_module_declarations,
    function_sig_from_decl as declarations_function_sig_from_decl,
)
from compiler.typecheck.expressions import (
    ensure_field_access_assignable as expressions_ensure_field_access_assignable,
    infer_expression_type as expressions_infer_expression_type,
)
from compiler.typecheck.model import (
    ClassInfo,
    FunctionSig,
    NUMERIC_TYPE_NAMES,
    PRIMITIVE_TYPE_NAMES,
    REFERENCE_BUILTIN_TYPE_NAMES,
    TypeCheckError,
    TypeInfo,
)
from compiler.typecheck.module_lookup import (
    current_module_info as lookup_current_module_info,
    flatten_field_chain as lookup_flatten_field_chain,
    lookup_class_by_type_name as lookup_lookup_class_by_type_name,
    resolve_imported_class_name as lookup_resolve_imported_class_name,
    resolve_imported_function_sig as lookup_resolve_imported_function_sig,
    resolve_module_member as lookup_resolve_module_member,
    resolve_qualified_imported_class_name as lookup_resolve_qualified_imported_class_name,
    resolve_unique_global_class_name as lookup_resolve_unique_global_class_name,
    resolve_unique_imported_class_module as lookup_resolve_unique_imported_class_module,
)
from compiler.typecheck.relations import (
    canonicalize_reference_type_name as relation_canonicalize_reference_type_name,
    check_explicit_cast as relation_check_explicit_cast,
    display_type_name as relation_display_type_name,
    format_function_type_name as relation_format_function_type_name,
    is_comparable as relation_is_comparable,
    require_array_index_type as relation_require_array_index_type,
    require_array_size_type as relation_require_array_size_type,
    require_assignable as relation_require_assignable,
    require_type_name as relation_require_type_name,
    type_infos_equal as relation_type_infos_equal,
    type_names_equal as relation_type_names_equal,
)
from compiler.typecheck.structural import (
    ensure_index_assignment as structural_ensure_index_assignment,
    ensure_structural_set_method_available_for_index_assignment as structural_ensure_structural_set_method_available_for_index_assignment,
    ensure_structural_set_method_for_index_assignment as structural_ensure_structural_set_method_for_index_assignment,
    resolve_for_in_element_type as structural_resolve_for_in_element_type,
    resolve_index_expression_type as structural_resolve_index_expression_type,
    resolve_structural_get_method_result_type as structural_resolve_structural_get_method_result_type,
    resolve_structural_set_slice_method_result_type as structural_resolve_structural_set_slice_method_result_type,
    resolve_structural_slice_method_result_type as structural_resolve_structural_slice_method_result_type,
)
from compiler.typecheck.statements import (
    block_guarantees_return as statements_block_guarantees_return,
    check_block as statements_check_block,
    check_function_like as statements_check_function_like,
    check_statement as statements_check_statement,
    ensure_assignable_target as statements_ensure_assignable_target,
    ensure_field_access_assignable as statements_ensure_field_access_assignable,
    require_member_visible as statements_require_member_visible,
    statement_guarantees_return as statements_statement_guarantees_return,
)
from compiler.typecheck.type_resolution import (
    qualify_member_type_for_owner as resolution_qualify_member_type_for_owner,
    resolve_string_type as resolution_resolve_string_type,
    resolve_type_ref as resolution_resolve_type_ref,
)


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
        self.module_ast = module_ast
        self.module_path = module_path
        self.modules = modules
        self.module_function_sigs = module_function_sigs
        self.module_class_infos = module_class_infos
        self.pre_collected = pre_collected

        functions: dict[str, FunctionSig]
        classes: dict[str, ClassInfo]
        if module_path is not None and module_function_sigs is not None and module_class_infos is not None:
            functions = module_function_sigs[module_path]
            classes = module_class_infos[module_path]
        else:
            functions = {}
            classes = {}

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
            self._collect_declarations()

        for fn_decl in self.module_ast.functions:
            if fn_decl.is_extern:
                continue
            fn_sig = self.functions[fn_decl.name]
            if fn_decl.body is None:
                raise TypeCheckError("Function declaration missing body", fn_decl.span)
            self._check_function_like(fn_decl.params, fn_decl.body, fn_sig.return_type)

        for class_decl in self.module_ast.classes:
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

    def _collect_declarations(self) -> None:
        declarations_collect_module_declarations(
            self.ctx,
            infer_expression_type=self._infer_expression_type,
            require_assignable=self._require_assignable,
        )

    def _check_field_initializer_expr(self, expr: Expression) -> None:
        declarations_check_constant_field_initializer(expr)

    def _function_sig_from_decl(self, decl: FunctionDecl | MethodDecl) -> FunctionSig:
        return declarations_function_sig_from_decl(
            self.ctx,
            decl,
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
            self.ctx,
            params,
            body,
            return_type,
            resolve_type_ref=self._resolve_type_ref,
            declare_variable=self._declare_variable,
            check_block=self._check_block,
            block_guarantees_return=self._block_guarantees_return,
            push_scope=self._push_scope,
            pop_scope=self._pop_scope,
            canonicalize_reference_type_name=self._canonicalize_reference_type_name,
            receiver_type=receiver_type,
            owner_class_name=owner_class_name,
        )

    def _check_block(self, block: BlockStmt, return_type: TypeInfo) -> None:
        statements_check_block(
            block,
            return_type,
            check_statement=self._check_statement,
            push_scope=self._push_scope,
            pop_scope=self._pop_scope,
        )

    def _check_statement(self, stmt: Statement, return_type: TypeInfo) -> None:
        statements_check_statement(
            self.ctx,
            stmt,
            return_type,
            check_block=self._check_block,
            infer_expression_type=self._infer_expression_type,
            resolve_type_ref=self._resolve_type_ref,
            require_assignable=self._require_assignable,
            require_type_name=self._require_type_name,
            resolve_for_in_element_type=self._resolve_for_in_element_type,
            push_scope=self._push_scope,
            pop_scope=self._pop_scope,
            declare_variable=self._declare_variable,
            ensure_assignable_target=self._ensure_assignable_target,
            ensure_index_assignment=lambda object_type, index_expr, value_type, span: structural_ensure_index_assignment(
                self.ctx,
                object_type,
                index_expr,
                value_type,
                span,
                infer_expression_type=self._infer_expression_type,
                require_member_visible=self._require_member_visible,
            ),
        )

    def _block_guarantees_return(self, block: BlockStmt) -> bool:
        return statements_block_guarantees_return(block)

    def _statement_guarantees_return(self, stmt: Statement) -> bool:
        return statements_statement_guarantees_return(
            stmt,
            block_guarantees_return=self._block_guarantees_return,
        )

    def _ensure_assignable_target(self, expr: Expression) -> None:
        statements_ensure_assignable_target(
            expr,
            lookup_variable=self._lookup_variable,
            infer_expression_type=self._infer_expression_type,
            ensure_field_access_assignable=self._ensure_field_access_assignable,
            ensure_structural_set_method_available_for_index_assignment=self._ensure_structural_set_method_available_for_index_assignment,
        )

    def _infer_expression_type(self, expr: Expression) -> TypeInfo:
        return expressions_infer_expression_type(
            self.ctx,
            expr,
            lookup_variable=self._lookup_variable,
            require_type_name=self._require_type_name,
            require_array_size_type=self._require_array_size_type,
            is_comparable=self._is_comparable,
            check_explicit_cast=self._check_explicit_cast,
            require_member_visible=self._require_member_visible,
        )

    def _resolve_for_in_element_type(self, collection_type: TypeInfo, span: SourceSpan) -> TypeInfo:
        return structural_resolve_for_in_element_type(
            self.ctx,
            collection_type,
            span,
            require_member_visible=self._require_member_visible,
        )

    def _infer_call_type(self, expr: CallExpr) -> TypeInfo:
        return calls_infer_call_type(
            self.ctx,
            expr,
            infer_expression_type=self._infer_expression_type,
            require_member_visible=self._require_member_visible,
            resolve_structural_slice_method_result_type=self._resolve_structural_slice_method_result_type,
            resolve_structural_set_slice_method_result_type=self._resolve_structural_set_slice_method_result_type,
        )

    def _callable_type_from_signature(self, name: str, signature: FunctionSig) -> TypeInfo:
        return calls_callable_type_from_signature(name, signature)

    def _class_type_name_from_callable(self, callable_name: str) -> str:
        return calls_class_type_name_from_callable(callable_name)

    def _resolve_structural_get_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        index_type: TypeInfo,
        index_span: SourceSpan,
        span: SourceSpan,
    ) -> TypeInfo:
        return structural_resolve_structural_get_method_result_type(
            self.ctx,
            object_type,
            class_info,
            index_type,
            index_span,
            span,
            require_member_visible=self._require_member_visible,
        )

    def _ensure_structural_set_method_available_for_index_assignment(
        self,
        object_type: TypeInfo,
        span: SourceSpan,
    ) -> FunctionSig:
        return structural_ensure_structural_set_method_available_for_index_assignment(
            self.ctx,
            object_type,
            span,
            require_member_visible=self._require_member_visible,
        )

    def _ensure_structural_set_method_for_index_assignment(
        self,
        object_type: TypeInfo,
        index_expr: Expression,
        value_type: TypeInfo,
        span: SourceSpan,
    ) -> None:
        structural_ensure_structural_set_method_for_index_assignment(
            self.ctx,
            object_type,
            index_expr,
            value_type,
            span,
            infer_expression_type=self._infer_expression_type,
            require_member_visible=self._require_member_visible,
        )

    def _resolve_structural_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        return structural_resolve_structural_slice_method_result_type(
            self.ctx,
            object_type,
            class_info,
            args,
            span,
            infer_expression_type=self._infer_expression_type,
            require_member_visible=self._require_member_visible,
        )

    def _resolve_structural_set_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        return structural_resolve_structural_set_slice_method_result_type(
            self.ctx,
            object_type,
            class_info,
            args,
            span,
            infer_expression_type=self._infer_expression_type,
            require_member_visible=self._require_member_visible,
        )

    def _resolve_imported_function_sig(self, fn_name: str, span: SourceSpan) -> FunctionSig | None:
        return lookup_resolve_imported_function_sig(
            self.ctx,
            fn_name,
            span,
        )

    def _check_call_arguments(self, params: list[TypeInfo], args: list[Expression], span: SourceSpan) -> None:
        calls_check_call_arguments(
            self.ctx,
            params,
            args,
            span,
            infer_expression_type=self._infer_expression_type,
        )

    def _infer_constructor_call_type(
        self,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
        result_type: TypeInfo,
    ) -> TypeInfo:
        return calls_infer_constructor_call_type(
            self.ctx,
            class_info,
            args,
            span,
            result_type,
            infer_expression_type=self._infer_expression_type,
        )

    def _ensure_field_access_assignable(self, expr: FieldAccessExpr) -> None:
        statements_ensure_field_access_assignable(
            expr,
            infer_expression_type=self._infer_expression_type,
            lookup_class_by_type_name=self._lookup_class_by_type_name,
            require_member_visible=self._require_member_visible,
        )

    def _resolve_type_ref(self, type_ref: TypeRefNode) -> TypeInfo:
        return resolution_resolve_type_ref(
            self.ctx,
            type_ref,
        )

    def _resolve_string_type(self, span: SourceSpan) -> TypeInfo:
        return resolution_resolve_string_type(
            self.ctx,
            span,
        )

    def _resolve_unique_global_class_type(self, class_name: str, span: SourceSpan) -> TypeInfo | None:
        resolved_name = lookup_resolve_unique_global_class_name(
            self.ctx,
            class_name,
            span,
        )
        if resolved_name is None:
            return None
        return TypeInfo(name=resolved_name, kind="reference")

    def _resolve_imported_class_type(self, class_name: str, span: SourceSpan) -> TypeInfo | None:
        resolved_name = lookup_resolve_imported_class_name(
            self.ctx,
            class_name,
            span,
        )
        if resolved_name is None:
            return None
        return TypeInfo(name=resolved_name, kind="reference")

    def _qualify_member_type_for_owner(self, member_type: TypeInfo, owner_type_name: str) -> TypeInfo:
        return resolution_qualify_member_type_for_owner(
            self.ctx,
            member_type,
            owner_type_name,
        )

    def _resolve_unique_imported_class_module(
        self,
        class_name: str,
        span: SourceSpan,
        *,
        ambiguity_label: str,
    ) -> ModulePath | None:
        return lookup_resolve_unique_imported_class_module(
            self.ctx,
            class_name,
            span,
            ambiguity_label=ambiguity_label,
        )

    def _resolve_qualified_imported_class_type(self, qualified_name: str, span: SourceSpan) -> TypeInfo | None:
        resolved_name = lookup_resolve_qualified_imported_class_name(
            self.ctx,
            qualified_name,
            span,
        )
        if resolved_name is None:
            return None
        return TypeInfo(name=resolved_name, kind="reference")

    def _declare_variable(self, name: str, var_type: TypeInfo, span: SourceSpan) -> None:
        context_declare_variable(self.ctx, name, var_type, span)

    def _lookup_variable(self, name: str) -> TypeInfo | None:
        return context_lookup_variable(self.ctx, name)

    def _push_scope(self) -> None:
        context_push_scope(self.ctx)

    def _pop_scope(self) -> None:
        context_pop_scope(self.ctx)

    def _require_type_name(self, actual: TypeInfo, expected_name: str, span: SourceSpan) -> None:
        relation_require_type_name(actual, expected_name, span)

    def _require_array_size_type(self, actual: TypeInfo, span: SourceSpan) -> None:
        relation_require_array_size_type(actual, span)

    def _require_array_index_type(self, actual: TypeInfo, span: SourceSpan) -> None:
        relation_require_array_index_type(actual, span)

    def _canonicalize_reference_type_name(self, type_name: str) -> str:
        return relation_canonicalize_reference_type_name(
            self.ctx,
            type_name,
        )

    def _type_names_equal(self, left: str, right: str) -> bool:
        return relation_type_names_equal(
            self.ctx,
            left,
            right,
        )

    def _type_infos_equal(self, left: TypeInfo, right: TypeInfo) -> bool:
        return relation_type_infos_equal(
            self.ctx,
            left,
            right,
        )

    def _require_assignable(self, target: TypeInfo, value: TypeInfo, span: SourceSpan) -> None:
        relation_require_assignable(
            self.ctx,
            target,
            value,
            span,
        )

    def _is_comparable(self, left: TypeInfo, right: TypeInfo) -> bool:
        return relation_is_comparable(
            self.ctx,
            left,
            right,
        )

    def _check_explicit_cast(self, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
        relation_check_explicit_cast(
            self.ctx,
            source,
            target,
            span,
        )

    def _format_function_type_name(self, params: list[TypeInfo], return_type: TypeInfo) -> str:
        return relation_format_function_type_name(params, return_type)

    def _display_type_name(self, type_info: TypeInfo) -> str:
        return relation_display_type_name(type_info)

    def _current_module_info(self) -> ModuleInfo | None:
        return lookup_current_module_info(self.ctx)

    def _lookup_class_by_type_name(self, type_name: str) -> ClassInfo | None:
        return lookup_lookup_class_by_type_name(
            self.ctx,
            type_name,
        )

    def _resolve_module_member(self, expr: FieldAccessExpr) -> tuple[str, ModulePath, str] | None:
        return lookup_resolve_module_member(
            self.ctx,
            expr,
        )

    def _flatten_field_chain(self, expr: Expression) -> list[str] | None:
        return lookup_flatten_field_chain(expr)

    def _require_member_visible(
        self,
        class_info: ClassInfo,
        owner_type_name: str,
        member_name: str,
        member_kind: str,
        span: SourceSpan,
    ) -> None:
        statements_require_member_visible(
            self.ctx,
            class_info,
            owner_type_name,
            member_name,
            member_kind,
            span,
            canonicalize_reference_type_name=self._canonicalize_reference_type_name,
        )
