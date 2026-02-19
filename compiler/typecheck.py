from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import *
from compiler.lexer import SourceSpan


PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
REFERENCE_BUILTIN_TYPE_NAMES = {
    "Obj",
    "Str",
    "Vec",
    "Map",
    "BoxI64",
    "BoxU64",
    "BoxU8",
    "BoxBool",
    "BoxDouble",
}
NUMERIC_TYPE_NAMES = {"i64", "u64", "u8", "double"}


@dataclass(frozen=True)
class TypeInfo:
    name: str
    kind: str


@dataclass(frozen=True)
class FunctionSig:
    name: str
    params: list[TypeInfo]
    return_type: TypeInfo


@dataclass(frozen=True)
class ClassInfo:
    name: str
    fields: dict[str, TypeInfo]
    field_order: list[str]
    methods: dict[str, FunctionSig]


class TypeCheckError(ValueError):
    def __init__(self, message: str, span: SourceSpan):
        super().__init__(f"{message} at {span.start.path}:{span.start.line}:{span.start.column}")
        self.message = message
        self.span = span


class TypeChecker:
    def __init__(self, module_ast: ModuleAst):
        self.module_ast = module_ast
        self.functions: dict[str, FunctionSig] = {}
        self.classes: dict[str, ClassInfo] = {}
        self.scope_stack: list[dict[str, TypeInfo]] = []

    def check(self) -> None:
        self._collect_declarations()

        for fn_decl in self.module_ast.functions:
            fn_sig = self.functions[fn_decl.name]
            self._check_function_like(fn_decl.params, fn_decl.body, fn_sig.return_type)

        for class_decl in self.module_ast.classes:
            class_info = self.classes[class_decl.name]
            for method_decl in class_decl.methods:
                method_sig = class_info.methods[method_decl.name]
                self._check_function_like(method_decl.params, method_decl.body, method_sig.return_type)

    def _collect_declarations(self) -> None:
        for class_decl in self.module_ast.classes:
            if class_decl.name in self.classes or class_decl.name in self.functions:
                raise TypeCheckError(f"Duplicate declaration '{class_decl.name}'", class_decl.span)

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

            self.classes[class_decl.name] = ClassInfo(
                name=class_decl.name,
                fields=fields,
                field_order=field_order,
                methods=methods,
            )

        for fn_decl in self.module_ast.functions:
            if fn_decl.name in self.functions or fn_decl.name in self.classes:
                raise TypeCheckError(f"Duplicate declaration '{fn_decl.name}'", fn_decl.span)
            self.functions[fn_decl.name] = self._function_sig_from_decl(fn_decl)

    def _function_sig_from_decl(self, decl: FunctionDecl | MethodDecl) -> FunctionSig:
        params = [self._resolve_type_ref(param.type_ref) for param in decl.params]
        return FunctionSig(
            name=decl.name,
            params=params,
            return_type=self._resolve_type_ref(decl.return_type),
        )

    def _check_function_like(self, params: list[ParamDecl], body: BlockStmt, return_type: TypeInfo) -> None:
        self._push_scope()
        for param in params:
            param_type = self._resolve_type_ref(param.type_ref)
            self._declare_variable(param.name, param_type, param.span)

        self._check_block(body, return_type)

        if return_type.name != "unit" and not self._block_guarantees_return(body):
            raise TypeCheckError("Non-unit function must return on all paths", body.span)

        self._pop_scope()

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
            self._check_block(stmt.body, return_type)
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

        if isinstance(expr, (FieldAccessExpr, IndexExpr)):
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

            raise TypeCheckError(f"Unknown identifier '{expr.name}'", expr.span)

        if isinstance(expr, LiteralExpr):
            if expr.value.startswith('"'):
                return TypeInfo(name="Str", kind="reference")
            if expr.value in {"true", "false"}:
                return TypeInfo(name="bool", kind="primitive")
            if "." in expr.value:
                return TypeInfo(name="double", kind="primitive")
            return TypeInfo(name="i64", kind="primitive")

        if isinstance(expr, NullExpr):
            return TypeInfo(name="null", kind="null")

        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expression_type(expr.operand)
            if expr.operator == "!":
                self._require_type_name(operand_type, "bool", expr.operand.span)
                return TypeInfo(name="bool", kind="primitive")

            if expr.operator == "-":
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

        if isinstance(expr, FieldAccessExpr):
            object_type = self._infer_expression_type(expr.object_expr)
            class_info = self.classes.get(object_type.name)
            if class_info is None:
                raise TypeCheckError(f"Type '{object_type.name}' has no fields/methods", expr.span)

            field_type = class_info.fields.get(expr.field_name)
            if field_type is not None:
                return field_type

            method_sig = class_info.methods.get(expr.field_name)
            if method_sig is not None:
                return TypeInfo(name=f"__method__:{class_info.name}:{method_sig.name}", kind="callable")

            raise TypeCheckError(f"Class '{class_info.name}' has no member '{expr.field_name}'", expr.span)

        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expression_type(expr.object_expr)
            index_type = self._infer_expression_type(expr.index_expr)
            if obj_type.name == "Vec":
                self._require_type_name(index_type, "i64", expr.index_expr.span)
                return TypeInfo(name="Obj", kind="reference")
            if obj_type.name == "Map":
                return TypeInfo(name="Obj", kind="reference")
            raise TypeCheckError(f"Type '{obj_type.name}' is not indexable", expr.span)

        raise TypeCheckError("Unsupported expression", expr.span)

    def _infer_call_type(self, expr: CallExpr) -> TypeInfo:
        if isinstance(expr.callee, IdentifierExpr):
            name = expr.callee.name

            fn_sig = self.functions.get(name)
            if fn_sig is not None:
                self._check_call_arguments(fn_sig.params, expr.arguments, expr.span)
                return fn_sig.return_type

            class_info = self.classes.get(name)
            if class_info is not None:
                ctor_params = [class_info.fields[field_name] for field_name in class_info.field_order]
                self._check_call_arguments(ctor_params, expr.arguments, expr.span)
                return TypeInfo(name=class_info.name, kind="reference")

        if isinstance(expr.callee, FieldAccessExpr):
            object_type = self._infer_expression_type(expr.callee.object_expr)
            class_info = self.classes.get(object_type.name)
            if class_info is None:
                raise TypeCheckError(f"Type '{object_type.name}' has no callable members", expr.span)

            method_sig = class_info.methods.get(expr.callee.field_name)
            if method_sig is None:
                raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)

            self._check_call_arguments(method_sig.params, expr.arguments, expr.span)
            return method_sig.return_type

        callee_type = self._infer_expression_type(expr.callee)
        raise TypeCheckError(f"Expression of type '{callee_type.name}' is not callable", expr.callee.span)

    def _check_call_arguments(self, params: list[TypeInfo], args: list[Expression], span: SourceSpan) -> None:
        if len(params) != len(args):
            raise TypeCheckError(f"Expected {len(params)} arguments, got {len(args)}", span)

        for param_type, arg_expr in zip(params, args):
            arg_type = self._infer_expression_type(arg_expr)
            self._require_assignable(param_type, arg_type, arg_expr.span)

    def _resolve_type_ref(self, type_ref: TypeRef) -> TypeInfo:
        name = type_ref.name
        if name in PRIMITIVE_TYPE_NAMES:
            return TypeInfo(name=name, kind="primitive")

        if name in REFERENCE_BUILTIN_TYPE_NAMES or name in self.classes:
            return TypeInfo(name=name, kind="reference")

        raise TypeCheckError(f"Unknown type '{name}'", type_ref.span)

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

    def _require_assignable(self, target: TypeInfo, value: TypeInfo, span: SourceSpan) -> None:
        if target.name == value.name:
            return
        if target.kind == "reference" and value.kind == "null":
            return
        if target.name == "Obj" and value.kind == "reference":
            return
        raise TypeCheckError(f"Cannot assign '{value.name}' to '{target.name}'", span)

    def _is_comparable(self, left: TypeInfo, right: TypeInfo) -> bool:
        if left.name == right.name:
            return True
        if left.kind == "reference" and right.kind == "null":
            return True
        if right.kind == "reference" and left.kind == "null":
            return True
        return False

    def _check_explicit_cast(self, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
        if source.name == target.name:
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


def typecheck(module_ast: ModuleAst) -> None:
    TypeChecker(module_ast).check()
