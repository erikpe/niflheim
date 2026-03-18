from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import *
from compiler.codegen.strings import decode_string_literal, is_str_type_name
from compiler.resolver import ModulePath, ProgramInfo
from compiler.semantic.ir import *
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    MethodId,
    ProgramSymbolIndex,
    SyntheticId,
    build_program_symbol_index,
    class_id_for_decl,
    function_id_for_decl,
    method_id_for_decl,
)
from compiler.typecheck.bodies import check_bodies
from compiler.typecheck.call_helpers import class_type_name_from_callable
from compiler.typecheck.calls import infer_call_type
from compiler.typecheck.context import TypeCheckContext, declare_variable, lookup_variable, pop_scope, push_scope
from compiler.typecheck.constants import I64_MAX_LITERAL
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.relations import canonicalize_reference_type_name
from compiler.typecheck.structural import (
    ensure_structural_set_method_available_for_index_assignment,
    resolve_for_in_element_type,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner, resolve_type_ref


@dataclass
class _ModuleLoweringContext:
    typecheck_ctx: TypeCheckContext
    symbol_index: ProgramSymbolIndex


@dataclass(frozen=True)
class _ResolvedFunctionCallTarget:
    function_id: object


@dataclass(frozen=True)
class _ResolvedConstructorCallTarget:
    constructor_id: ConstructorId


@dataclass(frozen=True)
class _ResolvedStaticMethodCallTarget:
    method_id: MethodId


@dataclass(frozen=True)
class _ResolvedInstanceMethodCallTarget:
    method_id: MethodId
    receiver: Expression
    receiver_type_name: str


@dataclass(frozen=True)
class _ResolvedCallableValueCallTarget:
    callee: Expression


@dataclass(frozen=True)
class _ResolvedLocalRefTarget:
    name: str
    type_name: str


@dataclass(frozen=True)
class _ResolvedFunctionRefTarget:
    function_id: object


@dataclass(frozen=True)
class _ResolvedClassRefTarget:
    class_id: ClassId


@dataclass(frozen=True)
class _ResolvedMethodRefTarget:
    method_id: MethodId
    receiver: Expression | None


@dataclass(frozen=True)
class _ResolvedFieldReadTarget:
    receiver: Expression
    receiver_type_name: str
    field_name: str
    field_type_name: str


@dataclass(frozen=True)
class _ResolvedLocalLValueTarget:
    name: str
    type_name: str


@dataclass(frozen=True)
class _ResolvedFieldLValueTarget:
    receiver: Expression
    receiver_type_name: str
    field_name: str
    field_type_name: str


@dataclass(frozen=True)
class _ResolvedIndexLValueTarget:
    target: Expression
    index: Expression
    value_type_name: str


ResolvedCallTarget = (
    _ResolvedFunctionCallTarget
    | _ResolvedConstructorCallTarget
    | _ResolvedStaticMethodCallTarget
    | _ResolvedInstanceMethodCallTarget
    | _ResolvedCallableValueCallTarget
)


ResolvedRefTarget = (
    _ResolvedLocalRefTarget
    | _ResolvedFunctionRefTarget
    | _ResolvedClassRefTarget
    | _ResolvedMethodRefTarget
    | _ResolvedFieldReadTarget
)


ResolvedLValueTarget = _ResolvedLocalLValueTarget | _ResolvedFieldLValueTarget | _ResolvedIndexLValueTarget


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
            lower_ctx, params=function_decl.params, body=function_decl.body, receiver_type=None, owner_class_name=None
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
        lower_ctx,
        params=method_decl.params,
        body=method_decl.body,
        receiver_type=receiver_type,
        owner_class_name=class_decl.name,
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
    lower_ctx: _ModuleLoweringContext,
    *,
    params: list[ParamDecl],
    body: BlockStmt,
    receiver_type: TypeInfo | None,
    owner_class_name: str | None,
) -> SemanticBlock:
    typecheck_ctx = lower_ctx.typecheck_ctx
    previous_owner = typecheck_ctx.current_private_owner_type
    if owner_class_name is not None:
        typecheck_ctx.current_private_owner_type = canonicalize_reference_type_name(typecheck_ctx, owner_class_name)
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
        typecheck_ctx.current_private_owner_type = previous_owner


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
        collection_type = infer_expression_type(lower_ctx.typecheck_ctx, stmt.collection_expr)
        element_type = resolve_for_in_element_type(lower_ctx.typecheck_ctx, collection_type, stmt.span)
        push_scope(lower_ctx.typecheck_ctx)
        try:
            declare_variable(lower_ctx.typecheck_ctx, stmt.element_name, element_type, stmt.span)
            body = _lower_block(lower_ctx, stmt.body)
        finally:
            pop_scope(lower_ctx.typecheck_ctx)
        return SemanticForIn(
            element_name=stmt.element_name,
            collection=_lower_expr(lower_ctx, stmt.collection_expr),
            iter_len_method=_resolve_instance_method_id(lower_ctx, collection_type.name, "iter_len"),
            iter_get_method=_resolve_instance_method_id(lower_ctx, collection_type.name, "iter_get"),
            element_type_name=element_type.name,
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
        slice_assign = _try_lower_slice_assign_stmt(lower_ctx, stmt)
        if slice_assign is not None:
            return slice_assign
        return SemanticExprStmt(expr=_lower_expr(lower_ctx, stmt.expression), span=stmt.span)

    raise TypeError(f"Unsupported statement for semantic lowering: {type(stmt).__name__}")


def _lower_lvalue(lower_ctx: _ModuleLoweringContext, expr: Expression):
    resolved_target = _resolve_lvalue_target(lower_ctx, expr)

    if isinstance(resolved_target, _ResolvedLocalLValueTarget):
        return LocalLValue(name=resolved_target.name, type_name=resolved_target.type_name, span=expr.span)

    if isinstance(resolved_target, _ResolvedFieldLValueTarget):
        return FieldLValue(
            receiver=_lower_expr(lower_ctx, resolved_target.receiver),
            receiver_type_name=resolved_target.receiver_type_name,
            field_name=resolved_target.field_name,
            field_type_name=resolved_target.field_type_name,
            span=expr.span,
        )

    return IndexLValue(
        target=_lower_expr(lower_ctx, resolved_target.target),
        index=_lower_expr(lower_ctx, resolved_target.index),
        value_type_name=resolved_target.value_type_name,
        set_method=_resolve_index_method_id(lower_ctx, resolved_target.target, "index_set"),
        span=expr.span,
    )


def _resolve_lvalue_target(lower_ctx: _ModuleLoweringContext, expr: Expression) -> ResolvedLValueTarget:
    if isinstance(expr, IdentifierExpr):
        local_type = lookup_variable(lower_ctx.typecheck_ctx, expr.name)
        if local_type is None:
            raise ValueError(f"Unknown local assignment target '{expr.name}'")
        return _ResolvedLocalLValueTarget(name=expr.name, type_name=local_type.name)

    if isinstance(expr, FieldAccessExpr):
        return _ResolvedFieldLValueTarget(
            receiver=expr.object_expr,
            receiver_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr.object_expr).name,
            field_name=expr.field_name,
            field_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
        )

    if isinstance(expr, IndexExpr):
        return _ResolvedIndexLValueTarget(
            target=expr.object_expr,
            index=expr.index_expr,
            value_type_name=_resolve_index_assignment_value_type_name(lower_ctx, expr),
        )

    raise TypeError(f"Unsupported lvalue for semantic lowering: {type(expr).__name__}")


