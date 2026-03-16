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
        previous_owner = self.ctx.current_private_owner_type
        if owner_class_name is not None:
            self.ctx.current_private_owner_type = self._canonicalize_reference_type_name(owner_class_name)

        self._push_scope()
        self.ctx.function_local_names_stack.append(set())
        try:
            if receiver_type is not None:
                self._declare_variable("__self", receiver_type, body.span)
            for param in params:
                param_type = self._resolve_type_ref(param.type_ref)
                self._declare_variable(param.name, param_type, param.span)

            self._check_block(body, return_type)

            if return_type.name != "unit" and not self._block_guarantees_return(body):
                raise TypeCheckError("Non-unit function must return on all paths", body.span)
        finally:
            self.ctx.function_local_names_stack.pop()
            self._pop_scope()
            self.ctx.current_private_owner_type = previous_owner

    def _check_block(self, block: BlockStmt, return_type: TypeInfo) -> None:
        self._push_scope()
        for stmt in block.statements:
            self._check_statement(stmt, return_type)
        self._pop_scope()

    def _check_statement(self, stmt: Statement, return_type: TypeInfo) -> None:
        if isinstance(stmt, BlockStmt):
            self._check_block(stmt, return_type)
            return

        if isinstance(stmt, VarDeclStmt):
            var_type = self._resolve_type_ref(stmt.type_ref)
            if stmt.initializer is not None:
                init_type = self._infer_expression_type(stmt.initializer)
                self._require_assignable(var_type, init_type, stmt.initializer.span)
            self._declare_variable(stmt.name, var_type, stmt.span)
            return

        if isinstance(stmt, IfStmt):
            cond_type = self._infer_expression_type(stmt.condition)
            self._require_type_name(cond_type, "bool", stmt.condition.span)
            self._check_block(stmt.then_branch, return_type)
            if isinstance(stmt.else_branch, BlockStmt):
                self._check_block(stmt.else_branch, return_type)
            elif isinstance(stmt.else_branch, IfStmt):
                self._check_statement(stmt.else_branch, return_type)
            return

        if isinstance(stmt, WhileStmt):
            cond_type = self._infer_expression_type(stmt.condition)
            self._require_type_name(cond_type, "bool", stmt.condition.span)
            self.ctx.loop_depth += 1
            self._check_block(stmt.body, return_type)
            self.ctx.loop_depth -= 1
            return

        if isinstance(stmt, ForInStmt):
            collection_type = self._infer_expression_type(stmt.collection_expr)
            element_type = self._resolve_for_in_element_type(collection_type, stmt.span)
            object.__setattr__(stmt, "collection_type_name", collection_type.name)
            object.__setattr__(stmt, "element_type_name", element_type.name)

            self.ctx.loop_depth += 1
            self._push_scope()
            try:
                self._declare_variable(stmt.element_name, element_type, stmt.span)
                self._check_block(stmt.body, return_type)
            finally:
                self._pop_scope()
                self.ctx.loop_depth -= 1
            return

        if isinstance(stmt, BreakStmt):
            if self.ctx.loop_depth <= 0:
                raise TypeCheckError("'break' is only allowed inside while loops", stmt.span)
            return

        if isinstance(stmt, ContinueStmt):
            if self.ctx.loop_depth <= 0:
                raise TypeCheckError("'continue' is only allowed inside while loops", stmt.span)
            return

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                if return_type.name != "unit":
                    raise TypeCheckError("Non-unit function must return a value", stmt.span)
            else:
                value_type = self._infer_expression_type(stmt.value)
                self._require_assignable(return_type, value_type, stmt.value.span)
            return

        if isinstance(stmt, AssignStmt):
            self._ensure_assignable_target(stmt.target)
            if isinstance(stmt.target, IndexExpr):
                object_type = self._infer_expression_type(stmt.target.object_expr)
                value_type = self._infer_expression_type(stmt.value)
                structural_ensure_index_assignment(
                    self.ctx,
                    object_type,
                    stmt.target.index_expr,
                    value_type,
                    stmt.value.span,
                    infer_expression_type=self._infer_expression_type,
                    require_member_visible=self._require_member_visible,
                )
                return

            target_type = self._infer_expression_type(stmt.target)
            value_type = self._infer_expression_type(stmt.value)
            self._require_assignable(target_type, value_type, stmt.value.span)
            return

        if isinstance(stmt, ExprStmt):
            self._infer_expression_type(stmt.expression)

    def _block_guarantees_return(self, block: BlockStmt) -> bool:
        for stmt in block.statements:
            if self._statement_guarantees_return(stmt):
                return True
        return False

    def _statement_guarantees_return(self, stmt: Statement) -> bool:
        if isinstance(stmt, ReturnStmt):
            return True

        if isinstance(stmt, BlockStmt):
            return self._block_guarantees_return(stmt)

        if isinstance(stmt, IfStmt):
            if stmt.else_branch is None:
                return False
            then_returns = self._block_guarantees_return(stmt.then_branch)
            else_returns = self._statement_guarantees_return(stmt.else_branch)
            return then_returns and else_returns

        return False

    def _ensure_assignable_target(self, expr: Expression) -> None:
        if isinstance(expr, IdentifierExpr):
            if self._lookup_variable(expr.name) is None:
                raise TypeCheckError("Invalid assignment target", expr.span)
            return

        if isinstance(expr, FieldAccessExpr):
            self._ensure_field_access_assignable(expr)
            return

        if isinstance(expr, IndexExpr):
            object_type = self._infer_expression_type(expr.object_expr)
            if object_type.element_type is None:
                self._ensure_structural_set_method_available_for_index_assignment(object_type, expr.span)
            return

        raise TypeCheckError("Invalid assignment target", expr.span)

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
        expressions_ensure_field_access_assignable(
            self.ctx,
            expr,
            infer_expression_type=self._infer_expression_type,
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
        is_private = (
            member_name in class_info.private_fields
            if member_kind == "field"
            else member_name in class_info.private_methods
        )
        if not is_private:
            return

        owner_canonical = self._canonicalize_reference_type_name(owner_type_name)
        if self.ctx.current_private_owner_type == owner_canonical:
            return

        raise TypeCheckError(f"Member '{class_info.name}.{member_name}' is private", span)
