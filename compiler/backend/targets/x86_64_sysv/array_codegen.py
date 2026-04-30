from __future__ import annotations

from compiler.backend.ir import (
    BackendArrayAllocInst,
    BackendArrayLengthInst,
    BackendArrayLoadInst,
    BackendArraySliceInst,
    BackendArraySliceStoreInst,
    BackendArrayStoreInst,
    BackendBoundsCheckInst,
    BackendCallInst,
    BackendEffects,
    BackendRuntimeCallTarget,
    BackendSignature,
)
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.backend.targets.x86_64_sysv.instruction_selection import (
    emit_load_float_operand,
    emit_load_operand,
    emit_store_float_result,
    emit_store_result,
)
from compiler.backend.targets.x86_64_sysv.array_runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_GET_OOB_PANIC_RUNTIME_CALL,
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_NULL_PANIC_RUNTIME_CALL,
    ARRAY_SET_OOB_PANIC_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
    array_data_index_address,
    array_length_operand,
    array_runtime_kind_tag,
    direct_primitive_array_store_operand,
    direct_ref_array_store_operand,
    is_direct_primitive_array_runtime_kind,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_OBJ, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import SemanticTypeRef, semantic_array_type_ref, semantic_primitive_type_ref


_I64_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_I64)
_U64_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_U64)
_U8_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_U8)
_BOOL_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_BOOL)
_DOUBLE_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_DOUBLE)
_OBJ_TYPE_REF = SemanticTypeRef(kind="reference", canonical_name=TYPE_NAME_OBJ, display_name=TYPE_NAME_OBJ)


def emit_array_alloc_instruction(builder, instruction: BackendArrayAllocInst, *, emit_call_instruction) -> None:
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_CONSTRUCTOR_RUNTIME_CALLS[instruction.array_runtime_kind],
            args=(instruction.length,),
            param_types=(_U64_TYPE_REF,),
            return_type=_array_type_for_runtime_kind(instruction.array_runtime_kind),
            dest=instruction.dest,
            effects=instruction.effects,
        )
    )


def emit_array_length_instruction(
    builder,
    instruction: BackendArrayLengthInst,
    *,
    callable_label: str,
    emit_call_instruction,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    options: BackendTargetOptions,
) -> None:
    if options.collection_fast_paths_enabled:
        non_null_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_len_nonnull"
        emit_load_operand(
            builder,
            instruction.array_ref,
            target_register="rax",
            target_byte_register="al",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        builder.instruction("test", "rax", "rax")
        builder.instruction("jne", non_null_label)
        builder.instruction("call", ARRAY_NULL_PANIC_RUNTIME_CALL)
        builder.label(non_null_label)
        builder.instruction("mov", "rax", array_length_operand("rax"))
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_LEN_RUNTIME_CALL,
            args=(instruction.array_ref,),
            param_types=(_OBJ_TYPE_REF,),
            return_type=_U64_TYPE_REF,
            dest=instruction.dest,
            effects=BackendEffects(reads_memory=True),
        )
    )


def emit_array_load_instruction(
    builder,
    instruction: BackendArrayLoadInst,
    *,
    callable_label: str,
    emit_call_instruction,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    options: BackendTargetOptions,
) -> None:
    if options.collection_fast_paths_enabled:
        emit_load_operand(
            builder,
            instruction.array_ref,
            target_register="rax",
            target_byte_register="al",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_load_operand(
            builder,
            instruction.index,
            target_register="rcx",
            target_byte_register="cl",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        _emit_direct_array_index_bounds_check(
            builder,
            callable_label=callable_label,
            instruction=instruction,
            panic_symbol=ARRAY_GET_OOB_PANIC_RUNTIME_CALL,
        )
        if instruction.array_runtime_kind is ArrayRuntimeKind.DOUBLE:
            builder.instruction("movq", "xmm0", _direct_array_load_operand(instruction.array_runtime_kind))
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        if instruction.array_runtime_kind is ArrayRuntimeKind.U8:
            builder.instruction("movzx", "eax", _direct_array_load_operand(instruction.array_runtime_kind))
        else:
            builder.instruction("mov", "rax", _direct_array_load_operand(instruction.array_runtime_kind))
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_INDEX_GET_RUNTIME_CALLS[instruction.array_runtime_kind],
            args=(instruction.array_ref, instruction.index),
            param_types=(_OBJ_TYPE_REF, _I64_TYPE_REF),
            return_type=_element_type_for_runtime_kind(instruction.array_runtime_kind),
            dest=instruction.dest,
            effects=BackendEffects(reads_memory=True),
        )
    )