def _lower_expr(lower_ctx: _ModuleLoweringContext, expr: Expression) -> SemanticExpr:
    if isinstance(expr, IdentifierExpr):
        return _lower_resolved_ref(
            lower_ctx,
            _resolve_identifier_ref_target(lower_ctx, expr),
            infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            expr.span,
        )

    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            return _lower_string_literal_expr(
                lower_ctx, expr, infer_expression_type(lower_ctx.typecheck_ctx, expr).name
            )
        return LiteralExprS(value=expr.value, type_name=_literal_type_name(expr), span=expr.span)

    if isinstance(expr, NullExpr):
        return NullExprS(span=expr.span)

    if isinstance(expr, UnaryExpr):
        return UnaryExprS(
            operator=expr.operator,
            operand=_lower_expr(lower_ctx, expr.operand),
            type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            span=expr.span,
        )

    if isinstance(expr, BinaryExpr):
        result_type_name = infer_expression_type(lower_ctx.typecheck_ctx, expr).name
        string_concat = _try_lower_string_concat_expr(lower_ctx, expr, result_type_name)
        if string_concat is not None:
            return string_concat
        return BinaryExprS(
            operator=expr.operator,
            left=_lower_expr(lower_ctx, expr.left),
            right=_lower_expr(lower_ctx, expr.right),
            type_name=result_type_name,
            span=expr.span,
        )

    if isinstance(expr, CastExpr):
        return CastExprS(
            operand=_lower_expr(lower_ctx, expr.operand),
            target_type_name=_resolved_type_name(lower_ctx.typecheck_ctx, expr.type_ref),
            type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
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
        return _lower_resolved_ref(
            lower_ctx,
            _resolve_field_access_ref_target(lower_ctx, expr),
            infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            expr.span,
        )

    if isinstance(expr, IndexExpr):
        return IndexReadExpr(
            target=_lower_expr(lower_ctx, expr.object_expr),
            index=_lower_expr(lower_ctx, expr.index_expr),
            result_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr).name,
            get_method=_resolve_index_method_id(lower_ctx, expr.object_expr, "index_get"),
            span=expr.span,
        )

    if isinstance(expr, CallExpr):
        return _lower_call_expr(lower_ctx, expr, infer_expression_type(lower_ctx.typecheck_ctx, expr).name)

    raise TypeError(f"Unsupported expression for semantic lowering: {type(expr).__name__}")


