from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import (
    ArrayCtorExpr,
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    BreakStmt,
    CallExpr,
    CastExpr,
    ClassDecl,
    ContinueStmt,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForInStmt,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    LiteralExpr,
    MethodDecl,
    NullExpr,
    ParamDecl,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from compiler.resolver import ModulePath, ProgramInfo
from compiler.semantic_ir import (
    ArrayCtorExprS,
    BinaryExprS,
    CastExprS,
    ClassRefExpr,
    ConstructorCallExpr,
    FieldLValue,
    FieldReadExpr,
    FunctionCallExpr,
    FunctionRefExpr,
    IndexLValue,
    IndexReadExpr,
    InstanceMethodCallExpr,
    LiteralExprS,
    LocalLValue,
    LocalRefExpr,
    MethodRefExpr,
    NullExprS,
    SemanticAssign,
    SemanticBlock,
    SemanticBreak,
    SemanticClass,
    SemanticContinue,
    SemanticExpr,
    SemanticExprStmt,
    SemanticField,
    SemanticForIn,
    SemanticFunction,
    SemanticIf,
    SemanticMethod,
    SemanticModule,
    SemanticParam,
    SemanticProgram,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    StaticMethodCallExpr,
    UnaryExprS,
)
from compiler.semantic_symbols import (
    ClassId,
    ConstructorId,
    MethodId,
    ProgramSymbolIndex,
    build_program_symbol_index,
    class_id_for_decl,
    constructor_id_for_class,
    function_id_for_decl,
    method_id_for_decl,
)
from compiler.typecheck.bodies import check_bodies
from compiler.typecheck.call_helpers import class_type_name_from_callable
from compiler.typecheck.calls import infer_call_type
from compiler.typecheck.context import TypeCheckContext, declare_variable, lookup_variable, pop_scope, push_scope
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner, resolve_type_ref


@dataclass
class _ModuleLoweringContext:
    typecheck_ctx: TypeCheckContext
    symbol_index: ProgramSymbolIndex


def lower_program(program: ProgramInfo) -> SemanticProgram:
    symbol_index = build_program_symbol_index(program)
    module_contexts = _build_typecheck_contexts(program)
    modules = {
        module_path: _lower_module(program, module_path, module_contexts[module_path], symbol_index)
        for module_path in program.modules
    }
    return SemanticProgram(entry_module=program.entry_module, modules=modules)


def _build_typecheck_contexts(program: ProgramInfo) -> dict[ModulePath, TypeCheckContext]:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {
        module_path: {} for module_path in program.modules
    }
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {module_path: {} for module_path in program.modules}
    contexts: dict[ModulePath, TypeCheckContext] = {}

    for module_path, module_info in program.modules.items():
        contexts[module_path] = TypeCheckContext(
            module_ast=module_info.ast,
            module_path=module_path,
            modules=program.modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            functions=module_function_sigs[module_path],
            classes=module_class_infos[module_path],
        )

    for ctx in contexts.values():
        collect_module_declarations(ctx)

    for ctx in contexts.values():
        check_bodies(ctx)

    return contexts


def _lower_module(
    program: ProgramInfo, module_path: ModulePath, typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex
) -> SemanticModule:
    module_info = program.modules[module_path]
    lower_ctx = _ModuleLoweringContext(typecheck_ctx=typecheck_ctx, symbol_index=symbol_index)
    return SemanticModule(
        module_path=module_path,
        file_path=module_info.file_path,
        classes=[_lower_class(lower_ctx, module_path, class_decl) for class_decl in module_info.ast.classes],
        functions=[
            _lower_function(lower_ctx, module_path, function_decl) for function_decl in module_info.ast.functions
        ],
        span=module_info.ast.span,
    )


def _lower_class(lower_ctx: _ModuleLoweringContext, module_path: ModulePath, class_decl: ClassDecl) -> SemanticClass:
    return SemanticClass(
        class_id=class_id_for_decl(module_path, class_decl),
        is_export=class_decl.is_export,
        fields=[_lower_field(lower_ctx, field_decl) for field_decl in class_decl.fields],
        methods=[_lower_method(lower_ctx, module_path, class_decl, method_decl) for method_decl in class_decl.methods],
        span=class_decl.span,
    )


def _lower_field(lower_ctx: _ModuleLoweringContext, field_decl) -> SemanticField:
    initializer = None if field_decl.initializer is None else _lower_expr(lower_ctx, field_decl.initializer)
    return SemanticField(
        name=field_decl.name,
        type_name=_resolved_type_name(lower_ctx.typecheck_ctx, field_decl.type_ref),
        initializer=initializer,
        is_private=field_decl.is_private,
        is_final=field_decl.is_final,
        span=field_decl.span,
    )


def _lower_function(
    lower_ctx: _ModuleLoweringContext, module_path: ModulePath, function_decl: FunctionDecl
) -> SemanticFunction:
    body = None
    if function_decl.body is not None:
        body = _lower_function_like_body(
            lower_ctx, params=function_decl.params, body=function_decl.body, receiver_type=None
        )

    return SemanticFunction(
        function_id=function_id_for_decl(module_path, function_decl),
        params=[_lower_param(lower_ctx.typecheck_ctx, param) for param in function_decl.params],
        return_type_name=_resolved_type_name(lower_ctx.typecheck_ctx, function_decl.return_type),
        body=body,
        is_export=function_decl.is_export,
        is_extern=function_decl.is_extern,
        span=function_decl.span,
    )


def _lower_method(
    lower_ctx: _ModuleLoweringContext, module_path: ModulePath, class_decl: ClassDecl, method_decl: MethodDecl
) -> SemanticMethod:
    receiver_type = None
    if not method_decl.is_static:
        receiver_type = TypeInfo(name=class_decl.name, kind="reference")

    body = _lower_function_like_body(
        lower_ctx, params=method_decl.params, body=method_decl.body, receiver_type=receiver_type
    )
    return SemanticMethod(
        method_id=method_id_for_decl(module_path, class_decl, method_decl),
        params=[_lower_param(lower_ctx.typecheck_ctx, param) for param in method_decl.params],
        return_type_name=_resolved_type_name(lower_ctx.typecheck_ctx, method_decl.return_type),
        body=body,
        is_static=method_decl.is_static,
        is_private=method_decl.is_private,
        span=method_decl.span,
    )


def _lower_param(typecheck_ctx: TypeCheckContext, param: ParamDecl) -> SemanticParam:
    return SemanticParam(name=param.name, type_name=_resolved_type_name(typecheck_ctx, param.type_ref), span=param.span)


def _lower_function_like_body(
    lower_ctx: _ModuleLoweringContext, *, params: list[ParamDecl], body: BlockStmt, receiver_type: TypeInfo | None
) -> SemanticBlock:
    typecheck_ctx = lower_ctx.typecheck_ctx
    push_scope(typecheck_ctx)
    typecheck_ctx.function_local_names_stack.append(set())
    try:
        if receiver_type is not None:
            declare_variable(typecheck_ctx, "__self", receiver_type, body.span)
        for param in params:
            declare_variable(typecheck_ctx, param.name, resolve_type_ref(typecheck_ctx, param.type_ref), param.span)
        return _lower_block(lower_ctx, body)
    finally:
        typecheck_ctx.function_local_names_stack.pop()
        pop_scope(typecheck_ctx)


def _lower_block(lower_ctx: _ModuleLoweringContext, block: BlockStmt) -> SemanticBlock:
    push_scope(lower_ctx.typecheck_ctx)
    try:
        statements = [_lower_stmt(lower_ctx, stmt) for stmt in block.statements]
        return SemanticBlock(statements=statements, span=block.span)
    finally:
        pop_scope(lower_ctx.typecheck_ctx)


def _lower_stmt(lower_ctx: _ModuleLoweringContext, stmt: Statement) -> SemanticStmt:
    if isinstance(stmt, BlockStmt):
        return _lower_block(lower_ctx, stmt)

    if isinstance(stmt, VarDeclStmt):
        initializer = None if stmt.initializer is None else _lower_expr(lower_ctx, stmt.initializer)
        var_type = resolve_type_ref(lower_ctx.typecheck_ctx, stmt.type_ref)
        declare_variable(lower_ctx.typecheck_ctx, stmt.name, var_type, stmt.span)
        return SemanticVarDecl(name=stmt.name, type_name=var_type.name, initializer=initializer, span=stmt.span)

    if isinstance(stmt, IfStmt):
        else_block = None
        if isinstance(stmt.else_branch, BlockStmt):
            else_block = _lower_block(lower_ctx, stmt.else_branch)
        elif isinstance(stmt.else_branch, IfStmt):
            nested_if = _lower_stmt(lower_ctx, stmt.else_branch)
            else_block = SemanticBlock(statements=[nested_if], span=stmt.else_branch.span)
        return SemanticIf(
            condition=_lower_expr(lower_ctx, stmt.condition),
            then_block=_lower_block(lower_ctx, stmt.then_branch),
            else_block=else_block,
            span=stmt.span,
        )

    if isinstance(stmt, WhileStmt):
        return SemanticWhile(
            condition=_lower_expr(lower_ctx, stmt.condition), body=_lower_block(lower_ctx, stmt.body), span=stmt.span
        )

    if isinstance(stmt, ForInStmt):
        element_type = TypeInfo(name=stmt.element_type_name, kind="reference")
        push_scope(lower_ctx.typecheck_ctx)
        try:
            declare_variable(lower_ctx.typecheck_ctx, stmt.element_name, element_type, stmt.span)
            body = _lower_block(lower_ctx, stmt.body)
        finally:
            pop_scope(lower_ctx.typecheck_ctx)
        return SemanticForIn(
            element_name=stmt.element_name,
            collection=_lower_expr(lower_ctx, stmt.collection_expr),
            iter_len_method=None,
            iter_get_method=None,
            element_type_name=stmt.element_type_name,
            body=body,
            span=stmt.span,
        )

    if isinstance(stmt, BreakStmt):
        return SemanticBreak(span=stmt.span)

    if isinstance(stmt, ContinueStmt):
        return SemanticContinue(span=stmt.span)

    if isinstance(stmt, ReturnStmt):
        value = None if stmt.value is None else _lower_expr(lower_ctx, stmt.value)
        return SemanticReturn(value=value, span=stmt.span)

    if isinstance(stmt, AssignStmt):
        return SemanticAssign(
            target=_lower_lvalue(lower_ctx, stmt.target), value=_lower_expr(lower_ctx, stmt.value), span=stmt.span
        )

    if isinstance(stmt, ExprStmt):
        return SemanticExprStmt(expr=_lower_expr(lower_ctx, stmt.expression), span=stmt.span)

    raise TypeError(f"Unsupported statement for semantic lowering: {type(stmt).__name__}")


def _lower_lvalue(lower_ctx: _ModuleLoweringContext, expr: Expression):
    if isinstance(expr, IdentifierExpr):
        local_type = lookup_variable(lower_ctx.typecheck_ctx, expr.name)
        if local_type is None:
            raise ValueError(f"Unknown local assignment target '{expr.name}'")
        return LocalLValue(name=expr.name, type_name=local_type.name, span=expr.span)

    if isinstance(expr, FieldAccessExpr):
        return FieldLValue(
            receiver=_lower_expr(lower_ctx, expr.object_expr),
            receiver_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr.object_expr).name,
            field_name=expr.field_name,
            field_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            span=expr.span,
        )

    if isinstance(expr, IndexExpr):
        return IndexLValue(
            target=_lower_expr(lower_ctx, expr.object_expr),
            index=_lower_expr(lower_ctx, expr.index_expr),
            value_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            set_method=None,
            span=expr.span,
        )

    raise TypeError(f"Unsupported lvalue for semantic lowering: {type(expr).__name__}")


