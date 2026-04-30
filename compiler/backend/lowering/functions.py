"""Callable lowering helpers for the phase-2 backend lowerer."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass

from compiler.backend.ir import model as ir_model
from compiler.backend.lowering.control_flow import CallableSurface, lower_callable_body
from compiler.backend.lowering.expressions import backend_signature_return_type
from compiler.semantic.ir import (
    BoundMemberAccess,
    CallExprS,
    ConstructorInitCallTarget,
    FieldLValue,
    LocalRefExpr,
    SemanticAssign,
    SemanticBlock,
    SemanticConstructor,
    SemanticExprStmt,
    SemanticField,
    SemanticFunction,
    SemanticFunctionLike,
    SemanticClass,
    SemanticLocalInfo,
    SemanticMethod,
)
from compiler.semantic.linker import LinkedSemanticProgram
from compiler.semantic.symbols import ClassId, LocalId
from compiler.semantic.types import (
    SemanticTypeRef,
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
    string_data_operand_for_literal: Callable[[str], tuple[ir_model.BackendDataOperand, int]],
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
            string_data_operand_for_literal=string_data_operand_for_literal,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_method_callable(
    owner_class_id: ClassId,
    method: SemanticMethod,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
    string_data_operand_for_literal: Callable[[str], tuple[ir_model.BackendDataOperand, int]],
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
            string_data_operand_for_literal=string_data_operand_for_literal,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def lower_constructor_callable(
    owner_class: SemanticClass,
    constructor: SemanticConstructor,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
    string_data_operand_for_literal: Callable[[str], tuple[ir_model.BackendDataOperand, int]],
) -> LoweredCallable:
    receiver_type_ref = semantic_type_ref_for_class_id(owner_class.class_id)
    signature = _constructor_signature(owner_class.class_id, constructor)
    layout = _allocate_register_layout(
        callable_id=constructor.constructor_id,
        params=constructor.params,
        local_info_by_id=constructor.local_info_by_id,
        receiver_type_ref=receiver_type_ref,
    )
    body = constructor.body
    if body is None:
        body = _synthesize_compatibility_constructor_body(
            owner_class,
            constructor,
            call_surface_by_id=call_surface_by_id,
        )
    else:
        body = _inject_explicit_constructor_field_initializers(owner_class, constructor, body)
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
            string_data_operand_for_literal=string_data_operand_for_literal,
        ),
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
    )


def _synthesize_compatibility_constructor_body(
    owner_class: SemanticClass,
    constructor: SemanticConstructor,
    *,
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
) -> SemanticBlock:
    access = _constructor_receiver_access(owner_class.class_id, constructor)
    param_expr_by_name = _constructor_param_expr_by_name(constructor)

    statements = []
    if constructor.super_constructor_id is not None:
        try:
            super_surface = call_surface_by_id[constructor.super_constructor_id]
        except KeyError as exc:
            raise KeyError(f"Missing callable surface for superclass constructor {constructor.super_constructor_id}") from exc
        super_param_count = len(super_surface.signature.param_types)
        super_class_id = ClassId(
            module_path=constructor.super_constructor_id.module_path,
            name=constructor.super_constructor_id.class_name,
        )
        statements.append(
            SemanticExprStmt(
                expr=CallExprS(
                    target=ConstructorInitCallTarget(
                        constructor_id=constructor.super_constructor_id,
                        access=access,
                    ),
                    args=[param_expr_by_name[param.name] for param in constructor.params[:super_param_count]],
                    type_ref=semantic_type_ref_for_class_id(super_class_id),
                    span=constructor.span,
                ),
                span=constructor.span,
            )
        )

    for field in owner_class.fields:
        value_expr = param_expr_by_name.get(field.name, field.initializer)
        if value_expr is None:
            raise ValueError(
                f"Compatibility constructor '{owner_class.class_id.name}' is missing an initializer for field '{field.name}'"
            )
        statements.append(
            SemanticAssign(
                target=FieldLValue(
                    access=access,
                    owner_class_id=owner_class.class_id,
                    field_name=field.name,
                    type_ref=field.type_ref,
                    span=constructor.span,
                ),
                value=value_expr,
                span=constructor.span,
            )
        )

    return SemanticBlock(statements=statements, span=constructor.span)


def _inject_explicit_constructor_field_initializers(
    owner_class: SemanticClass,
    constructor: SemanticConstructor,
    body: SemanticBlock,
) -> SemanticBlock:
    initializer_statements = _constructor_field_initializer_assignments(owner_class, constructor)
    if not initializer_statements:
        return body
    if not body.statements:
        return SemanticBlock(statements=initializer_statements, span=body.span)
    if _is_super_init_stmt(body.statements[0]):
        return SemanticBlock(
            statements=[body.statements[0], *initializer_statements, *body.statements[1:]],
            span=body.span,
        )
    return SemanticBlock(statements=[*initializer_statements, *body.statements], span=body.span)


def _constructor_field_initializer_assignments(
    owner_class: SemanticClass,
    constructor: SemanticConstructor,
) -> list[SemanticAssign]:
    access = _constructor_receiver_access(owner_class.class_id, constructor)
    return [
        SemanticAssign(
            target=FieldLValue(
                access=access,
                owner_class_id=owner_class.class_id,
                field_name=field.name,
                type_ref=field.type_ref,
                span=constructor.span,
            ),
            value=field.initializer,
            span=constructor.span,
        )
        for field in owner_class.fields
        if field.initializer is not None
    ]


def _constructor_receiver_access(owner_class_id: ClassId, constructor: SemanticConstructor) -> BoundMemberAccess:
    receiver_type_ref = semantic_type_ref_for_class_id(owner_class_id)
    receiver_local_id = _require_receiver_local_id(constructor)
    receiver_expr = LocalRefExpr(local_id=receiver_local_id, type_ref=receiver_type_ref, span=constructor.span)
    return BoundMemberAccess(receiver=receiver_expr, receiver_type_ref=receiver_type_ref)


def _is_super_init_stmt(stmt) -> bool:
    return (
        isinstance(stmt, SemanticExprStmt)
        and isinstance(stmt.expr, CallExprS)
        and isinstance(stmt.expr.target, ConstructorInitCallTarget)
    )


def _require_receiver_local_id(constructor: SemanticConstructor) -> LocalId:
    for local_info in sorted(constructor.local_info_by_id.values(), key=lambda info: info.local_id.ordinal):
        if local_info.binding_kind == "receiver":
            return local_info.local_id
    raise ValueError(f"Constructor '{constructor.constructor_id}' is missing receiver local metadata")


def _constructor_param_expr_by_name(constructor: SemanticConstructor) -> dict[str, LocalRefExpr]:
    param_local_infos = [
        local_info
        for local_info in sorted(constructor.local_info_by_id.values(), key=lambda info: info.local_id.ordinal)
        if local_info.binding_kind == "param"
    ]
    if len(param_local_infos) != len(constructor.params):
        raise ValueError(
            f"Constructor '{constructor.constructor_id}' parameter locals do not match its parameter list"
        )
    return {
        param.name: LocalRefExpr(local_id=local_info.local_id, type_ref=param.type_ref, span=param.span)
        for param, local_info in zip(constructor.params, param_local_infos, strict=True)
    }


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
    string_data_operand_for_literal: Callable[[str], tuple[ir_model.BackendDataOperand, int]],
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

    block_span = owner.span if body is None else body.span
    lowered_body = lower_callable_body(
        callable_id=callable_id,
        kind=kind,
        signature=signature,
        receiver_reg=layout.receiver_reg,
        reg_id_by_local_id=dict(layout.reg_id_by_local_id),
        registers=list(layout.registers),
        register_by_id={register.reg_id: register for register in layout.registers},
        call_surface_by_id=call_surface_by_id,
        string_data_operand_for_literal=string_data_operand_for_literal,
        next_reg_ordinal=layout.next_ordinal,
        body=body,
        block_span=block_span,
    )
    return ir_model.BackendCallableDecl(
        callable_id=callable_id,
        kind=kind,
        signature=signature,
        is_export=is_export,
        is_extern=False,
        is_static=is_static,
        is_private=is_private,
        registers=lowered_body.registers,
        param_regs=tuple(layout.param_regs),
        receiver_reg=layout.receiver_reg,
        entry_block_id=lowered_body.entry_block_id,
        blocks=lowered_body.blocks,
        span=owner.span,
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


__all__ = [
    "CallableSurface",
    "LoweredCallable",
    "build_callable_surface_by_id",
    "lower_constructor_callable",
    "lower_field_decl",
    "lower_function_callable",
    "lower_method_callable",
]