def _lower_call_expr(lower_ctx: _ModuleLoweringContext, expr: CallExpr, result_type_name: str) -> SemanticExpr:
    array_structural_expr = _try_lower_array_structural_call_expr(lower_ctx, expr, result_type_name)
    if array_structural_expr is not None:
        return array_structural_expr

    slice_read = _try_lower_slice_read_expr(lower_ctx, expr, result_type_name)
    if slice_read is not None:
        return slice_read

    resolved_target = _resolve_call_target(lower_ctx, expr)
    args = [_lower_expr(lower_ctx, arg) for arg in expr.arguments]

    if isinstance(resolved_target, _ResolvedFunctionCallTarget):
        return FunctionCallExpr(
            function_id=resolved_target.function_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, _ResolvedConstructorCallTarget):
        return ConstructorCallExpr(
            constructor_id=resolved_target.constructor_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, _ResolvedStaticMethodCallTarget):
        return StaticMethodCallExpr(
            method_id=resolved_target.method_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, _ResolvedInstanceMethodCallTarget):
        return InstanceMethodCallExpr(
            method_id=resolved_target.method_id,
            receiver=_lower_expr(lower_ctx, resolved_target.receiver),
            receiver_type_name=resolved_target.receiver_type_name,
            args=args,
            type_name=result_type_name,
            span=expr.span,
        )

    return CallableValueCallExpr(
        callee=_lower_expr(lower_ctx, resolved_target.callee), args=args, type_name=result_type_name, span=expr.span
    )