def emit_array_store_instruction(
    builder,
    instruction: BackendArrayStoreInst,
    *,
    callable_label: str,
    emit_call_instruction,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    options: BackendTargetOptions,
) -> None:
    if options.collection_fast_paths_enabled:
        emit_load_operand(
            builder,
            instruction.array_ref,
            target_register="rax",
            target_byte_register="al",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_load_operand(
            builder,
            instruction.index,
            target_register="rcx",
            target_byte_register="cl",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        _emit_direct_array_index_bounds_check(
            builder,
            callable_label=callable_label,
            instruction=instruction,
            panic_symbol=ARRAY_SET_OOB_PANIC_RUNTIME_CALL,
        )
        if instruction.array_runtime_kind is ArrayRuntimeKind.DOUBLE:
            emit_load_float_operand(
                builder,
                instruction.value,
                target_float_register="xmm0",
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_load_operand(
                builder,
                instruction.array_ref,
                target_register="rax",
                target_byte_register="al",
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_load_operand(
                builder,
                instruction.index,
                target_register="rcx",
                target_byte_register="cl",
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            builder.instruction("movq", _direct_array_store_operand(instruction.array_runtime_kind), "xmm0")
            return
        emit_load_operand(
            builder,
            instruction.value,
            target_register="rdx",
            target_byte_register="dl",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        if instruction.array_runtime_kind is ArrayRuntimeKind.BOOL:
            builder.instruction("test", "rdx", "rdx")
            builder.instruction("setne", "dl")
            builder.instruction("movzx", "edx", "dl")
        if instruction.array_runtime_kind is ArrayRuntimeKind.U8:
            builder.instruction("mov", _direct_array_store_operand(instruction.array_runtime_kind), "dl")
            return
        builder.instruction("mov", _direct_array_store_operand(instruction.array_runtime_kind), "rdx")
        return
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_INDEX_SET_RUNTIME_CALLS[instruction.array_runtime_kind],
            args=(instruction.array_ref, instruction.index, instruction.value),
            param_types=(_OBJ_TYPE_REF, _I64_TYPE_REF, _element_type_for_runtime_kind(instruction.array_runtime_kind)),
            return_type=None,
            dest=None,
            effects=BackendEffects(reads_memory=True, writes_memory=True),
        )
    )


def emit_array_slice_instruction(builder, instruction: BackendArraySliceInst, *, emit_call_instruction) -> None:
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_SLICE_GET_RUNTIME_CALLS[instruction.array_runtime_kind],
            args=(instruction.array_ref, instruction.begin, instruction.end),
            param_types=(_OBJ_TYPE_REF, _I64_TYPE_REF, _I64_TYPE_REF),
            return_type=_array_type_for_runtime_kind(instruction.array_runtime_kind),
            dest=instruction.dest,
            effects=instruction.effects,
        )
    )


def emit_array_slice_store_instruction(builder, instruction: BackendArraySliceStoreInst, *, emit_call_instruction) -> None:
    emit_call_instruction(
        _runtime_call_instruction(
            instruction,
            name=ARRAY_SLICE_SET_RUNTIME_CALLS[instruction.array_runtime_kind],
            args=(instruction.array_ref, instruction.begin, instruction.end, instruction.value),
            param_types=(_OBJ_TYPE_REF, _I64_TYPE_REF, _I64_TYPE_REF, _array_type_for_runtime_kind(instruction.array_runtime_kind)),
            return_type=None,
            dest=None,
            effects=BackendEffects(reads_memory=True, writes_memory=True),
        )
    )


def emit_bounds_check_instruction(builder, instruction: BackendBoundsCheckInst) -> None:
    # Array load/store fast paths lower bounds checks inline so they can preserve
    # operation-specific panic messages. Slice helpers still validate ranges.
    return


def _emit_direct_array_index_bounds_check(builder, *, callable_label: str, instruction, panic_symbol: str) -> None:
    in_bounds_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_in_bounds"
    builder.instruction("cmp", "rcx", "0")
    builder.instruction("jl", f"{in_bounds_label}_panic")
    builder.instruction("cmp", "rcx", array_length_operand("rax"))
    builder.instruction("jb", in_bounds_label)
    builder.label(f"{in_bounds_label}_panic")
    builder.instruction("mov", "rdi", str(array_runtime_kind_tag(instruction.array_runtime_kind)))
    builder.instruction("call", panic_symbol)
    builder.label(in_bounds_label)


def _direct_array_load_operand(runtime_kind: ArrayRuntimeKind) -> str:
    if runtime_kind is ArrayRuntimeKind.REF:
        return direct_ref_array_store_operand("rax", "rcx")
    if is_direct_primitive_array_runtime_kind(runtime_kind):
        if runtime_kind is ArrayRuntimeKind.U8:
            return f"byte ptr {array_data_index_address('rax', 'rcx', element_size=1)}"
        return f"qword ptr {array_data_index_address('rax', 'rcx', element_size=8)}"
    raise ValueError(f"unsupported direct array load runtime kind '{runtime_kind}'")


def _direct_array_store_operand(runtime_kind: ArrayRuntimeKind) -> str:
    if runtime_kind is ArrayRuntimeKind.REF:
        return direct_ref_array_store_operand("rax", "rcx")
    return direct_primitive_array_store_operand("rax", "rcx", runtime_kind=runtime_kind)


def _runtime_call_instruction(
    instruction,
    *,
    name: str,
    args: tuple,
    param_types: tuple[SemanticTypeRef, ...],
    return_type: SemanticTypeRef | None,
    dest,
    effects=None,
) -> BackendCallInst:
    return BackendCallInst(
        inst_id=instruction.inst_id,
        dest=dest,
        target=BackendRuntimeCallTarget(name=name, ref_arg_indices=()),
        args=args,
        signature=BackendSignature(param_types=param_types, return_type=return_type),
        effects=instruction.effects if effects is None else effects,
        span=instruction.span,
    )


def _element_type_for_runtime_kind(runtime_kind: ArrayRuntimeKind) -> SemanticTypeRef:
    if runtime_kind is ArrayRuntimeKind.I64:
        return _I64_TYPE_REF
    if runtime_kind is ArrayRuntimeKind.U64:
        return _U64_TYPE_REF
    if runtime_kind is ArrayRuntimeKind.U8:
        return _U8_TYPE_REF
    if runtime_kind is ArrayRuntimeKind.BOOL:
        return _BOOL_TYPE_REF
    if runtime_kind is ArrayRuntimeKind.DOUBLE:
        return _DOUBLE_TYPE_REF
    if runtime_kind is ArrayRuntimeKind.REF:
        return _OBJ_TYPE_REF
    raise ValueError(f"unsupported array runtime kind '{runtime_kind}'")


def _array_type_for_runtime_kind(runtime_kind: ArrayRuntimeKind) -> SemanticTypeRef:
    return semantic_array_type_ref(_element_type_for_runtime_kind(runtime_kind))


__all__ = [
    "emit_array_alloc_instruction",
    "emit_array_length_instruction",
    "emit_array_load_instruction",
    "emit_array_slice_instruction",
    "emit_array_slice_store_instruction",
    "emit_array_store_instruction",
    "emit_bounds_check_instruction",
]