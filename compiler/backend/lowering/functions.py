"""Callable lowering helpers for the phase-2 backend lowerer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from compiler.backend.ir import model as ir_model
from compiler.backend.lowering.expressions import (
    backend_signature_return_type,
    lower_literal_expression_to_operand,
    lower_null_operand,
    lower_unit_operand,
)
from compiler.common.span import SourceSpan
from compiler.semantic.ir import (
    BinaryExprS,
    CallExprS,
    CallableValueCallTarget,
    ClassRefExpr,
    FunctionCallTarget,
    FunctionRefExpr,
    LocalRefExpr,
    LocalLValue,
    MethodRefExpr,
    NullExprS,
    SemanticAssign,
    SemanticBlock,
    SemanticConstructor,
    SemanticExprStmt,
    SemanticExpr,
    SemanticField,
    SemanticFunction,
    SemanticFunctionLike,
    SemanticIf,
    SemanticLocalInfo,
    SemanticMethod,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    StaticMethodCallTarget,
    UnaryExprS,
)
from compiler.semantic.linker import LinkedSemanticProgram
from compiler.semantic.symbols import ClassId, ConstructorId, LocalId, MethodId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_callable_params,
    semantic_type_callable_return,
    semantic_type_canonical_name,
    semantic_type_is_callable,
    semantic_type_ref_for_class_id,
)


@dataclass(frozen=True)
class LoweredCallable:
    callable_decl: ir_model.BackendCallableDecl
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId]


@dataclass
class _RegisterLayout:
    registers: list[ir_model.BackendRegister]
    param_regs: list[ir_model.BackendRegId]
    receiver_reg: ir_model.BackendRegId | None
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId]
    next_ordinal: int


@dataclass(frozen=True)
class CallableSurface:
    signature: ir_model.BackendSignature
    expects_receiver: bool


@dataclass
class _CallableBodyBuilder:
    callable_id: ir_model.BackendCallableId
    kind: ir_model.BackendCallableKind
    signature: ir_model.BackendSignature
    receiver_reg: ir_model.BackendRegId | None
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId]
    registers: list[ir_model.BackendRegister]
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister]
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface]
    block_span: SourceSpan
    instructions: list[ir_model.BackendInstruction]
    next_reg_ordinal: int
    next_inst_ordinal: int = 0
    next_temp_index: int = 0
    terminator: ir_model.BackendTerminator | None = None

    def emit_const(self, *, dest: ir_model.BackendRegId, constant: ir_model.BackendConstant, span: SourceSpan) -> None:
        self.instructions.append(
            ir_model.BackendConstInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                constant=constant,
                span=span,
            )
        )

    def emit_copy(self, *, dest: ir_model.BackendRegId, source: ir_model.BackendOperand, span: SourceSpan) -> None:
        self.instructions.append(
            ir_model.BackendCopyInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                source=source,
                span=span,
            )
        )

    def emit_unary(
        self,
        *,
        dest: ir_model.BackendRegId,
        op,
        operand: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self.instructions.append(
            ir_model.BackendUnaryInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                op=op,
                operand=operand,
                span=span,
            )
        )

    def emit_binary(
        self,
        *,
        dest: ir_model.BackendRegId,
        op,
        left: ir_model.BackendOperand,
        right: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self.instructions.append(
            ir_model.BackendBinaryInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                op=op,
                left=left,
                right=right,
                span=span,
            )
        )

    def emit_call(
        self,
        *,
        dest: ir_model.BackendRegId | None,
        target: ir_model.BackendCallTarget,
        args: tuple[ir_model.BackendOperand, ...],
        signature: ir_model.BackendSignature,
        span: SourceSpan,
    ) -> None:
        self.instructions.append(
            ir_model.BackendCallInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                target=target,
                args=args,
                signature=signature,
                effects=_conservative_user_call_effects(),
                span=span,
            )
        )

    def allocate_temp(self, *, type_ref: SemanticTypeRef, span: SourceSpan, debug_hint: str = "tmp") -> ir_model.BackendRegId:
        reg_id = ir_model.BackendRegId(owner_id=self.callable_id, ordinal=self.next_reg_ordinal)
        self.next_reg_ordinal += 1
        debug_name = f"{debug_hint}{self.next_temp_index}"
        self.next_temp_index += 1
        register = ir_model.BackendRegister(
            reg_id=reg_id,
            type_ref=type_ref,
            debug_name=debug_name,
            origin_kind="temp",
            semantic_local_id=None,
            span=span,
        )
        self.registers.append(register)
        self.register_by_id[reg_id] = register
        return reg_id

    def require_register_type(self, reg_id: ir_model.BackendRegId) -> SemanticTypeRef:
        register = self.register_by_id.get(reg_id)
        if register is None:
            raise KeyError(f"Missing backend register metadata for {reg_id}")
        return register.type_ref

    def require_callable_surface(self, callable_id: ir_model.BackendCallableId) -> CallableSurface:
        surface = self.call_surface_by_id.get(callable_id)
        if surface is None:
            raise KeyError(f"Missing backend callable surface for {callable_id}")
        return surface

    def _next_inst_id(self) -> ir_model.BackendInstId:
        inst_id = ir_model.BackendInstId(owner_id=self.callable_id, ordinal=self.next_inst_ordinal)
        self.next_inst_ordinal += 1
        return inst_id


def build_callable_surface_by_id(program: LinkedSemanticProgram) -> dict[ir_model.BackendCallableId, CallableSurface]:
    call_surface_by_id: dict[ir_model.BackendCallableId, CallableSurface] = {}

    for function in program.functions:
        call_surface_by_id[function.function_id] = CallableSurface(
            signature=_function_signature(function),
            expects_receiver=False,
        )

    for class_decl in program.classes:
        for method in class_decl.methods:
            call_surface_by_id[method.method_id] = CallableSurface(
                signature=_method_signature(method),
                expects_receiver=not method.is_static,
            )
        for constructor in class_decl.constructors:
            call_surface_by_id[constructor.constructor_id] = CallableSurface(
                signature=_constructor_signature(class_decl.class_id, constructor),
                expects_receiver=True,
            )

    return call_surface_by_id


def lower_function_callable(
    function: SemanticFunction,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
) -> LoweredCallable:
    signature = _function_signature(function)
    layout = _allocate_register_layout(
        callable_id=function.function_id,
        params=function.params,
        local_info_by_id=function.local_info_by_id,
        receiver_type_ref=None,
    )
    return LoweredCallable(
        callable_decl=_lower_callable_decl(
            owner=function,
            callable_id=function.function_id,
            kind="function",
            signature=signature,
            is_export=function.is_export,
            is_extern=function.is_extern,
            is_static=None,
            is_private=None,
            body=function.body,
            layout=layout,
            call_surface_by_id=call_surface_by_id,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_method_callable(
    owner_class_id: ClassId,
    method: SemanticMethod,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
) -> LoweredCallable:
    signature = _method_signature(method)
    receiver_type_ref = None if method.is_static else semantic_type_ref_for_class_id(owner_class_id)
    layout = _allocate_register_layout(
        callable_id=method.method_id,
        params=method.params,
        local_info_by_id=method.local_info_by_id,
        receiver_type_ref=receiver_type_ref,
    )
    return LoweredCallable(
        callable_decl=_lower_callable_decl(
            owner=method,
            callable_id=method.method_id,
            kind="method",
            signature=signature,
            is_export=False,
            is_extern=False,
            is_static=method.is_static,
            is_private=method.is_private,
            body=method.body,
            layout=layout,
            call_surface_by_id=call_surface_by_id,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_constructor_callable(
    owner_class_id: ClassId,
    constructor: SemanticConstructor,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
) -> LoweredCallable:
    receiver_type_ref = semantic_type_ref_for_class_id(owner_class_id)
    signature = _constructor_signature(owner_class_id, constructor)
    layout = _allocate_register_layout(
        callable_id=constructor.constructor_id,
        params=constructor.params,
        local_info_by_id=constructor.local_info_by_id,
        receiver_type_ref=receiver_type_ref,
    )
    body = constructor.body
    return LoweredCallable(
        callable_decl=_lower_callable_decl(
            owner=constructor,
            callable_id=constructor.constructor_id,
            kind="constructor",
            signature=signature,
            is_export=False,
            is_extern=False,
            is_static=False,
            is_private=constructor.is_private,
            body=body,
            layout=layout,
            call_surface_by_id=call_surface_by_id,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_field_decl(owner_class_id: ClassId, field: SemanticField) -> ir_model.BackendFieldDecl:
    return ir_model.BackendFieldDecl(
        owner_class_id=owner_class_id,
        name=field.name,
        type_ref=field.type_ref,
        is_private=field.is_private,
        is_final=field.is_final,
    )


def _allocate_register_layout(
    *,
    callable_id: ir_model.BackendCallableId,
    params,
    local_info_by_id: dict[LocalId, SemanticLocalInfo],
    receiver_type_ref: SemanticTypeRef | None,
) -> _RegisterLayout:
    ordered_local_infos = sorted(local_info_by_id.values(), key=lambda local_info: local_info.local_id.ordinal)
    receiver_info = next((info for info in ordered_local_infos if info.binding_kind == "receiver"), None)
    param_infos = [info for info in ordered_local_infos if info.binding_kind == "param"]
    other_local_infos = [info for info in ordered_local_infos if info.binding_kind not in {"receiver", "param"}]

    registers: list[ir_model.BackendRegister] = []
    param_regs: list[ir_model.BackendRegId] = []
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId] = {}
    next_ordinal = 0

    receiver_reg = None
    if receiver_type_ref is not None:
        receiver_reg = ir_model.BackendRegId(owner_id=callable_id, ordinal=next_ordinal)
        next_ordinal += 1
        registers.append(
            ir_model.BackendRegister(
                reg_id=receiver_reg,
                type_ref=receiver_info.type_ref if receiver_info is not None else receiver_type_ref,
                debug_name=receiver_info.display_name if receiver_info is not None else "__self",
                origin_kind="receiver",
                semantic_local_id=None if receiver_info is None else receiver_info.local_id,
                span=None if receiver_info is None else receiver_info.span,
            )
        )
        if receiver_info is not None:
            reg_id_by_local_id[receiver_info.local_id] = receiver_reg

    for index, param in enumerate(params):
        param_info = param_infos[index] if index < len(param_infos) else None
        reg_id = ir_model.BackendRegId(owner_id=callable_id, ordinal=next_ordinal)
        next_ordinal += 1
        registers.append(
            ir_model.BackendRegister(
                reg_id=reg_id,
                type_ref=param.type_ref if param_info is None else param_info.type_ref,
                debug_name=param.name if param_info is None else param_info.display_name,
                origin_kind="param",
                semantic_local_id=None if param_info is None else param_info.local_id,
                span=param.span if param_info is None else param_info.span,
            )
        )
        if param_info is not None:
            reg_id_by_local_id[param_info.local_id] = reg_id
        param_regs.append(reg_id)

    for local_info in other_local_infos:
        reg_id = ir_model.BackendRegId(owner_id=callable_id, ordinal=next_ordinal)
        next_ordinal += 1
        origin_kind = "local" if local_info.binding_kind == "local" else "helper"
        registers.append(
            ir_model.BackendRegister(
                reg_id=reg_id,
                type_ref=local_info.type_ref,
                debug_name=local_info.display_name,
                origin_kind=origin_kind,
                semantic_local_id=local_info.local_id,
                span=local_info.span,
            )
        )
        reg_id_by_local_id[local_info.local_id] = reg_id

    return _RegisterLayout(
        registers=registers,
        param_regs=param_regs,
        receiver_reg=receiver_reg,
        reg_id_by_local_id=reg_id_by_local_id,
        next_ordinal=next_ordinal,
    )


def _lower_callable_decl(
    *,
    owner: SemanticFunctionLike,
    callable_id: ir_model.BackendCallableId,
    kind: ir_model.BackendCallableKind,
    signature: ir_model.BackendSignature,
    is_export: bool,
    is_extern: bool,
    is_static: bool | None,
    is_private: bool | None,
    body: SemanticBlock | None,
    layout: _RegisterLayout,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
) -> ir_model.BackendCallableDecl:
    if is_extern:
        return ir_model.BackendCallableDecl(
            callable_id=callable_id,
            kind=kind,
            signature=signature,
            is_export=is_export,
            is_extern=True,
            is_static=is_static,
            is_private=is_private,
            registers=tuple(layout.registers),
            param_regs=tuple(layout.param_regs),
            receiver_reg=layout.receiver_reg,
            entry_block_id=None,
            blocks=(),
            span=owner.span,
        )

    entry_block_id = ir_model.BackendBlockId(owner_id=callable_id, ordinal=0)
    block_span = owner.span if body is None else body.span
    builder = _CallableBodyBuilder(
        callable_id=callable_id,
        kind=kind,
        signature=signature,
        receiver_reg=layout.receiver_reg,
        reg_id_by_local_id=layout.reg_id_by_local_id,
        registers=list(layout.registers),
        register_by_id={register.reg_id: register for register in layout.registers},
        call_surface_by_id=call_surface_by_id,
        block_span=block_span,
        instructions=[],
        next_reg_ordinal=layout.next_ordinal,
    )

    if body is not None:
        _lower_straight_line_block(builder, body)

    if builder.terminator is None:
        if kind == "constructor":
            assert layout.receiver_reg is not None
            builder.terminator = ir_model.BackendReturnTerminator(
                span=block_span,
                value=ir_model.BackendRegOperand(reg_id=layout.receiver_reg),
            )
        elif signature.return_type is None:
            builder.terminator = ir_model.BackendReturnTerminator(span=block_span, value=None)
        else:
            raise NotImplementedError(
                f"Backend lowering smoke path requires an explicit return for callable '{callable_id}'"
            )

    block = ir_model.BackendBlock(
        block_id=entry_block_id,
        debug_name="entry",
        instructions=tuple(builder.instructions),
        terminator=builder.terminator,
        span=block_span,
    )
    return ir_model.BackendCallableDecl(
        callable_id=callable_id,
        kind=kind,
        signature=signature,
        is_export=is_export,
        is_extern=False,
        is_static=is_static,
        is_private=is_private,
        registers=tuple(builder.registers),
        param_regs=tuple(layout.param_regs),
        receiver_reg=layout.receiver_reg,
        entry_block_id=entry_block_id,
        blocks=(block,),
        span=owner.span,
    )


def _lower_straight_line_block(builder: _CallableBodyBuilder, block: SemanticBlock) -> None:
    for statement in block.statements:
        if builder.terminator is not None:
            raise NotImplementedError("Backend lowering does not support statements after return yet")
        _lower_straight_line_stmt(builder, statement)


def _lower_straight_line_stmt(builder: _CallableBodyBuilder, stmt: SemanticStmt) -> None:
    if isinstance(stmt, SemanticBlock):
        _lower_straight_line_block(builder, stmt)
        return
    if isinstance(stmt, SemanticVarDecl):
        if stmt.initializer is None:
            return
        dest_reg_id = _require_local_reg(builder, stmt.local_id)
        _materialize_expr_into(builder, dest_reg_id=dest_reg_id, expr=stmt.initializer, span=stmt.span)
        return
    if isinstance(stmt, SemanticAssign):
        if not isinstance(stmt.target, LocalLValue):
            raise NotImplementedError(
                f"Backend lowering does not support assignment target '{type(stmt.target).__name__}' yet"
            )
        dest_reg_id = _require_local_reg(builder, stmt.target.local_id)
        _materialize_expr_into(builder, dest_reg_id=dest_reg_id, expr=stmt.value, span=stmt.span)
        return
    if isinstance(stmt, SemanticExprStmt):
        _lower_expression_statement(builder, stmt.expr, stmt.span)
        return
    if isinstance(stmt, SemanticReturn):
        _lower_return_stmt(builder, stmt)
        return
    if isinstance(stmt, (SemanticIf, SemanticWhile)):
        raise NotImplementedError(
            f"Backend lowering does not support statement '{type(stmt).__name__}' yet"
        )
    raise NotImplementedError(
        f"Backend lowering does not support statement '{type(stmt).__name__}' yet"
    )


def _lower_expression_statement(builder: _CallableBodyBuilder, expr: SemanticExpr, span: SourceSpan) -> None:
    if _is_unit_typed(expr.type_ref):
        _lower_expression_to_operand(builder, expr)
        return
    if isinstance(expr, (LocalRefExpr, NullExprS)):
        _lower_expression_to_operand(builder, expr)
        return
    if hasattr(expr, "constant"):
        _lower_expression_to_operand(builder, expr)
        return
    discard_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=span, debug_hint="discard")
    _materialize_expr_into(builder, dest_reg_id=discard_reg_id, expr=expr, span=span)


def _materialize_expr_into(
    builder: _CallableBodyBuilder,
    *,
    dest_reg_id: ir_model.BackendRegId,
    expr,
    span: SourceSpan,
) -> None:
    if isinstance(expr, UnaryExprS):
        operand = _lower_expression_to_operand(builder, expr.operand)
        builder.emit_unary(dest=dest_reg_id, op=expr.op, operand=operand, span=expr.span)
        return
    if isinstance(expr, BinaryExprS):
        left = _lower_expression_to_operand(builder, expr.left)
        right = _lower_expression_to_operand(builder, expr.right)
        builder.emit_binary(dest=dest_reg_id, op=expr.op, left=left, right=right, span=expr.span)
        return
    if isinstance(expr, CallExprS):
        _emit_call_expression(builder, expr=expr, dest_reg_id=dest_reg_id)
        return
    operand = _lower_expression_to_operand(builder, expr)
    if isinstance(operand, ir_model.BackendRegOperand):
        if operand.reg_id == dest_reg_id:
            return
        builder.emit_copy(dest=dest_reg_id, source=operand, span=span)
        return
    if isinstance(operand, ir_model.BackendConstOperand):
        if isinstance(operand.constant, ir_model.BackendNullConst) and not _is_null_typed(builder.require_register_type(dest_reg_id)):
            raise NotImplementedError(
                "Backend lowering does not materialize null into reference-typed locals yet"
            )
        if isinstance(operand.constant, ir_model.BackendUnitConst):
            raise NotImplementedError("Backend lowering cannot materialize unit-valued expressions into registers")
        builder.emit_const(dest=dest_reg_id, constant=operand.constant, span=span)
        return
    raise NotImplementedError(
        f"Backend lowering does not support materializing operand '{type(operand).__name__}' yet"
    )


def _lower_return_stmt(builder: _CallableBodyBuilder, stmt: SemanticReturn) -> None:
    if stmt.value is None:
        value = None
        if builder.kind == "constructor":
            if builder.receiver_reg is None:
                raise ValueError("Constructor lowering requires a receiver register")
            value = ir_model.BackendRegOperand(reg_id=builder.receiver_reg)
        builder.terminator = ir_model.BackendReturnTerminator(span=stmt.span, value=value)
        return
    builder.terminator = ir_model.BackendReturnTerminator(
        span=stmt.span,
        value=_lower_expression_to_operand(builder, stmt.value),
    )


def _lower_expression_to_operand(builder: _CallableBodyBuilder, expr: SemanticExpr) -> ir_model.BackendOperand:
    if isinstance(expr, LocalRefExpr):
        reg_id = builder.reg_id_by_local_id.get(expr.local_id)
        if reg_id is None:
            raise KeyError(f"Missing backend register for semantic local {expr.local_id}")
        return ir_model.BackendRegOperand(reg_id=reg_id)
    if isinstance(expr, NullExprS):
        return lower_null_operand()
    if hasattr(expr, "constant"):
        return lower_literal_expression_to_operand(expr)
    if isinstance(expr, UnaryExprS):
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="tmp")
        _materialize_expr_into(builder, dest_reg_id=dest_reg_id, expr=expr, span=expr.span)
        return ir_model.BackendRegOperand(reg_id=dest_reg_id)
    if isinstance(expr, BinaryExprS):
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="tmp")
        _materialize_expr_into(builder, dest_reg_id=dest_reg_id, expr=expr, span=expr.span)
        return ir_model.BackendRegOperand(reg_id=dest_reg_id)
    if isinstance(expr, CallExprS):
        return _lower_call_expression(builder, expr)
    if isinstance(expr, (FunctionRefExpr, MethodRefExpr, ClassRefExpr)):
        raise NotImplementedError(
            f"Backend lowering does not materialize first-class reference '{type(expr).__name__}' yet"
        )
    raise NotImplementedError(
        f"Backend lowering does not support expression type '{type(expr).__name__}' yet"
    )


def _lower_call_expression(builder: _CallableBodyBuilder, expr: CallExprS) -> ir_model.BackendOperand:
    dest_reg_id = None
    if _backend_return_type_for_expr(expr) is not None:
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="call")
    _emit_call_expression(builder, expr=expr, dest_reg_id=dest_reg_id)
    if dest_reg_id is None:
        return lower_unit_operand()
    return ir_model.BackendRegOperand(reg_id=dest_reg_id)


def _emit_call_expression(
    builder: _CallableBodyBuilder,
    *,
    expr: CallExprS,
    dest_reg_id: ir_model.BackendRegId | None,
) -> None:
    signature = _call_signature(builder, expr)
    args = tuple(_lower_expression_to_operand(builder, argument) for argument in expr.args)
    target = expr.target

    if isinstance(target, FunctionCallTarget):
        builder.emit_call(
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.function_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, StaticMethodCallTarget):
        builder.emit_call(
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.method_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, CallableValueCallTarget):
        callee = _lower_expression_to_operand(builder, target.callee)
        builder.emit_call(
            dest=dest_reg_id,
            target=ir_model.BackendIndirectCallTarget(callee=callee),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    raise NotImplementedError(
        f"Backend lowering does not support call target '{type(target).__name__}' yet"
    )


def _call_signature(builder: _CallableBodyBuilder, expr: CallExprS) -> ir_model.BackendSignature:
    target = expr.target
    if isinstance(target, FunctionCallTarget):
        return builder.require_callable_surface(target.function_id).signature
    if isinstance(target, StaticMethodCallTarget):
        surface = builder.require_callable_surface(target.method_id)
        if surface.expects_receiver:
            raise NotImplementedError("Backend lowering only supports static method direct calls in this slice")
        return surface.signature
    if isinstance(target, CallableValueCallTarget):
        callee_type_ref = target.callee.type_ref
        if not semantic_type_is_callable(callee_type_ref):
            raise TypeError("CallableValueCallTarget requires a callable semantic type")
        return ir_model.BackendSignature(
            param_types=semantic_type_callable_params(callee_type_ref),
            return_type=backend_signature_return_type(semantic_type_callable_return(callee_type_ref)),
        )
    raise NotImplementedError(
        f"Backend lowering does not support call target '{type(target).__name__}' yet"
    )


def _function_signature(function: SemanticFunction) -> ir_model.BackendSignature:
    return ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in function.params),
        return_type=backend_signature_return_type(function.return_type_ref),
    )


def _method_signature(method: SemanticMethod) -> ir_model.BackendSignature:
    return ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in method.params),
        return_type=backend_signature_return_type(method.return_type_ref),
    )


def _constructor_signature(owner_class_id: ClassId, constructor: SemanticConstructor) -> ir_model.BackendSignature:
    return ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in constructor.params),
        return_type=semantic_type_ref_for_class_id(owner_class_id),
    )


def _backend_return_type_for_expr(expr: SemanticExpr) -> SemanticTypeRef | None:
    return backend_signature_return_type(expr.type_ref)


def _conservative_user_call_effects() -> ir_model.BackendEffects:
    return ir_model.BackendEffects(reads_memory=True, writes_memory=True, may_gc=True, may_trap=True)


def _is_unit_typed(type_ref: SemanticTypeRef) -> bool:
    return semantic_type_canonical_name(type_ref) == "unit"


def _is_null_typed(type_ref: SemanticTypeRef) -> bool:
    return semantic_type_canonical_name(type_ref) == "null"


def _require_local_reg(builder: _CallableBodyBuilder, local_id: LocalId) -> ir_model.BackendRegId:
    reg_id = builder.reg_id_by_local_id.get(local_id)
    if reg_id is None:
        raise KeyError(f"Missing backend register for semantic local {local_id}")
    return reg_id


__all__ = [
    "LoweredCallable",
    "lower_constructor_callable",
    "lower_field_decl",
    "lower_function_callable",
    "lower_method_callable",
]