def _try_lower_array_structural_call_expr(
    lower_ctx: _ModuleLoweringContext, expr: CallExpr, result_type_name: str
) -> SemanticExpr | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    if expr.callee.field_name in {"len", "iter_len"}:
        if expr.arguments:
            return None
        return ArrayLenExpr(target=_lower_expr(lower_ctx, expr.callee.object_expr), span=expr.span)

    if expr.callee.field_name in {"index_get", "iter_get"}:
        if len(expr.arguments) != 1:
            return None
        return IndexReadExpr(
            target=_lower_expr(lower_ctx, expr.callee.object_expr),
            index=_lower_expr(lower_ctx, expr.arguments[0]),
            result_type_name=result_type_name,
            get_method=None,
            span=expr.span,
        )

    if expr.callee.field_name == "slice_get":
        if len(expr.arguments) != 2:
            return None
        return SliceReadExpr(
            target=_lower_expr(lower_ctx, expr.callee.object_expr),
            begin=_lower_expr(lower_ctx, expr.arguments[0]),
            end=_lower_expr(lower_ctx, expr.arguments[1]),
            result_type_name=result_type_name,
            get_method=None,
            span=expr.span,
        )

    return None


def _try_lower_slice_assign_stmt(lower_ctx: _ModuleLoweringContext, stmt: ExprStmt) -> SemanticAssign | None:
    array_index_assign = _try_lower_array_index_assign_stmt(lower_ctx, stmt)
    if array_index_assign is not None:
        return array_index_assign

    array_slice_assign = _try_lower_array_slice_assign_stmt(lower_ctx, stmt)
    if array_slice_assign is not None:
        return array_slice_assign

    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if expr.callee.field_name != "slice_set" or len(expr.arguments) != 3:
        return None

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    return SemanticAssign(
        target=SliceLValue(
            target=_lower_expr(lower_ctx, expr.callee.object_expr),
            begin=_lower_expr(lower_ctx, expr.arguments[0]),
            end=_lower_expr(lower_ctx, expr.arguments[1]),
            value_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr.arguments[2]).name,
            set_method=_resolve_instance_method_id(lower_ctx, receiver_type.name, "slice_set"),
            span=expr.span,
        ),
        value=_lower_expr(lower_ctx, expr.arguments[2]),
        span=stmt.span,
    )


def _try_lower_array_index_assign_stmt(lower_ctx: _ModuleLoweringContext, stmt: ExprStmt) -> SemanticAssign | None:
    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if expr.callee.field_name != "index_set" or len(expr.arguments) != 2:
        return None

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    return SemanticAssign(
        target=IndexLValue(
            target=_lower_expr(lower_ctx, expr.callee.object_expr),
            index=_lower_expr(lower_ctx, expr.arguments[0]),
            value_type_name=receiver_type.element_type.name,
            set_method=None,
            span=expr.span,
        ),
        value=_lower_expr(lower_ctx, expr.arguments[1]),
        span=stmt.span,
    )


def _try_lower_array_slice_assign_stmt(lower_ctx: _ModuleLoweringContext, stmt: ExprStmt) -> SemanticAssign | None:
    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if expr.callee.field_name != "slice_set" or len(expr.arguments) != 3:
        return None

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    return SemanticAssign(
        target=SliceLValue(
            target=_lower_expr(lower_ctx, expr.callee.object_expr),
            begin=_lower_expr(lower_ctx, expr.arguments[0]),
            end=_lower_expr(lower_ctx, expr.arguments[1]),
            value_type_name=infer_expression_type(lower_ctx.typecheck_ctx, expr.arguments[2]).name,
            set_method=None,
            span=expr.span,
        ),
        value=_lower_expr(lower_ctx, expr.arguments[2]),
        span=stmt.span,
    )


def _try_lower_slice_read_expr(
    lower_ctx: _ModuleLoweringContext, expr: CallExpr, result_type_name: str
) -> SliceReadExpr | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if expr.callee.field_name != "slice_get" or len(expr.arguments) != 2:
        return None

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    return SliceReadExpr(
        target=_lower_expr(lower_ctx, expr.callee.object_expr),
        begin=_lower_expr(lower_ctx, expr.arguments[0]),
        end=_lower_expr(lower_ctx, expr.arguments[1]),
        result_type_name=result_type_name,
        get_method=_resolve_instance_method_id(lower_ctx, receiver_type.name, "slice_get"),
        span=expr.span,
    )


