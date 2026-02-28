from __future__ import annotations

from compiler.ast_nodes import *
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.str_type_utils import STR_CLASS_NAME, is_str_type_name
from compiler.typecheck_model import (
    ClassInfo,
    FunctionSig,
    NUMERIC_TYPE_NAMES,
    PRIMITIVE_TYPE_NAMES,
    REFERENCE_BUILTIN_TYPE_NAMES,
    TypeCheckError,
    TypeInfo,
)

ARRAY_METHOD_NAMES = {"len", "get", "set", "slice"}

I64_MAX_LITERAL = 9223372036854775807
I64_MIN_MAGNITUDE_LITERAL = 9223372036854775808
U64_MAX_LITERAL = 18446744073709551615


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

        if module_path is not None and module_function_sigs is not None and module_class_infos is not None:
            self.functions = module_function_sigs[module_path]
            self.classes = module_class_infos[module_path]
        else:
            self.functions: dict[str, FunctionSig] = {}
            self.classes: dict[str, ClassInfo] = {}

        self.scope_stack: list[dict[str, TypeInfo]] = []
        self.loop_depth: int = 0
        self.current_private_owner_type: str | None = None

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
        for class_decl in self.module_ast.classes:
            if class_decl.name in self.classes or class_decl.name in self.functions:
                raise TypeCheckError(f"Duplicate declaration '{class_decl.name}'", class_decl.span)
            self.classes[class_decl.name] = ClassInfo(
                name=class_decl.name,
                fields={},
                field_order=[],
                methods={},
                private_fields=set(),
                private_methods=set(),
            )

        for class_decl in self.module_ast.classes:
            fields: dict[str, TypeInfo] = {}
            field_order: list[str] = []
            for field_decl in class_decl.fields:
                if field_decl.name in fields:
                    raise TypeCheckError(f"Duplicate field '{field_decl.name}'", field_decl.span)
                field_type = self._resolve_type_ref(field_decl.type_ref)
                fields[field_decl.name] = field_type
                field_order.append(field_decl.name)

            methods: dict[str, FunctionSig] = {}
            for method_decl in class_decl.methods:
                if method_decl.name in methods:
                    raise TypeCheckError(f"Duplicate method '{method_decl.name}'", method_decl.span)
                methods[method_decl.name] = self._function_sig_from_decl(method_decl)

            private_fields = {field_decl.name for field_decl in class_decl.fields if field_decl.is_private}
            private_methods = {method_decl.name for method_decl in class_decl.methods if method_decl.is_private}

            self.classes[class_decl.name] = ClassInfo(
                name=class_decl.name,
                fields=fields,
                field_order=field_order,
                methods=methods,
                private_fields=private_fields,
                private_methods=private_methods,
            )

        for fn_decl in self.module_ast.functions:
            if fn_decl.is_extern and fn_decl.body is not None:
                raise TypeCheckError("Extern function must not have a body", fn_decl.span)
            if not fn_decl.is_extern and fn_decl.body is None:
                raise TypeCheckError("Function declaration missing body", fn_decl.span)
            if fn_decl.name in self.functions or fn_decl.name in self.classes:
                raise TypeCheckError(f"Duplicate declaration '{fn_decl.name}'", fn_decl.span)
            self.functions[fn_decl.name] = self._function_sig_from_decl(fn_decl)

    def _function_sig_from_decl(self, decl: FunctionDecl | MethodDecl) -> FunctionSig:
        params = [self._resolve_type_ref(param.type_ref) for param in decl.params]
        return FunctionSig(
            name=decl.name,
            params=params,
            return_type=self._resolve_type_ref(decl.return_type),
            is_static=decl.is_static if isinstance(decl, MethodDecl) else False,
            is_private=decl.is_private if isinstance(decl, MethodDecl) else False,
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
        previous_owner = self.current_private_owner_type
        if owner_class_name is not None:
            self.current_private_owner_type = self._canonicalize_reference_type_name(owner_class_name)

        self._push_scope()
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
            self._pop_scope()
            self.current_private_owner_type = previous_owner

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
            self.loop_depth += 1
            self._check_block(stmt.body, return_type)
            self.loop_depth -= 1
            return

        if isinstance(stmt, BreakStmt):
            if self.loop_depth <= 0:
                raise TypeCheckError("'break' is only allowed inside while loops", stmt.span)
            return

        if isinstance(stmt, ContinueStmt):
            if self.loop_depth <= 0:
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
                if object_type.element_type is None and object_type.name != "Map":
                    value_type = self._infer_expression_type(stmt.value)
                    self._ensure_structural_set_method_for_index_assignment(
                        object_type,
                        value_type,
                        stmt.target.span,
                    )
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
            return

        if isinstance(expr, IndexExpr):
            object_type = self._infer_expression_type(expr.object_expr)
            if object_type.element_type is None and object_type.name != "Map":
                self._ensure_structural_set_method_available_for_index_assignment(object_type, expr.span)
            return

        raise TypeCheckError("Invalid assignment target", expr.span)

    def _infer_expression_type(self, expr: Expression) -> TypeInfo:
        if isinstance(expr, IdentifierExpr):
            symbol_type = self._lookup_variable(expr.name)
            if symbol_type is not None:
                return symbol_type

            if expr.name in self.functions:
                return TypeInfo(name=f"__fn__:{expr.name}", kind="callable")

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
                if operand_type.name not in NUMERIC_TYPE_NAMES:
                    raise TypeCheckError("Unary '-' requires numeric operand", expr.span)
                return operand_type

            raise TypeCheckError(f"Unknown unary operator '{expr.operator}'", expr.span)

        if isinstance(expr, BinaryExpr):
            left_type = self._infer_expression_type(expr.left)
            right_type = self._infer_expression_type(expr.right)
            op = expr.operator

            if op in {"+", "-", "*", "/", "%"}:
                if left_type.name not in NUMERIC_TYPE_NAMES or right_type.name not in NUMERIC_TYPE_NAMES:
                    raise TypeCheckError(f"Operator '{op}' requires numeric operands", expr.span)
                if left_type.name != right_type.name:
                    raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
                if op == "%" and left_type.name == "double":
                    raise TypeCheckError("Operator '%' is not supported for 'double'", expr.span)
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
                    return TypeInfo(name=f"__fn__:{dotted}:{member_name}", kind="callable")
                if kind == "class":
                    dotted = ".".join(owner_module)
                    return TypeInfo(name=f"__class__:{dotted}:{member_name}", kind="callable")
                dotted = ".".join(owner_module)
                return TypeInfo(name=f"__module__:{dotted}", kind="module")

            object_type = self._infer_expression_type(expr.object_expr)

            if object_type.element_type is not None:
                if expr.field_name not in ARRAY_METHOD_NAMES:
                    raise TypeCheckError(f"Array type '{object_type.name}' has no member '{expr.field_name}'", expr.span)
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
                return TypeInfo(name=f"__method__:{class_info.name}:{method_sig.name}", kind="callable")

            raise TypeCheckError(f"Class '{class_info.name}' has no member '{expr.field_name}'", expr.span)

        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expression_type(expr.object_expr)
            index_type = self._infer_expression_type(expr.index_expr)
            if obj_type.element_type is not None:
                self._require_array_index_type(index_type, expr.index_expr.span)
                return obj_type.element_type

            if obj_type.name == "Map":
                return TypeInfo(name="Obj", kind="reference")

            class_info = self._lookup_class_by_type_name(obj_type.name)
            if class_info is not None:
                self._require_array_index_type(index_type, expr.index_expr.span)
                return self._resolve_structural_get_method_result_type(obj_type, class_info, expr.span)
            raise TypeCheckError(f"Type '{obj_type.name}' is not indexable", expr.span)

        raise TypeCheckError("Unsupported expression", expr.span)

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
                    raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
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
                if method_name == "get":
                    if len(expr.arguments) != 1:
                        raise TypeCheckError(f"Expected 1 arguments, got {len(expr.arguments)}", expr.span)
                    index_type = self._infer_expression_type(expr.arguments[0])
                    self._require_array_index_type(index_type, expr.arguments[0].span)
                    return object_type.element_type
                if method_name == "set":
                    if len(expr.arguments) != 2:
                        raise TypeCheckError(f"Expected 2 arguments, got {len(expr.arguments)}", expr.span)
                    index_type = self._infer_expression_type(expr.arguments[0])
                    self._require_array_index_type(index_type, expr.arguments[0].span)
                    value_type = self._infer_expression_type(expr.arguments[1])
                    self._require_assignable(object_type.element_type, value_type, expr.arguments[1].span)
                    return TypeInfo(name="unit", kind="primitive")
                if method_name == "slice":
                    if len(expr.arguments) != 2:
                        raise TypeCheckError(f"Expected 2 arguments, got {len(expr.arguments)}", expr.span)
                    start_type = self._infer_expression_type(expr.arguments[0])
                    end_type = self._infer_expression_type(expr.arguments[1])
                    self._require_array_index_type(start_type, expr.arguments[0].span)
                    self._require_array_index_type(end_type, expr.arguments[1].span)
                    return object_type
                raise TypeCheckError(f"Array type '{object_type.name}' has no method '{method_name}'", expr.span)

            class_info = self._lookup_class_by_type_name(object_type.name)
            if class_info is None:
                raise TypeCheckError(f"Type '{object_type.name}' has no callable members", expr.span)

            method_sig = class_info.methods.get(expr.callee.field_name)
            if method_sig is None:
                raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
            self._require_member_visible(class_info, object_type.name, expr.callee.field_name, "method", expr.span)

            if expr.callee.field_name == "slice":
                return self._resolve_structural_slice_method_result_type(
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
        raise TypeCheckError(f"Expression of type '{callee_type.name}' is not callable", expr.callee.span)

    def _class_type_name_from_callable(self, callable_name: str) -> str:
        if not callable_name.startswith("__class__:"):
            raise ValueError(f"invalid class callable name: {callable_name}")
        payload = callable_name[len("__class__:") :]
        if ":" not in payload:
            return payload
        owner_dotted, class_name = payload.rsplit(":", 1)
        return f"{owner_dotted}::{class_name}"

    def _resolve_structural_get_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        span: SourceSpan,
    ) -> TypeInfo:
        method_sig = class_info.methods.get("get")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (missing method 'get(i64)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "get", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (method 'get' must be instance method)",
                span,
            )
        if len(method_sig.params) != 1:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (method 'get' must take exactly 1 argument)",
                span,
            )

        qualified_index_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        if qualified_index_param.name != "i64":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not indexable (method 'get' first parameter must be i64)",
                span,
            )

        return self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)

    def _ensure_structural_set_method_available_for_index_assignment(
        self,
        object_type: TypeInfo,
        span: SourceSpan,
    ) -> None:
        class_info = self._lookup_class_by_type_name(object_type.name)
        if class_info is None:
            raise TypeCheckError(f"Type '{object_type.name}' is not index-assignable", span)

        method_sig = class_info.methods.get("set")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (missing method 'set(i64, T)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "set", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'set' must be instance method)",
                span,
            )
        if len(method_sig.params) != 2:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'set' must take exactly 2 arguments)",
                span,
            )

        qualified_index_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        if qualified_index_param.name != "i64":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'set' first parameter must be i64)",
                span,
            )

        qualified_return_type = self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)
        if qualified_return_type.name != "unit":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not index-assignable (method 'set' must return unit)",
                span,
            )

    def _ensure_structural_set_method_for_index_assignment(
        self,
        object_type: TypeInfo,
        value_type: TypeInfo,
        span: SourceSpan,
    ) -> None:
        class_info = self._lookup_class_by_type_name(object_type.name)
        if class_info is None:
            raise TypeCheckError(f"Type '{object_type.name}' is not index-assignable", span)

        get_result_type = self._resolve_structural_get_method_result_type(object_type, class_info, span)
        self._ensure_structural_set_method_available_for_index_assignment(object_type, span)

        method_sig = class_info.methods["set"]
        qualified_value_param = self._qualify_member_type_for_owner(method_sig.params[1], object_type.name)
        self._require_assignable(qualified_value_param, value_type, span)

        if not self._type_infos_equal(qualified_value_param, get_result_type):
            raise TypeCheckError(
                f"Type '{object_type.name}' index sugar requires matching get/set value type",
                span,
            )

    def _resolve_structural_slice_method_result_type(
        self,
        object_type: TypeInfo,
        class_info: ClassInfo,
        args: list[Expression],
        span: SourceSpan,
    ) -> TypeInfo:
        method_sig = class_info.methods.get("slice")
        if method_sig is None:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (missing method 'slice(i64, i64)')",
                span,
            )
        self._require_member_visible(class_info, object_type.name, "slice", "method", span)
        if method_sig.is_static:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice' must be instance method)",
                span,
            )
        if len(method_sig.params) != 2:
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice' must take exactly 2 arguments)",
                span,
            )
        if len(args) != 2:
            raise TypeCheckError(f"Expected 2 arguments, got {len(args)}", span)

        qualified_begin_param = self._qualify_member_type_for_owner(method_sig.params[0], object_type.name)
        qualified_end_param = self._qualify_member_type_for_owner(method_sig.params[1], object_type.name)
        if qualified_begin_param.name != "i64" or qualified_end_param.name != "i64":
            raise TypeCheckError(
                f"Type '{object_type.name}' is not sliceable (method 'slice' parameters must be i64)",
                span,
            )

        begin_arg_type = self._infer_expression_type(args[0])
        end_arg_type = self._infer_expression_type(args[1])
        self._require_array_index_type(begin_arg_type, args[0].span)
        self._require_array_index_type(end_arg_type, args[1].span)
        return self._qualify_member_type_for_owner(method_sig.return_type, object_type.name)

    def _resolve_imported_function_sig(self, fn_name: str, span: SourceSpan) -> FunctionSig | None:
        current_module = self._current_module_info()
        if (
            current_module is None
            or self.modules is None
            or self.module_function_sigs is None
        ):
            return None

        matches: list[ModulePath] = []
        for import_info in current_module.imports.values():
            module_path = import_info.module_path
            module_info = self.modules[module_path]
            symbol = module_info.exported_symbols.get(fn_name)
            if symbol is not None and symbol.kind == "function":
                matches.append(module_path)

        if not matches:
            return None

        if len(matches) > 1:
            candidates = ", ".join(sorted(".".join(path) for path in matches))
            raise TypeCheckError(
                f"Ambiguous imported function '{fn_name}' (matches: {candidates})",
                span,
            )

        return self.module_function_sigs[matches[0]][fn_name]

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
        ctor_params = [class_info.fields[field_name] for field_name in class_info.field_order]
        self._check_call_arguments(ctor_params, args, span)
        return result_type

    def _resolve_type_ref(self, type_ref: TypeRefNode) -> TypeInfo:
        if isinstance(type_ref, ArrayTypeRef):
            element_type = self._resolve_type_ref(type_ref.element_type)
            return TypeInfo(name=f"{element_type.name}[]", kind="reference", element_type=element_type)

        name = type_ref.name
        if name in PRIMITIVE_TYPE_NAMES:
            return TypeInfo(name=name, kind="primitive")

        if "." in name:
            qualified = self._resolve_qualified_imported_class_type(name, type_ref.span)
            if qualified is not None:
                return qualified

        if name in self.classes:
            return TypeInfo(name=name, kind="reference")

        imported_class_type = self._resolve_imported_class_type(name, type_ref.span)
        if imported_class_type is not None:
            return imported_class_type

        if name in REFERENCE_BUILTIN_TYPE_NAMES:
            return TypeInfo(name=name, kind="reference")

        raise TypeCheckError(f"Unknown type '{name}'", type_ref.span)

    def _resolve_string_type(self, span: SourceSpan) -> TypeInfo:
        if STR_CLASS_NAME in self.classes:
            return TypeInfo(name=STR_CLASS_NAME, kind="reference")

        imported_class_type = self._resolve_imported_class_type(STR_CLASS_NAME, span)
        if imported_class_type is not None:
            return imported_class_type

        global_class_type = self._resolve_unique_global_class_type(STR_CLASS_NAME, span)
        if global_class_type is not None:
            return global_class_type

        raise TypeCheckError(f"Unknown type '{STR_CLASS_NAME}'", span)

    def _resolve_unique_global_class_type(self, class_name: str, span: SourceSpan) -> TypeInfo | None:
        if self.module_class_infos is None:
            return None

        matches: list[ModulePath] = []
        for module_path, classes in self.module_class_infos.items():
            if class_name in classes:
                matches.append(module_path)

        if not matches:
            return None

        if len(matches) > 1:
            candidates = ", ".join(sorted(".".join(path) for path in matches))
            raise TypeCheckError(
                f"Ambiguous global class '{class_name}' (matches: {candidates})",
                span,
            )

        owner_dotted = ".".join(matches[0])
        return TypeInfo(name=f"{owner_dotted}::{class_name}", kind="reference")

    def _resolve_imported_class_type(self, class_name: str, span: SourceSpan) -> TypeInfo | None:
        matched_module = self._resolve_unique_imported_class_module(
            class_name,
            span,
            ambiguity_label="type",
        )
        if matched_module is None:
            return None

        owner_dotted = ".".join(matched_module)
        return TypeInfo(name=f"{owner_dotted}::{class_name}", kind="reference")

    def _qualify_member_type_for_owner(self, member_type: TypeInfo, owner_type_name: str) -> TypeInfo:
        if member_type.element_type is not None:
            qualified_element_type = self._qualify_member_type_for_owner(member_type.element_type, owner_type_name)
            if qualified_element_type == member_type.element_type:
                return member_type
            return TypeInfo(name=f"{qualified_element_type.name}[]", kind="reference", element_type=qualified_element_type)

        if member_type.kind != "reference" or "::" in member_type.name:
            return member_type
        if "::" not in owner_type_name or self.module_class_infos is None:
            return member_type

        owner_dotted, _owner_class_name = owner_type_name.split("::", 1)
        owner_module = tuple(owner_dotted.split("."))
        owner_classes = self.module_class_infos.get(owner_module)
        if owner_classes is None or member_type.name not in owner_classes:
            return member_type

        return TypeInfo(name=f"{owner_dotted}::{member_type.name}", kind="reference")

    def _resolve_unique_imported_class_module(
        self,
        class_name: str,
        span: SourceSpan,
        *,
        ambiguity_label: str,
    ) -> ModulePath | None:
        current_module = self._current_module_info()
        if (
            current_module is None
            or self.modules is None
        ):
            return None

        matches: list[ModulePath] = []
        for import_info in current_module.imports.values():
            module_path = import_info.module_path
            module_info = self.modules[module_path]
            symbol = module_info.exported_symbols.get(class_name)
            if symbol is not None and symbol.kind == "class":
                matches.append(module_path)

        if not matches:
            return None

        if len(matches) > 1:
            candidates = ", ".join(sorted(".".join(path) for path in matches))
            raise TypeCheckError(
                f"Ambiguous imported {ambiguity_label} '{class_name}' (matches: {candidates})",
                span,
            )

        return matches[0]

    def _resolve_qualified_imported_class_type(self, qualified_name: str, span: SourceSpan) -> TypeInfo | None:
        current_module = self._current_module_info()
        if (
            current_module is None
            or self.modules is None
        ):
            return None

        parts = qualified_name.split(".")
        if len(parts) < 2:
            return None

        import_alias = parts[0]
        import_info = current_module.imports.get(import_alias)
        if import_info is None:
            return None

        module_path = import_info.module_path
        for segment in parts[1:-1]:
            module_info = self.modules[module_path]
            next_module = module_info.exported_modules.get(segment)
            if next_module is None:
                dotted = ".".join(module_path)
                raise TypeCheckError(
                    f"Module '{dotted}' has no exported module '{segment}'",
                    span,
                )
            module_path = next_module

        class_name = parts[-1]
        module_info = self.modules[module_path]
        symbol = module_info.exported_symbols.get(class_name)
        if symbol is None or symbol.kind != "class":
            dotted = ".".join(module_path)
            raise TypeCheckError(
                f"Module '{dotted}' has no exported class '{class_name}'",
                span,
            )

        owner_dotted = ".".join(module_path)
        return TypeInfo(name=f"{owner_dotted}::{class_name}", kind="reference")

    def _declare_variable(self, name: str, var_type: TypeInfo, span: SourceSpan) -> None:
        scope = self.scope_stack[-1]
        if name in scope:
            raise TypeCheckError(f"Duplicate local variable '{name}'", span)
        scope[name] = var_type

    def _lookup_variable(self, name: str) -> TypeInfo | None:
        for scope in reversed(self.scope_stack):
            if name in scope:
                return scope[name]
        return None

    def _push_scope(self) -> None:
        self.scope_stack.append({})

    def _pop_scope(self) -> None:
        self.scope_stack.pop()

    def _require_type_name(self, actual: TypeInfo, expected_name: str, span: SourceSpan) -> None:
        if actual.name != expected_name:
            raise TypeCheckError(f"Expected '{expected_name}', got '{actual.name}'", span)

    def _require_array_size_type(self, actual: TypeInfo, span: SourceSpan) -> None:
        if actual.name in {"u64", "i64"}:
            return
        raise TypeCheckError(f"Expected 'u64', got '{actual.name}'", span)

    def _require_array_index_type(self, actual: TypeInfo, span: SourceSpan) -> None:
        if actual.name == "i64":
            return
        raise TypeCheckError(f"Expected 'i64', got '{actual.name}'", span)

    def _canonicalize_reference_type_name(self, type_name: str) -> str:
        if "::" in type_name:
            return type_name
        if self.module_path is None:
            return type_name
        if type_name not in self.classes:
            return type_name
        owner_dotted = ".".join(self.module_path)
        return f"{owner_dotted}::{type_name}"

    def _type_names_equal(self, left: str, right: str) -> bool:
        if left == right:
            return True
        return self._canonicalize_reference_type_name(left) == self._canonicalize_reference_type_name(right)

    def _type_infos_equal(self, left: TypeInfo, right: TypeInfo) -> bool:
        if left.element_type is not None or right.element_type is not None:
            if left.element_type is None or right.element_type is None:
                return False
            return self._type_infos_equal(left.element_type, right.element_type)
        return self._type_names_equal(left.name, right.name)

    def _require_assignable(self, target: TypeInfo, value: TypeInfo, span: SourceSpan) -> None:
        if self._type_infos_equal(target, value):
            return
        if target.kind == "reference" and value.kind == "null":
            return
        if target.name == "Obj" and value.kind == "reference":
            return
        raise TypeCheckError(f"Cannot assign '{value.name}' to '{target.name}'", span)

    def _is_comparable(self, left: TypeInfo, right: TypeInfo) -> bool:
        if self._type_infos_equal(left, right):
            return True
        if left.kind == "reference" and right.kind == "null":
            return True
        if right.kind == "reference" and left.kind == "null":
            return True
        return False

    def _check_explicit_cast(self, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
        if self._type_infos_equal(source, target):
            return

        if source.kind == "primitive" and target.kind == "primitive":
            if source.name == "unit" or target.name == "unit":
                raise TypeCheckError("Casts involving 'unit' are not allowed", span)
            return

        if source.kind == "reference" and target.name == "Obj":
            return

        if source.name == "Obj" and target.kind == "reference" and target.name != "Obj":
            return

        raise TypeCheckError(
            f"Invalid cast from '{source.name}' to '{target.name}'",
            span,
        )

    def _current_module_info(self) -> ModuleInfo | None:
        if self.modules is None or self.module_path is None:
            return None
        return self.modules[self.module_path]

    def _lookup_class_by_type_name(self, type_name: str) -> ClassInfo | None:
        local = self.classes.get(type_name)
        if local is not None:
            return local

        if "::" not in type_name or self.module_class_infos is None:
            return None

        owner_dotted, class_name = type_name.split("::", 1)
        owner_module = tuple(owner_dotted.split("."))
        owner_classes = self.module_class_infos.get(owner_module)
        if owner_classes is None:
            return None
        return owner_classes.get(class_name)

    def _resolve_module_member(self, expr: FieldAccessExpr) -> tuple[str, ModulePath, str] | None:
        if self.modules is None or self.module_path is None:
            return None

        chain = self._flatten_field_chain(expr)
        if chain is None or len(chain) < 2:
            return None

        current_module = self.modules[self.module_path]
        import_info = current_module.imports.get(chain[0])
        if import_info is None:
            return None

        module_path = import_info.module_path
        for index, segment in enumerate(chain[1:]):
            module_info = self.modules[module_path]
            is_last = index == len(chain[1:]) - 1

            reexported = module_info.exported_modules.get(segment)
            if reexported is not None:
                module_path = reexported
                if is_last:
                    return ("module", module_path, segment)
                continue

            exported_symbol = module_info.exported_symbols.get(segment)

            if (
                self.module_function_sigs is not None
                and segment in self.module_function_sigs[module_path]
                and exported_symbol is not None
                and exported_symbol.kind == "function"
            ):
                if is_last:
                    return ("function", module_path, segment)
                return None

            if (
                self.module_class_infos is not None
                and segment in self.module_class_infos[module_path]
                and exported_symbol is not None
                and exported_symbol.kind == "class"
            ):
                if is_last:
                    return ("class", module_path, segment)
                return None

            return None

        return None

    def _flatten_field_chain(self, expr: Expression) -> list[str] | None:
        if isinstance(expr, IdentifierExpr):
            return [expr.name]

        if isinstance(expr, FieldAccessExpr):
            left = self._flatten_field_chain(expr.object_expr)
            if left is None:
                return None
            return [*left, expr.field_name]

        return None

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
        if self.current_private_owner_type == owner_canonical:
            return

        raise TypeCheckError(f"Member '{class_info.name}.{member_name}' is private", span)