def _lower_expr(lower_ctx: _ModuleLoweringContext, expr: Expression) -> SemanticExpr:
    expr_type = infer_expression_type(lower_ctx.typecheck_ctx, expr)

    if isinstance(expr, IdentifierExpr):
        local_type = lookup_variable(lower_ctx.typecheck_ctx, expr.name)
        if local_type is not None:
            return LocalRefExpr(name=expr.name, type_name=local_type.name, span=expr.span)

        local_function = lower_ctx.typecheck_ctx.functions.get(expr.name)
        if local_function is not None:
            function_id = _function_id_for_local_name(lower_ctx, expr.name)
            return FunctionRefExpr(function_id=function_id, type_name=expr_type.name, span=expr.span)

        imported_function = resolve_imported_function_sig(lower_ctx.typecheck_ctx, expr.name, expr.span)
        if imported_function is not None:
            function_id = _function_id_for_imported_name(lower_ctx, expr.name)
            return FunctionRefExpr(function_id=function_id, type_name=expr_type.name, span=expr.span)

        imported_class_name = resolve_imported_class_name(lower_ctx.typecheck_ctx, expr.name, expr.span)
        if expr.name in lower_ctx.typecheck_ctx.classes or imported_class_name is not None:
            type_name = expr.name if imported_class_name is None else imported_class_name
            class_id = _class_id_from_type_name(lower_ctx.typecheck_ctx.module_path, type_name)
            return ClassRefExpr(class_id=class_id, type_name=expr_type.name, span=expr.span)

        raise TypeError(f"Unsupported identifier expression for semantic lowering: {expr.name}")

    if isinstance(expr, LiteralExpr):
        return LiteralExprS(value=expr.value, type_name=expr_type.name, span=expr.span)

    if isinstance(expr, NullExpr):
        return NullExprS(span=expr.span)

    if isinstance(expr, UnaryExpr):
        return UnaryExprS(
            operator=expr.operator,
            operand=_lower_expr(lower_ctx, expr.operand),
            type_name=expr_type.name,
            span=expr.span,
        )

    if isinstance(expr, BinaryExpr):
        return BinaryExprS(
            operator=expr.operator,
            left=_lower_expr(lower_ctx, expr.left),
            right=_lower_expr(lower_ctx, expr.right),
            type_name=expr_type.name,
            span=expr.span,
        )

    if isinstance(expr, CastExpr):
        return CastExprS(
            operand=_lower_expr(lower_ctx, expr.operand),
            target_type_name=_resolved_type_name(lower_ctx.typecheck_ctx, expr.type_ref),
            type_name=expr_type.name,
            span=expr.span,
        )

    if isinstance(expr, ArrayCtorExpr):
        array_type = resolve_type_ref(lower_ctx.typecheck_ctx, expr.element_type_ref)
        assert array_type.element_type is not None
        return ArrayCtorExprS(
            element_type_name=array_type.element_type.name,
            length_expr=_lower_expr(lower_ctx, expr.length_expr),
            type_name=array_type.name,
            span=expr.span,
        )

    if isinstance(expr, FieldAccessExpr):
        module_member = resolve_module_member(lower_ctx.typecheck_ctx, expr)
        if module_member is not None:
            kind, owner_module, member_name = module_member
            if kind == "function":
                return FunctionRefExpr(
                    function_id=_function_id_for_module_member(lower_ctx, owner_module, member_name),
                    type_name=expr_type.name,
                    span=expr.span,
                )
            if kind == "class":
                return ClassRefExpr(
                    class_id=_class_id_for_module_member(owner_module, member_name),
                    type_name=expr_type.name,
                    span=expr.span,
                )
            raise TypeError("Module references are not first-class semantic expressions")

        receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.object_expr)
        if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
            return MethodRefExpr(
                method_id=_method_id_for_type_name(
                    lower_ctx.typecheck_ctx.module_path,
                    class_type_name_from_callable(receiver_type.name),
                    expr.field_name,
                ),
                receiver=None,
                type_name=expr_type.name,
                span=expr.span,
            )

        class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, receiver_type.name)
        if class_info is not None and expr.field_name in class_info.fields:
            field_type = qualify_member_type_for_owner(
                lower_ctx.typecheck_ctx, class_info.fields[expr.field_name], receiver_type.name
            )
            return FieldReadExpr(
                receiver=_lower_expr(lower_ctx, expr.object_expr),
                receiver_type_name=receiver_type.name,
                field_name=expr.field_name,
                field_type_name=field_type.name,
                span=expr.span,
            )

        if class_info is not None and expr.field_name in class_info.methods:
            return MethodRefExpr(
                method_id=_method_id_for_type_name(
                    lower_ctx.typecheck_ctx.module_path, receiver_type.name, expr.field_name
                ),
                receiver=_lower_expr(lower_ctx, expr.object_expr),
                type_name=expr_type.name,
                span=expr.span,
            )

        raise TypeError(f"Unsupported field access for semantic lowering: {expr.field_name}")

    if isinstance(expr, IndexExpr):
        return IndexReadExpr(
            target=_lower_expr(lower_ctx, expr.object_expr),
            index=_lower_expr(lower_ctx, expr.index_expr),
            result_type_name=expr_type.name,
            get_method=None,
            span=expr.span,
        )

    if isinstance(expr, CallExpr):
        return _lower_call_expr(lower_ctx, expr, expr_type.name)

    raise TypeError(f"Unsupported expression for semantic lowering: {type(expr).__name__}")