def _lower_string_literal_expr(
    lower_ctx: _ModuleLoweringContext, expr: LiteralExpr, result_type_name: str
) -> StaticMethodCallExpr:
    decode_string_literal(expr.value)
    return StaticMethodCallExpr(
        method_id=_resolve_static_method_id(lower_ctx, result_type_name, "from_u8_array"),
        args=[
            SyntheticExpr(
                synthetic_id=SyntheticId(kind="string_literal_bytes", owner=result_type_name, name=expr.value),
                args=[],
                type_name="u8[]",
                span=expr.span,
            )
        ],
        type_name=result_type_name,
        span=expr.span,
    )


def _try_lower_string_concat_expr(
    lower_ctx: _ModuleLoweringContext, expr: BinaryExpr, result_type_name: str
) -> StaticMethodCallExpr | None:
    left_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.left)
    right_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.right)
    if expr.operator != "+" or not is_str_type_name(left_type.name) or not is_str_type_name(right_type.name):
        return None

    return StaticMethodCallExpr(
        method_id=_resolve_static_method_id(lower_ctx, result_type_name, "concat"),
        args=[_lower_expr(lower_ctx, expr.left), _lower_expr(lower_ctx, expr.right)],
        type_name=result_type_name,
        span=expr.span,
    )


def _resolve_call_target(lower_ctx: _ModuleLoweringContext, expr: CallExpr) -> ResolvedCallTarget:
    identifier_target = _resolve_identifier_call_target(lower_ctx, expr)
    if identifier_target is not None:
        return identifier_target

    field_access_target = _resolve_field_access_call_target(lower_ctx, expr)
    if field_access_target is not None:
        return field_access_target

    infer_call_type(lower_ctx.typecheck_ctx, expr)
    return _ResolvedCallableValueCallTarget(callee=expr.callee)


def _resolve_identifier_ref_target(lower_ctx: _ModuleLoweringContext, expr: IdentifierExpr) -> ResolvedRefTarget:
    local_type = lookup_variable(lower_ctx.typecheck_ctx, expr.name)
    if local_type is not None:
        return _ResolvedLocalRefTarget(name=expr.name, type_name=local_type.name)

    if expr.name in lower_ctx.typecheck_ctx.functions:
        return _ResolvedFunctionRefTarget(function_id=_function_id_for_local_name(lower_ctx, expr.name))

    if resolve_imported_function_sig(lower_ctx.typecheck_ctx, expr.name, expr.span) is not None:
        return _ResolvedFunctionRefTarget(function_id=_function_id_for_imported_name(lower_ctx, expr.name))

    imported_class_name = resolve_imported_class_name(lower_ctx.typecheck_ctx, expr.name, expr.span)
    if expr.name in lower_ctx.typecheck_ctx.classes or imported_class_name is not None:
        type_name = expr.name if imported_class_name is None else imported_class_name
        return _ResolvedClassRefTarget(
            class_id=_class_id_from_type_name(lower_ctx.typecheck_ctx.module_path, type_name)
        )

    raise TypeError(f"Unsupported identifier expression for semantic lowering: {expr.name}")


def _resolve_field_access_ref_target(lower_ctx: _ModuleLoweringContext, expr: FieldAccessExpr) -> ResolvedRefTarget:
    module_member = resolve_module_member(lower_ctx.typecheck_ctx, expr)
    if module_member is not None:
        kind, owner_module, member_name = module_member
        if kind == "function":
            return _ResolvedFunctionRefTarget(
                function_id=_function_id_for_module_member(lower_ctx, owner_module, member_name)
            )
        if kind == "class":
            return _ResolvedClassRefTarget(class_id=_class_id_for_module_member(owner_module, member_name))
        raise TypeError("Module references are not first-class semantic expressions")

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.object_expr)
    if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
        return _ResolvedMethodRefTarget(
            method_id=_method_id_for_type_name(
                lower_ctx.typecheck_ctx.module_path, class_type_name_from_callable(receiver_type.name), expr.field_name
            ),
            receiver=None,
        )

    class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, receiver_type.name)
    if class_info is None:
        raise TypeError(f"Unsupported field access for semantic lowering: {expr.field_name}")

    if expr.field_name in class_info.fields:
        field_type = qualify_member_type_for_owner(
            lower_ctx.typecheck_ctx, class_info.fields[expr.field_name], receiver_type.name
        )
        return _ResolvedFieldReadTarget(
            receiver=expr.object_expr,
            receiver_type_name=receiver_type.name,
            field_name=expr.field_name,
            field_type_name=field_type.name,
        )

    if expr.field_name in class_info.methods:
        return _ResolvedMethodRefTarget(
            method_id=_method_id_for_type_name(
                lower_ctx.typecheck_ctx.module_path, receiver_type.name, expr.field_name
            ),
            receiver=expr.object_expr,
        )

    raise TypeError(f"Unsupported field access for semantic lowering: {expr.field_name}")


