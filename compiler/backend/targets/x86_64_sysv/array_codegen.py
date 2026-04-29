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
from compiler.backend.targets.x86_64_sysv.array_runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
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


def emit_array_length_instruction(builder, instruction: BackendArrayLengthInst, *, emit_call_instruction) -> None:
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


def emit_array_load_instruction(builder, instruction: BackendArrayLoadInst, *, emit_call_instruction) -> None:
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


def emit_array_store_instruction(builder, instruction: BackendArrayStoreInst, *, emit_call_instruction) -> None:
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
    # The runtime-backed array helpers already enforce the same bounds contract,
    # so PR4 does not duplicate a second target-local trap sequence here.
    return


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