def _lower_call_expr(lower_ctx: _ModuleLoweringContext, expr: CallExpr, result_type_name: str) -> SemanticExpr:
    args = [_lower_expr(lower_ctx, arg) for arg in expr.arguments]

    if isinstance(expr.callee, IdentifierExpr):
        if (
            expr.callee.name in lower_ctx.typecheck_ctx.functions
            or resolve_imported_function_sig(lower_ctx.typecheck_ctx, expr.callee.name, expr.callee.span) is not None
        ):
            function_id = _function_id_for_identifier_call(lower_ctx, expr.callee.name)
            return FunctionCallExpr(function_id=function_id, args=args, type_name=result_type_name, span=expr.span)

        imported_class_name = resolve_imported_class_name(lower_ctx.typecheck_ctx, expr.callee.name, expr.callee.span)
        if expr.callee.name in lower_ctx.typecheck_ctx.classes or imported_class_name is not None:
            type_name = expr.callee.name if imported_class_name is None else imported_class_name
            return ConstructorCallExpr(
                constructor_id=_constructor_id_from_type_name(lower_ctx.typecheck_ctx.module_path, type_name),
                args=args,
                type_name=result_type_name,
                span=expr.span,
            )

    if isinstance(expr.callee, FieldAccessExpr):
        module_member = resolve_module_member(lower_ctx.typecheck_ctx, expr.callee)
        if module_member is not None:
            kind, owner_module, member_name = module_member
            if kind == "function":
                return FunctionCallExpr(
                    function_id=_function_id_for_module_member(lower_ctx, owner_module, member_name),
                    args=args,
                    type_name=result_type_name,
                    span=expr.span,
                )
            if kind == "class":
                return ConstructorCallExpr(
                    constructor_id=_constructor_id_for_module_member(owner_module, member_name),
                    args=args,
                    type_name=result_type_name,
                    span=expr.span,
                )

        receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
        if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
            return StaticMethodCallExpr(
                method_id=_method_id_for_type_name(
                    lower_ctx.typecheck_ctx.module_path,
                    class_type_name_from_callable(receiver_type.name),
                    expr.callee.field_name,
                ),
                args=args,
                type_name=result_type_name,
                span=expr.span,
            )

        class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, receiver_type.name)
        if class_info is not None and expr.callee.field_name in class_info.methods:
            return InstanceMethodCallExpr(
                method_id=_method_id_for_type_name(
                    lower_ctx.typecheck_ctx.module_path, receiver_type.name, expr.callee.field_name
                ),
                receiver=_lower_expr(lower_ctx, expr.callee.object_expr),
                receiver_type_name=receiver_type.name,
                args=args,
                type_name=result_type_name,
                span=expr.span,
            )

    infer_call_type(lower_ctx.typecheck_ctx, expr)
    raise NotImplementedError("Pass 2 semantic lowering does not yet support this callable form")