def _lower_resolved_ref(
    lower_ctx: _ModuleLoweringContext, resolved_target: ResolvedRefTarget, type_name: str, span
) -> SemanticExpr:
    if isinstance(resolved_target, _ResolvedLocalRefTarget):
        return LocalRefExpr(name=resolved_target.name, type_name=resolved_target.type_name, span=span)

    if isinstance(resolved_target, _ResolvedFunctionRefTarget):
        return FunctionRefExpr(function_id=resolved_target.function_id, type_name=type_name, span=span)

    if isinstance(resolved_target, _ResolvedClassRefTarget):
        return ClassRefExpr(class_id=resolved_target.class_id, type_name=type_name, span=span)

    if isinstance(resolved_target, _ResolvedMethodRefTarget):
        receiver = None if resolved_target.receiver is None else _lower_expr(lower_ctx, resolved_target.receiver)
        return MethodRefExpr(method_id=resolved_target.method_id, receiver=receiver, type_name=type_name, span=span)

    return FieldReadExpr(
        receiver=_lower_expr(lower_ctx, resolved_target.receiver),
        receiver_type_name=resolved_target.receiver_type_name,
        field_name=resolved_target.field_name,
        field_type_name=resolved_target.field_type_name,
        span=span,
    )


def _resolve_identifier_call_target(lower_ctx: _ModuleLoweringContext, expr: CallExpr) -> ResolvedCallTarget | None:
    if not isinstance(expr.callee, IdentifierExpr):
        return None

    name = expr.callee.name
    if name in lower_ctx.typecheck_ctx.functions:
        return _ResolvedFunctionCallTarget(function_id=_function_id_for_local_name(lower_ctx, name))

    imported_function = resolve_imported_function_sig(lower_ctx.typecheck_ctx, name, expr.callee.span)
    if imported_function is not None:
        return _ResolvedFunctionCallTarget(function_id=_function_id_for_imported_name(lower_ctx, name))

    imported_class_name = resolve_imported_class_name(lower_ctx.typecheck_ctx, name, expr.callee.span)
    if name in lower_ctx.typecheck_ctx.classes or imported_class_name is not None:
        type_name = name if imported_class_name is None else imported_class_name
        return _ResolvedConstructorCallTarget(
            constructor_id=_constructor_id_from_type_name(lower_ctx.typecheck_ctx.module_path, type_name)
        )

    return None


def _resolve_field_access_call_target(lower_ctx: _ModuleLoweringContext, expr: CallExpr) -> ResolvedCallTarget | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    module_member_target = _resolve_module_member_call_target(lower_ctx, expr.callee)
    if module_member_target is not None:
        return module_member_target

    receiver_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.callee.object_expr)
    if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
        return _ResolvedStaticMethodCallTarget(
            method_id=_method_id_for_type_name(
                lower_ctx.typecheck_ctx.module_path,
                class_type_name_from_callable(receiver_type.name),
                expr.callee.field_name,
            )
        )

    class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, receiver_type.name)
    if class_info is not None and expr.callee.field_name in class_info.methods:
        return _ResolvedInstanceMethodCallTarget(
            method_id=_method_id_for_type_name(
                lower_ctx.typecheck_ctx.module_path, receiver_type.name, expr.callee.field_name
            ),
            receiver=expr.callee.object_expr,
            receiver_type_name=receiver_type.name,
        )

    return None


