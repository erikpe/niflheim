from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import *
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath, ProgramInfo


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

    def check(self) -> None:
        if not self.pre_collected:
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

            if self._current_module_info() is not None and expr.name in self._current_module_info().imports:
                return TypeInfo(name=f"__module__:{expr.name}", kind="module")

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
            class_info = self._lookup_class_by_type_name(object_type.name)
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
            class_info = self._lookup_class_by_type_name(object_type.name)
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

    def _resolve_type_ref(self, type_ref: TypeRef) -> TypeInfo:
        name = type_ref.name
        if name in PRIMITIVE_TYPE_NAMES:
            return TypeInfo(name=name, kind="primitive")

        if "." in name:
            qualified = self._resolve_qualified_imported_class_type(name, type_ref.span)
            if qualified is not None:
                return qualified

        if name in REFERENCE_BUILTIN_TYPE_NAMES or name in self.classes:
            return TypeInfo(name=name, kind="reference")

        imported_class_type = self._resolve_imported_class_type(name, type_ref.span)
        if imported_class_type is not None:
            return imported_class_type

        raise TypeCheckError(f"Unknown type '{name}'", type_ref.span)

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
            or self.module_class_infos is None
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
            or self.module_class_infos is None
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


def typecheck_program(program: ProgramInfo) -> None:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {}
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {}

    for module_path, module_info in program.modules.items():
        checker = TypeChecker(module_info.ast)
        checker._collect_declarations()
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
