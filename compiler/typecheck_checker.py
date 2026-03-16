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
                if object_type.element_type is None:
                    self._ensure_structural_set_method_for_index_assignment(
                        object_type,
                        stmt.target.index_expr,
                        value_type,
                        stmt.target.span,
                    )
                else:
                    target_type = self._infer_expression_type(stmt.target)
                    self._require_assignable(target_type, value_type, stmt.value.span)
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
        if isinstance(expr, IdentifierExpr):
            symbol_type = self._lookup_variable(expr.name)
            if symbol_type is not None:
                return symbol_type

            fn_sig = self.functions.get(expr.name)
            if fn_sig is not None:
                return self._callable_type_from_signature(f"__fn__:{expr.name}", fn_sig)

            imported_fn_sig = self._resolve_imported_function_sig(expr.name, expr.span)
            if imported_fn_sig is not None:
                return self._callable_type_from_signature(f"__fn__:{expr.name}", imported_fn_sig)

            if expr.name in self.classes:
                return TypeInfo(name=f"__class__:{expr.name}", kind="callable")

            imported_class_type = self._resolve_imported_class_type(expr.name, expr.span)
            if imported_class_type is not None:
                if "::" in imported_class_type.name:
                    owner_dotted, class_name = imported_class_type.name.split("::", 1)
                    return TypeInfo(name=f"__class__:{owner_dotted}:{class_name}", kind="callable")
                return TypeInfo(name=f"__class__:{imported_class_type.name}", kind="callable")

            if self._current_module_info() is not None and expr.name in self._current_module_info().imports:
                return TypeInfo(name=f"__module__:{expr.name}", kind="module")

            raise TypeCheckError(f"Unknown identifier '{expr.name}'", expr.span)

        if isinstance(expr, LiteralExpr):
            if expr.value.startswith('"'):
                return self._resolve_string_type(expr.span)
            if expr.value.startswith("'"):
                return TypeInfo(name="u8", kind="primitive")
            if expr.value in {"true", "false"}:
                return TypeInfo(name="bool", kind="primitive")
            if "." in expr.value:
                return TypeInfo(name="double", kind="primitive")
            if expr.value.endswith("u8") and expr.value[:-2].isdigit():
                value = int(expr.value[:-2])
                if value < 0 or value > 255:
                    raise TypeCheckError("u8 literal out of range (expected 0..255)", expr.span)
                return TypeInfo(name="u8", kind="primitive")
            if expr.value.endswith("u") and expr.value[:-1].isdigit():
                value = int(expr.value[:-1])
                if value > U64_MAX_LITERAL:
                    raise TypeCheckError("u64 literal out of range (expected 0..18446744073709551615)", expr.span)
                return TypeInfo(name="u64", kind="primitive")
            if expr.value.isdigit():
                value = int(expr.value)
                if value > I64_MAX_LITERAL:
                    raise TypeCheckError(
                        "i64 literal out of range (expected -9223372036854775808..9223372036854775807)",
                        expr.span,
                    )
            return TypeInfo(name="i64", kind="primitive")

        if isinstance(expr, NullExpr):
            return TypeInfo(name="null", kind="null")

        if isinstance(expr, UnaryExpr):
            if expr.operator == "!":
                operand_type = self._infer_expression_type(expr.operand)
                self._require_type_name(operand_type, "bool", expr.operand.span)
                return TypeInfo(name="bool", kind="primitive")

            if expr.operator == "-":
                if isinstance(expr.operand, LiteralExpr) and expr.operand.value.isdigit():
                    value = int(expr.operand.value)
                    if value == I64_MIN_MAGNITUDE_LITERAL:
                        return TypeInfo(name="i64", kind="primitive")

                operand_type = self._infer_expression_type(expr.operand)
                if operand_type.name not in {"i64", "double"}:
                    raise TypeCheckError("Unary '-' requires signed numeric operand", expr.span)
                return operand_type

            if expr.operator == "~":
                operand_type = self._infer_expression_type(expr.operand)
                if operand_type.name not in BITWISE_TYPE_NAMES:
                    raise TypeCheckError("Unary '~' requires integer operand", expr.span)
                return operand_type

            raise TypeCheckError(f"Unknown unary operator '{expr.operator}'", expr.span)

        if isinstance(expr, BinaryExpr):
            left_type = self._infer_expression_type(expr.left)
            right_type = self._infer_expression_type(expr.right)
            op = expr.operator

            if op in {"+", "-", "*", "/", "%"}:
                if op == "+" and is_str_type_name(left_type.name) and is_str_type_name(right_type.name):
                    return self._resolve_string_type(expr.span)

                if left_type.name not in NUMERIC_TYPE_NAMES or right_type.name not in NUMERIC_TYPE_NAMES:
                    if op == "+":
                        raise TypeCheckError("Operator '+' requires numeric operands or Str operands", expr.span)
                    raise TypeCheckError(f"Operator '{op}' requires numeric operands", expr.span)
                if left_type.name != right_type.name:
                    raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
                if op == "%" and left_type.name == "double":
                    raise TypeCheckError("Operator '%' is not supported for 'double'", expr.span)
                return left_type

            if op == "**":
                if left_type.name not in BITWISE_TYPE_NAMES:
                    raise TypeCheckError("Operator '**' requires integer left operand", expr.span)
                if right_type.name != "u64":
                    raise TypeCheckError("Operator '**' requires 'u64' exponent", expr.span)
                return left_type

            if op in {"<<", ">>"}:
                if left_type.name not in BITWISE_TYPE_NAMES:
                    raise TypeCheckError(f"Operator '{op}' requires integer left operand", expr.span)
                if right_type.name != "u64":
                    raise TypeCheckError(f"Operator '{op}' requires 'u64' shift count", expr.span)
                return left_type

            if op in {"&", "|", "^"}:
                if left_type.name not in BITWISE_TYPE_NAMES or right_type.name not in BITWISE_TYPE_NAMES:
                    raise TypeCheckError(f"Operator '{op}' requires integer operands", expr.span)
                if left_type.name != right_type.name:
                    raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
                return left_type

            if op in {"<", "<=", ">", ">="}:
                if left_type.name not in NUMERIC_TYPE_NAMES or right_type.name not in NUMERIC_TYPE_NAMES:
                    raise TypeCheckError(f"Operator '{op}' requires numeric operands", expr.span)
                if left_type.name != right_type.name:
                    raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
                return TypeInfo(name="bool", kind="primitive")

            if op in {"==", "!="}:
                if not self._is_comparable(left_type, right_type):
                    raise TypeCheckError(f"Operator '{op}' has incompatible operand types", expr.span)
                return TypeInfo(name="bool", kind="primitive")

            if op in {"&&", "||"}:
                self._require_type_name(left_type, "bool", expr.left.span)
                self._require_type_name(right_type, "bool", expr.right.span)
                return TypeInfo(name="bool", kind="primitive")

            raise TypeCheckError(f"Unknown binary operator '{op}'", expr.span)

        if isinstance(expr, CastExpr):
            source_type = self._infer_expression_type(expr.operand)
            target_type = self._resolve_type_ref(expr.type_ref)
            self._check_explicit_cast(source_type, target_type, expr.span)
            return target_type

        if isinstance(expr, CallExpr):
            return self._infer_call_type(expr)

        if isinstance(expr, ArrayCtorExpr):
            array_type = self._resolve_type_ref(expr.element_type_ref)
            if array_type.element_type is None:
                raise TypeCheckError("Array constructor requires array element type", expr.element_type_ref.span)
            length_type = self._infer_expression_type(expr.length_expr)
            self._require_array_size_type(length_type, expr.length_expr.span)
            return array_type

        if isinstance(expr, FieldAccessExpr):
            module_member = self._resolve_module_member(expr)
            if module_member is not None:
                kind, owner_module, member_name = module_member
                if kind == "function":
                    dotted = ".".join(owner_module)
                    fn_sig = self.module_function_sigs[owner_module][member_name]
                    return self._callable_type_from_signature(f"__fn__:{dotted}:{member_name}", fn_sig)
                if kind == "class":
                    dotted = ".".join(owner_module)
                    return TypeInfo(name=f"__class__:{dotted}:{member_name}", kind="callable")
                dotted = ".".join(owner_module)
                return TypeInfo(name=f"__module__:{dotted}", kind="module")

            object_type = self._infer_expression_type(expr.object_expr)

            if object_type.kind == "callable" and object_type.name.startswith("__class__:"):
                class_type_name = self._class_type_name_from_callable(object_type.name)
                class_info = self._lookup_class_by_type_name(class_type_name)
                if class_info is None:
                    raise TypeCheckError(f"Type '{class_type_name}' has no callable members", expr.span)

                method_sig = class_info.methods.get(expr.field_name)
                if method_sig is None:
                    raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.field_name}'", expr.span)
                self._require_member_visible(class_info, class_type_name, expr.field_name, "method", expr.span)
                if not method_sig.is_static:
                    raise TypeCheckError(
                        f"Method '{class_info.name}.{expr.field_name}' is not static",
                        expr.span,
                    )

                qualified_params = [
                    self._qualify_member_type_for_owner(param_type, class_type_name)
                    for param_type in method_sig.params
                ]
                qualified_return = self._qualify_member_type_for_owner(method_sig.return_type, class_type_name)
                return TypeInfo(
                    name=f"__method__:{class_info.name}:{method_sig.name}",
                    kind="callable",
                    callable_params=qualified_params,
                    callable_return=qualified_return,
                )

            if object_type.element_type is not None:
                if expr.field_name not in ARRAY_METHOD_NAMES:
                    raise TypeCheckError(f"Array type '{object_type.name}' has no member '{
                                         expr.field_name}'", expr.span)
                return TypeInfo(name=f"__array_method__:{expr.field_name}", kind="callable")

            class_info = self._lookup_class_by_type_name(object_type.name)
            if class_info is None:
                raise TypeCheckError(f"Type '{object_type.name}' has no fields/methods", expr.span)

            field_type = class_info.fields.get(expr.field_name)
            if field_type is not None:
                self._require_member_visible(class_info, object_type.name, expr.field_name, "field", expr.span)
                return self._qualify_member_type_for_owner(field_type, object_type.name)

            method_sig = class_info.methods.get(expr.field_name)
            if method_sig is not None:
                self._require_member_visible(class_info, object_type.name, expr.field_name, "method", expr.span)
                if not method_sig.is_static:
                    raise TypeCheckError("Instance methods are not first-class values in MVP", expr.span)
                qualified_params = [
                    self._qualify_member_type_for_owner(param_type, object_type.name)
                    for param_type in method_sig.params
                ]
                qualified_return = self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)
                return TypeInfo(
                    name=f"__method__:{class_info.name}:{method_sig.name}",
                    kind="callable",
                    callable_params=qualified_params,
                    callable_return=qualified_return,
                )

            raise TypeCheckError(f"Class '{class_info.name}' has no member '{expr.field_name}'", expr.span)

        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expression_type(expr.object_expr)
            index_type = self._infer_expression_type(expr.index_expr)
            if obj_type.element_type is not None:
                self._require_array_index_type(index_type, expr.index_expr.span)
                return obj_type.element_type

            class_info = self._lookup_class_by_type_name(obj_type.name)
            if class_info is not None:
                return self._resolve_structural_get_method_result_type(
                    obj_type,
                    class_info,
                    index_type,
                    expr.index_expr.span,
                    expr.span,
                )
            raise TypeCheckError(f"Type '{obj_type.name}' is not indexable", expr.span)

        raise TypeCheckError("Unsupported expression", expr.span)

    def _resolve_for_in_element_type(self, collection_type: TypeInfo, span: SourceSpan) -> TypeInfo:
        if collection_type.element_type is not None:
            return collection_type.element_type

        class_info = self._lookup_class_by_type_name(collection_type.name)
        if class_info is None:
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (missing methods 'iter_len()' and 'iter_get(i64)')",
                span,
            )

        iter_len_sig = class_info.methods.get("iter_len")
        if iter_len_sig is None:
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (missing method 'iter_len()')",
                span,
            )
        self._require_member_visible(class_info, collection_type.name, "iter_len", "method", span)
        if iter_len_sig.is_static or len(iter_len_sig.params) != 0:
            raise TypeCheckError(
                f"Type '{
                    collection_type.name}' is not iterable (method 'iter_len' must be instance method with 0 args)",
                span,
            )
        iter_len_return = self._qualify_member_type_for_owner(iter_len_sig.return_type, collection_type.name)
        if iter_len_return.name != "u64":
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (method 'iter_len' must return u64)",
                span,
            )

        iter_get_sig = class_info.methods.get("iter_get")
        if iter_get_sig is None:
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (missing method 'iter_get(i64)')",
                span,
            )
        self._require_member_visible(class_info, collection_type.name, "iter_get", "method", span)
        if iter_get_sig.is_static or len(iter_get_sig.params) != 1:
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (method 'iter_get' must be instance method with 1 arg)",
                span,
            )

        iter_get_param = self._qualify_member_type_for_owner(iter_get_sig.params[0], collection_type.name)
        if iter_get_param.name != "i64":
            raise TypeCheckError(
                f"Type '{collection_type.name}' is not iterable (method 'iter_get' parameter must be i64)",
                span,
            )

        return self._qualify_member_type_for_owner(iter_get_sig.return_type, collection_type.name)

    def _infer_call_type(self, expr: CallExpr) -> TypeInfo:
        if isinstance(expr.callee, IdentifierExpr):
            name = expr.callee.name

            fn_sig = self.functions.get(name)
            if fn_sig is not None:
                self._check_call_arguments(fn_sig.params, expr.arguments, expr.span)
                return fn_sig.return_type

            imported_fn_sig = self._resolve_imported_function_sig(name, expr.callee.span)
            if imported_fn_sig is not None:
                self._check_call_arguments(imported_fn_sig.params, expr.arguments, expr.span)
                return imported_fn_sig.return_type

            class_info = self.classes.get(name)
            if class_info is not None:
                return self._infer_constructor_call_type(
                    class_info,
                    expr.arguments,
                    expr.span,
                    TypeInfo(name=class_info.name, kind="reference"),
                )

            imported_class_type = self._resolve_imported_class_type(name, expr.callee.span)
            if imported_class_type is not None:
                imported_class_info = self._lookup_class_by_type_name(imported_class_type.name)
                if imported_class_info is None:
                    raise TypeCheckError(f"Unknown type '{imported_class_type.name}'", expr.callee.span)
                return self._infer_constructor_call_type(
                    imported_class_info,
                    expr.arguments,
                    expr.span,
                    imported_class_type,
                )

        if isinstance(expr.callee, FieldAccessExpr):
            module_member = self._resolve_module_member(expr.callee)
            if module_member is not None:
                kind, owner_module, member_name = module_member
                if kind == "function":
                    fn_sig = self.module_function_sigs[owner_module][member_name]
                    self._check_call_arguments(fn_sig.params, expr.arguments, expr.span)
                    return fn_sig.return_type

                if kind == "class":
                    class_info = self.module_class_infos[owner_module][member_name]
                    owner_dotted = ".".join(owner_module)
                    return self._infer_constructor_call_type(
                        class_info,
                        expr.arguments,
                        expr.span,
                        TypeInfo(name=f"{owner_dotted}::{class_info.name}", kind="reference"),
                    )

                raise TypeCheckError("Module values are not callable", expr.callee.span)

            object_type = self._infer_expression_type(expr.callee.object_expr)

            if object_type.kind == "callable" and object_type.name.startswith("__class__:"):
                class_type_name = self._class_type_name_from_callable(object_type.name)
                class_info = self._lookup_class_by_type_name(class_type_name)
                if class_info is None:
                    raise TypeCheckError(f"Type '{class_type_name}' has no callable members", expr.span)

                method_sig = class_info.methods.get(expr.callee.field_name)
                if method_sig is None:
                    raise TypeCheckError(f"Class '{class_info.name}' has no method '{
                                         expr.callee.field_name}'", expr.span)
                self._require_member_visible(class_info, class_type_name, expr.callee.field_name, "method", expr.span)
                if not method_sig.is_static:
                    raise TypeCheckError(
                        f"Method '{class_info.name}.{expr.callee.field_name}' is not static",
                        expr.span,
                    )

                qualified_params = [
                    self._qualify_member_type_for_owner(param_type, class_type_name)
                    for param_type in method_sig.params
                ]
                qualified_return_type = self._qualify_member_type_for_owner(method_sig.return_type, class_type_name)

                self._check_call_arguments(qualified_params, expr.arguments, expr.span)
                return qualified_return_type

            if object_type.element_type is not None:
                method_name = expr.callee.field_name
                if method_name == "len":
                    self._check_call_arguments([], expr.arguments, expr.span)
                    return TypeInfo(name="u64", kind="primitive")
                if method_name == "iter_len":
                    self._check_call_arguments([], expr.arguments, expr.span)
                    return TypeInfo(name="u64", kind="primitive")
                if method_name == "index_get":
                    if len(expr.arguments) != 1:
                        raise TypeCheckError(f"Expected 1 arguments, got {len(expr.arguments)}", expr.span)
                    index_type = self._infer_expression_type(expr.arguments[0])
                    self._require_array_index_type(index_type, expr.arguments[0].span)
                    return object_type.element_type
                if method_name == "iter_get":
                    if len(expr.arguments) != 1:
                        raise TypeCheckError(f"Expected 1 arguments, got {len(expr.arguments)}", expr.span)
                    index_type = self._infer_expression_type(expr.arguments[0])
                    self._require_array_index_type(index_type, expr.arguments[0].span)
                    return object_type.element_type
                if method_name == "index_set":
                    if len(expr.arguments) != 2:
                        raise TypeCheckError(f"Expected 2 arguments, got {len(expr.arguments)}", expr.span)
                    index_type = self._infer_expression_type(expr.arguments[0])
                    self._require_array_index_type(index_type, expr.arguments[0].span)
                    value_type = self._infer_expression_type(expr.arguments[1])
                    self._require_assignable(object_type.element_type, value_type, expr.arguments[1].span)
                    return TypeInfo(name="unit", kind="primitive")
                if method_name == "slice_get":
                    if len(expr.arguments) != 2:
                        raise TypeCheckError(f"Expected 2 arguments, got {len(expr.arguments)}", expr.span)
                    start_type = self._infer_expression_type(expr.arguments[0])
                    end_type = self._infer_expression_type(expr.arguments[1])
                    self._require_array_index_type(start_type, expr.arguments[0].span)
                    self._require_array_index_type(end_type, expr.arguments[1].span)
                    return object_type
                if method_name == "slice_set":
                    if len(expr.arguments) != 3:
                        raise TypeCheckError(f"Expected 3 arguments, got {len(expr.arguments)}", expr.span)
                    start_type = self._infer_expression_type(expr.arguments[0])
                    end_type = self._infer_expression_type(expr.arguments[1])
                    self._require_array_index_type(start_type, expr.arguments[0].span)
                    self._require_array_index_type(end_type, expr.arguments[1].span)
                    value_type = self._infer_expression_type(expr.arguments[2])
                    self._require_assignable(object_type, value_type, expr.arguments[2].span)
                    return TypeInfo(name="unit", kind="primitive")
                raise TypeCheckError(f"Array type '{object_type.name}' has no method '{method_name}'", expr.span)

            class_info = self._lookup_class_by_type_name(object_type.name)
            if class_info is None:
                raise TypeCheckError(f"Type '{object_type.name}' has no callable members", expr.span)

            method_sig = class_info.methods.get(expr.callee.field_name)
            if method_sig is None:
                field_type = class_info.fields.get(expr.callee.field_name)
                if field_type is not None:
                    self._require_member_visible(class_info, object_type.name,
                                                 expr.callee.field_name, "field", expr.span)
                    qualified_field_type = self._qualify_member_type_for_owner(field_type, object_type.name)
                    if (
                        qualified_field_type.kind == "callable"
                        and qualified_field_type.callable_params is not None
                        and qualified_field_type.callable_return is not None
                    ):
                        self._check_call_arguments(qualified_field_type.callable_params, expr.arguments, expr.span)
                        return qualified_field_type.callable_return
                    raise TypeCheckError(
                        f"Expression of type '{qualified_field_type.name}' is not callable",
                        expr.callee.span,
                    )
                raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
            self._require_member_visible(class_info, object_type.name, expr.callee.field_name, "method", expr.span)

            if expr.callee.field_name == "slice_get":
                return self._resolve_structural_slice_method_result_type(
                    object_type,
                    class_info,
                    expr.arguments,
                    expr.span,
                )

            if expr.callee.field_name == "slice_set":
                return self._resolve_structural_set_slice_method_result_type(
                    object_type,
                    class_info,
                    expr.arguments,
                    expr.span,
                )

            if method_sig.is_static:
                raise TypeCheckError(
                    f"Static method '{class_info.name}.{expr.callee.field_name}' must be called on the class",
                    expr.span,
                )

            qualified_params = [
                self._qualify_member_type_for_owner(param_type, object_type.name)
                for param_type in method_sig.params
            ]
            qualified_return_type = self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)

            self._check_call_arguments(qualified_params, expr.arguments, expr.span)
            return qualified_return_type

        callee_type = self._infer_expression_type(expr.callee)
        if callee_type.kind == "callable" and callee_type.callable_params is not None and callee_type.callable_return is not None:
            self._check_call_arguments(callee_type.callable_params, expr.arguments, expr.span)
            return callee_type.callable_return
        raise TypeCheckError(f"Expression of type '{callee_type.name}' is not callable", expr.callee.span)

    def _callable_type_from_signature(self, name: str, signature: FunctionSig) -> TypeInfo:
        return TypeInfo(
            name=name,
            kind="callable",
            callable_params=signature.params,
            callable_return=signature.return_type,
        )

    def _class_type_name_from_callable(self, callable_name: str) -> str:
        if not callable_name.startswith("__class__:"):
            raise ValueError(f"invalid class callable name: {callable_name}")
        payload = callable_name[len("__class__:"):]
        if ":" not in payload:
            return payload
        owner_dotted, class_name = payload.rsplit(":", 1)
        return f"{owner_dotted}::{class_name}"

    def _resolve_structural_get_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        index_type: TypeInfo,
        index_span: SourceSpan,
        span: SourceSpan,
    ) -> TypeInfo:
        method_sig = class_info.methods.get("index_get")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (missing method 'index_get(K)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "index_get", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (method 'index_get' must be instance method)",
                span,
            )
        if len(method_sig.params) != 1:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (method 'index_get' must take exactly 1 argument)",
                span,
            )

        qualified_index_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        self._require_assignable(qualified_index_param, index_type, index_span)

        return self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)

    def _ensure_structural_set_method_available_for_index_assignment(
        self,
        object_type: TypeInfo,
        span: SourceSpan,
    ) -> FunctionSig:
        class_info = self._lookup_class_by_type_name(object_type.name)
        if class_info is None:
            raise TypeCheckError(f"Type '{object_type.name}' is not index-assignable", span)

        method_sig = class_info.methods.get("index_set")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (missing method 'index_set(K, V)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "index_set", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'index_set' must be instance method)",
                span,
            )
        if len(method_sig.params) != 2:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'index_set' must take exactly 2 arguments)",
                span,
            )

        qualified_return_type = self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)
        if qualified_return_type.name != "unit":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'index_set' must return unit)",
                span,
            )

        return method_sig

    def _ensure_structural_set_method_for_index_assignment(
        self,
        object_type: TypeInfo,
        index_expr: Expression,
        value_type: TypeInfo,
        span: SourceSpan,
    ) -> None:
        class_info = self._lookup_class_by_type_name(object_type.name)
        if class_info is None:
            raise TypeCheckError(f"Type '{object_type.name}' is not index-assignable", span)

        method_sig = self._ensure_structural_set_method_available_for_index_assignment(object_type, span)
        index_type = self._infer_expression_type(index_expr)
        qualified_index_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        self._require_assignable(qualified_index_param, index_type, index_expr.span)
        qualified_value_param = self._qualify_member_type_for_owner(method_sig.params[1], object_type.name)
        self._require_assignable(qualified_value_param, value_type, span)

    def _resolve_structural_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        method_sig = class_info.methods.get("slice_get")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (missing method 'slice_get(i64, i64)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "slice_get", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice_get' must be instance method)",
                span,
            )
        if len(method_sig.params) != 2:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice_get' must take exactly 2 arguments)",
                span,
            )
        if len(args) != 2:
            raise TypeCheckError(f"Expected 2 arguments, got {len(args)}", span)

        qualified_begin_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        qualified_end_param = self._qualify_member_type_for_owner(method_sig.params[1], object_type.name)
        if qualified_begin_param.name != "i64" or qualified_end_param.name != "i64":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice_get' parameters must be i64)",
                span,
            )

        begin_arg_type = self._infer_expression_type(args[0])
        end_arg_type = self._infer_expression_type(args[1])
        self._require_array_index_type(begin_arg_type, args[0].span)
        self._require_array_index_type(end_arg_type, args[1].span)
        return self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)

    def _resolve_structural_set_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        method_sig = class_info.methods.get("slice_set")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not slice-assignable (missing method 'slice_set(i64, i64, U)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "slice_set", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must be instance method)",
                span,
            )
        if len(method_sig.params) != 3:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must take exactly 3 arguments)",
                span,
            )
        if len(args) != 3:
            raise TypeCheckError(f"Expected 3 arguments, got {len(args)}", span)

        qualified_begin_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        qualified_end_param = self._qualify_member_type_for_owner(method_sig.params[1], object_type.name)
        if qualified_begin_param.name != "i64" or qualified_end_param.name != "i64":
            raise TypeCheckError(
                f"Type '{
                    object_type.name}' is not slice-assignable (method 'slice_set' first two parameters must be i64)",
                span,
            )

        begin_arg_type = self._infer_expression_type(args[0])
        end_arg_type = self._infer_expression_type(args[1])
        self._require_array_index_type(begin_arg_type, args[0].span)
        self._require_array_index_type(end_arg_type, args[1].span)

        qualified_value_param = self._qualify_member_type_for_owner(method_sig.params[2], object_type.name)
        value_arg_type = self._infer_expression_type(args[2])
        self._require_assignable(qualified_value_param, value_arg_type, args[2].span)

        qualified_return_type = self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)
        if qualified_return_type.name != "unit":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must return unit)",
                span,
            )

        return TypeInfo(name="unit", kind="primitive")

    def _resolve_imported_function_sig(self, fn_name: str, span: SourceSpan) -> FunctionSig | None:
        return lookup_resolve_imported_function_sig(
            self.ctx,
            fn_name,
            span,
        )

    def _check_call_arguments(self, params: list[TypeInfo], args: list[Expression], span: SourceSpan) -> None:
        if len(params) != len(args):
            raise TypeCheckError(f"Expected {len(params)} arguments, got {len(args)}", span)

        for param_type, arg_expr in zip(params, args):
            arg_type = self._infer_expression_type(arg_expr)
            self._require_assignable(param_type, arg_type, arg_expr.span)

    def _infer_constructor_call_type(
        self,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
        result_type: TypeInfo,
    ) -> TypeInfo:
        if class_info.constructor_is_private:
            owner_canonical = self._canonicalize_reference_type_name(result_type.name)
            if self.ctx.current_private_owner_type != owner_canonical:
                raise TypeCheckError(f"Constructor for class '{class_info.name}' is private", span)

        ctor_params = [class_info.fields[field_name] for field_name in class_info.constructor_param_order]
        self._check_call_arguments(ctor_params, args, span)
        return result_type

    def _ensure_field_access_assignable(self, expr: FieldAccessExpr) -> None:
        object_type = self._infer_expression_type(expr.object_expr)
        class_info = self._lookup_class_by_type_name(object_type.name)
        if class_info is None:
            raise TypeCheckError("Invalid assignment target", expr.span)

        field_type = class_info.fields.get(expr.field_name)
        if field_type is None:
            raise TypeCheckError("Invalid assignment target", expr.span)

        self._require_member_visible(class_info, object_type.name, expr.field_name, "field", expr.span)

        if expr.field_name in class_info.final_fields:
            raise TypeCheckError(f"Field '{class_info.name}.{expr.field_name}' is final", expr.span)

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