def _resolve_module_member_call_target(
    lower_ctx: _ModuleLoweringContext, callee: FieldAccessExpr
) -> ResolvedCallTarget | None:
    module_member = resolve_module_member(lower_ctx.typecheck_ctx, callee)
    if module_member is None:
        return None

    kind, owner_module, member_name = module_member
    if kind == "function":
        return _ResolvedFunctionCallTarget(
            function_id=_function_id_for_module_member(lower_ctx, owner_module, member_name)
        )
    if kind == "class":
        return _ResolvedConstructorCallTarget(
            constructor_id=_constructor_id_for_module_member(owner_module, member_name)
        )
    return None


def _resolved_type_name(typecheck_ctx: TypeCheckContext, type_ref) -> str:
    return resolve_type_ref(typecheck_ctx, type_ref).name


def _literal_type_name(expr: LiteralExpr) -> str:
    if expr.value in {"true", "false"}:
        return "bool"
    if expr.value.startswith("'"):
        return "u8"
    if "." in expr.value:
        return "double"
    if expr.value.endswith("u8") and expr.value[:-2].isdigit():
        return "u8"
    if expr.value.endswith("u") and expr.value[:-1].isdigit():
        return "u64"
    if expr.value.isdigit():
        if int(expr.value) > I64_MAX_LITERAL:
            return "i64"
        return "i64"
    raise ValueError(f"Unsupported literal syntax for semantic lowering: {expr.value}")


def _resolve_index_assignment_value_type_name(lower_ctx: _ModuleLoweringContext, expr: IndexExpr) -> str:
    object_type = infer_expression_type(lower_ctx.typecheck_ctx, expr.object_expr)
    if object_type.element_type is not None:
        return object_type.element_type.name

    method_sig = ensure_structural_set_method_available_for_index_assignment(
        lower_ctx.typecheck_ctx, object_type, expr.span
    )
    return qualify_member_type_for_owner(lower_ctx.typecheck_ctx, method_sig.params[1], object_type.name).name


def _resolve_index_method_id(
    lower_ctx: _ModuleLoweringContext, target_expr: Expression, method_name: str
) -> MethodId | None:
    return _resolve_instance_method_id(
        lower_ctx, infer_expression_type(lower_ctx.typecheck_ctx, target_expr).name, method_name
    )


def _resolve_instance_method_id(
    lower_ctx: _ModuleLoweringContext, receiver_type_name: str, method_name: str
) -> MethodId | None:
    if receiver_type_name.endswith("[]"):
        return None

    class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, receiver_type_name)
    if class_info is None:
        raise ValueError(f"Cannot resolve structural method '{method_name}' on non-class type '{receiver_type_name}'")

    method_sig = class_info.methods.get(method_name)
    if method_sig is None:
        raise ValueError(f"Missing instance method '{method_name}' on type '{receiver_type_name}'")
    if method_sig.is_static:
        raise ValueError(f"Expected instance method '{method_name}' on type '{receiver_type_name}'")
    return _method_id_for_type_name(lower_ctx.typecheck_ctx.module_path, receiver_type_name, method_name)


def _resolve_static_method_id(lower_ctx: _ModuleLoweringContext, owner_type_name: str, method_name: str) -> MethodId:
    class_info = lookup_class_by_type_name(lower_ctx.typecheck_ctx, owner_type_name)
    if class_info is None:
        raise ValueError(f"Cannot resolve static method '{method_name}' on non-class type '{owner_type_name}'")

    method_sig = class_info.methods.get(method_name)
    if method_sig is None:
        raise ValueError(f"Missing static method '{method_name}' on type '{owner_type_name}'")
    if not method_sig.is_static:
        raise ValueError(f"Expected static method '{method_name}' on type '{owner_type_name}'")
    return _method_id_for_type_name(lower_ctx.typecheck_ctx.module_path, owner_type_name, method_name)


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