def _resolved_type_name(typecheck_ctx: TypeCheckContext, type_ref) -> str:
    return resolve_type_ref(typecheck_ctx, type_ref).name


def _function_id_for_local_name(lower_ctx: _ModuleLoweringContext, name: str):
    module_path = lower_ctx.typecheck_ctx.module_path
    assert module_path is not None
    return lower_ctx.symbol_index.local_functions_by_module[module_path][name]


def _function_id_for_imported_name(lower_ctx: _ModuleLoweringContext, name: str):
    current_module = lower_ctx.typecheck_ctx.modules[lower_ctx.typecheck_ctx.module_path]
    matches = []
    for import_info in current_module.imports.values():
        function_id = lower_ctx.symbol_index.local_functions_by_module.get(import_info.module_path, {}).get(name)
        if function_id is not None:
            matches.append(function_id)
    if len(matches) != 1:
        raise ValueError(f"Expected unique imported function '{name}'")
    return matches[0]


def _function_id_for_identifier_call(lower_ctx: _ModuleLoweringContext, name: str):
    if name in lower_ctx.typecheck_ctx.functions:
        return _function_id_for_local_name(lower_ctx, name)
    return _function_id_for_imported_name(lower_ctx, name)


def _function_id_for_module_member(lower_ctx: _ModuleLoweringContext, owner_module: ModulePath, name: str):
    return lower_ctx.symbol_index.local_functions_by_module[owner_module][name]


def _class_id_for_module_member(owner_module: ModulePath, name: str):
    return ClassId(module_path=owner_module, name=name)


def _constructor_id_for_module_member(owner_module: ModulePath, name: str):
    return _constructor_id_from_type_name(owner_module, name)


def _class_id_from_type_name(current_module_path: ModulePath | None, type_name: str):
    owner_module, class_name = _split_type_name(current_module_path, type_name)
    return _class_id_for_module_member(owner_module, class_name)


def _constructor_id_from_type_name(current_module_path: ModulePath | None, type_name: str):
    owner_module, class_name = _split_type_name(current_module_path, type_name)
    return ConstructorId(module_path=owner_module, class_name=class_name)


def _method_id_for_type_name(current_module_path: ModulePath | None, type_name: str, method_name: str):
    owner_module, class_name = _split_type_name(current_module_path, type_name)
    return MethodId(module_path=owner_module, class_name=class_name, name=method_name)


def _split_type_name(current_module_path: ModulePath | None, type_name: str) -> tuple[ModulePath, str]:
    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return tuple(owner_dotted.split(".")), class_name
    if current_module_path is None:
        raise ValueError(f"Cannot resolve unqualified type name '{type_name}' without a module path")
    return current_module_path, type_name
