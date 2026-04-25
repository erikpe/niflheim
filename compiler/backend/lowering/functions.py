"""Callable lowering helpers for phase-2 PR1 backend lowering."""

from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import model as ir_model
from compiler.backend.lowering.expressions import lower_smoke_expression_to_operand
from compiler.common.span import SourceSpan
from compiler.semantic.ir import (
    LocalLValue,
    SemanticAssign,
    SemanticBlock,
    SemanticConstructor,
    SemanticExprStmt,
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
)
from compiler.semantic.symbols import ClassId, ConstructorId, LocalId, MethodId
from compiler.semantic.types import SemanticTypeRef, semantic_type_ref_for_class_id


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


@dataclass
class _CallableBodyBuilder:
    callable_id: ir_model.BackendCallableId
    kind: ir_model.BackendCallableKind
    signature: ir_model.BackendSignature
    receiver_reg: ir_model.BackendRegId | None
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId]
    block_span: SourceSpan
    instructions: list[ir_model.BackendInstruction]
    next_inst_ordinal: int = 0
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

    def _next_inst_id(self) -> ir_model.BackendInstId:
        inst_id = ir_model.BackendInstId(owner_id=self.callable_id, ordinal=self.next_inst_ordinal)
        self.next_inst_ordinal += 1
        return inst_id


def lower_function_callable(function: SemanticFunction) -> LoweredCallable:
    signature = ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in function.params),
        return_type=function.return_type_ref,
    )
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
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_method_callable(owner_class_id: ClassId, method: SemanticMethod) -> LoweredCallable:
    signature = ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in method.params),
        return_type=method.return_type_ref,
    )
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
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_constructor_callable(owner_class_id: ClassId, constructor: SemanticConstructor) -> LoweredCallable:
    receiver_type_ref = semantic_type_ref_for_class_id(owner_class_id)
    signature = ir_model.BackendSignature(
        param_types=tuple(param.type_ref for param in constructor.params),
        return_type=receiver_type_ref,
    )
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
        block_span=block_span,
        instructions=[],
    )

    if body is not None:
        _lower_smoke_block(builder, body)

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
        registers=tuple(layout.registers),
        param_regs=tuple(layout.param_regs),
        receiver_reg=layout.receiver_reg,
        entry_block_id=entry_block_id,
        blocks=(block,),
        span=owner.span,
    )


def _lower_smoke_block(builder: _CallableBodyBuilder, block: SemanticBlock) -> None:
    for statement in block.statements:
        if builder.terminator is not None:
            raise NotImplementedError("Backend lowering smoke path does not support statements after return yet")
        _lower_smoke_stmt(builder, statement)


def _lower_smoke_stmt(builder: _CallableBodyBuilder, stmt: SemanticStmt) -> None:
    if isinstance(stmt, SemanticBlock):
        _lower_smoke_block(builder, stmt)
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
                f"Backend lowering smoke path does not support assignment target '{type(stmt.target).__name__}' yet"
            )
        dest_reg_id = _require_local_reg(builder, stmt.target.local_id)
        _materialize_expr_into(builder, dest_reg_id=dest_reg_id, expr=stmt.value, span=stmt.span)
        return
    if isinstance(stmt, SemanticExprStmt):
        lower_smoke_expression_to_operand(stmt.expr, reg_id_by_local_id=builder.reg_id_by_local_id)
        return
    if isinstance(stmt, SemanticReturn):
        _lower_smoke_return(builder, stmt)
        return
    if isinstance(stmt, (SemanticIf, SemanticWhile)):
        raise NotImplementedError(
            f"Backend lowering smoke path does not support statement '{type(stmt).__name__}' yet"
        )
    raise NotImplementedError(
        f"Backend lowering smoke path does not support statement '{type(stmt).__name__}' yet"
    )


def _materialize_expr_into(
    builder: _CallableBodyBuilder,
    *,
    dest_reg_id: ir_model.BackendRegId,
    expr,
    span: SourceSpan,
) -> None:
    operand = lower_smoke_expression_to_operand(expr, reg_id_by_local_id=builder.reg_id_by_local_id)
    if isinstance(operand, ir_model.BackendRegOperand):
        if operand.reg_id == dest_reg_id:
            return
        builder.emit_copy(dest=dest_reg_id, source=operand, span=span)
        return
    if isinstance(operand, ir_model.BackendConstOperand):
        builder.emit_const(dest=dest_reg_id, constant=operand.constant, span=span)
        return
    raise NotImplementedError(
        f"Backend lowering smoke path does not support materializing operand '{type(operand).__name__}' yet"
    )


def _lower_smoke_return(builder: _CallableBodyBuilder, stmt: SemanticReturn) -> None:
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
        value=lower_smoke_expression_to_operand(stmt.value, reg_id_by_local_id=builder.reg_id_by_local_id),
    )


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