from __future__ import annotations

from compiler.backend.ir import (
    BackendBoolConst,
    BackendCastInst,
    BackendConstOperand,
    BackendDoubleConst,
    BackendIntConst,
    BackendNullConst,
    BackendRegOperand,
    BackendTypeTestInst,
)
from compiler.backend.program import BackendProgramContext
from compiler.backend.program.symbols import mangle_type_name_symbol, mangle_type_symbol
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.array_runtime import (
    RT_ARRAY_PRIMITIVE_TYPE_SYMBOL,
    RT_ARRAY_REFERENCE_TYPE_SYMBOL,
    array_element_kind_operand,
    array_runtime_kind_display_name_for_tag,
    array_runtime_kind_tag,
)
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.backend.targets.x86_64_sysv.instruction_selection import (
    emit_load_float_operand,
    emit_load_operand,
    emit_store_float_result,
    emit_store_result,
)
from compiler.backend.targets.x86_64_sysv.object_runtime import (
    interface_table_entry_operand,
    interface_tables_operand,
    object_type_operand,
    type_debug_name_operand,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_NULL, TYPE_NAME_OBJ, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.operations import CastSemanticsKind, TypeTestSemanticsKind
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_array_element,
    semantic_type_canonical_name,
    semantic_type_is_array,
    semantic_type_is_interface,
)


_PRIMARY_REGISTER = "rax"
_PRIMARY_BYTE_REGISTER = "al"
_PRIMARY_FLOAT_REGISTER = "xmm0"
_SECONDARY_REGISTER = "rcx"
_SECONDARY_BYTE_REGISTER = "cl"
_SECONDARY_FLOAT_REGISTER = "xmm1"
_TERTIARY_REGISTER = "rdx"
_TERTIARY_BYTE_REGISTER = "dl"

_ARRAY_KIND_NAME_LABELS = {
    1: "__nif_array_kind_name_i64",
    2: "__nif_array_kind_name_u64",
    3: "__nif_array_kind_name_u8",
    4: "__nif_array_kind_name_bool",
    5: "__nif_array_kind_name_double",
    6: "__nif_array_kind_name_obj",
}
_UNKNOWN_ARRAY_KIND_NAME_LABEL = "__nif_array_kind_name_unknown"


def emit_cast_instruction(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    callable_label: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_context: BackendProgramContext,
) -> None:
    source_type_name = _operand_type_name(instruction.operand, register_type_name_by_reg_id)
    target_type_name = semantic_type_canonical_name(instruction.target_type_ref)

    if instruction.cast_kind is CastSemanticsKind.IDENTITY:
        if target_type_name == TYPE_NAME_DOUBLE:
            emit_load_float_operand(
                builder,
                instruction.operand,
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        emit_load_operand(
            builder,
            instruction.operand,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if instruction.cast_kind is CastSemanticsKind.TO_DOUBLE:
        _emit_to_double_cast(
            builder,
            instruction,
            source_type_name=source_type_name,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if instruction.cast_kind is CastSemanticsKind.TO_INTEGER:
        _emit_to_integer_cast(
            builder,
            instruction,
            source_type_name=source_type_name,
            target_type_name=target_type_name,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if instruction.cast_kind is CastSemanticsKind.TO_BOOL:
        _emit_to_bool_cast(
            builder,
            instruction,
            source_type_name=source_type_name,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if instruction.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY:
        emit_load_operand(
            builder,
            instruction.operand,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        if not instruction.trap_on_failure or source_type_name == TYPE_NAME_NULL or target_type_name == TYPE_NAME_OBJ:
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        if semantic_type_is_array(instruction.target_type_ref):
            _emit_array_checked_cast(builder, instruction, callable_label=callable_label)
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        if semantic_type_is_interface(instruction.target_type_ref):
            _emit_interface_checked_cast(
                builder,
                instruction,
                callable_label=callable_label,
                program_context=program_context,
            )
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        _emit_class_checked_cast(
            builder,
            instruction,
            callable_label=callable_label,
            program_context=program_context,
        )
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    raise BackendTargetLoweringError(
        f"x86_64_sysv cast emission does not support '{instruction.cast_kind.value}'"
    )


def emit_type_test_instruction(
    builder: X86AsmBuilder,
    instruction: BackendTypeTestInst,
    *,
    callable_label: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_context: BackendProgramContext,
) -> None:
    emit_load_operand(
        builder,
        instruction.operand,
        target_register=_PRIMARY_REGISTER,
        target_byte_register=_PRIMARY_BYTE_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )

    if semantic_type_is_array(instruction.target_type_ref):
        _emit_array_type_test(builder, instruction, callable_label=callable_label)
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return
    if instruction.test_kind is TypeTestSemanticsKind.INTERFACE_COMPATIBILITY:
        _emit_interface_type_test(builder, instruction, callable_label=callable_label, program_context=program_context)
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return
    _emit_class_type_test(builder, instruction, program_context=program_context)
    emit_store_result(builder, instruction.dest, frame_layout=frame_layout)


def emit_array_kind_name_literals(builder: X86AsmBuilder) -> None:
    builder.blank()
    builder.directive(".section .rodata")
    for kind_tag in sorted(_ARRAY_KIND_NAME_LABELS):
        builder.label(_ARRAY_KIND_NAME_LABELS[kind_tag])
        builder.directive(f'.asciz "{_escape_c_string(array_runtime_kind_display_name_for_tag(kind_tag))}"')
    builder.label(_UNKNOWN_ARRAY_KIND_NAME_LABEL)
    builder.directive('.asciz "<unknown-array-kind>"')


def _emit_to_double_cast(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    source_type_name: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if source_type_name == TYPE_NAME_DOUBLE:
        emit_load_float_operand(
            builder,
            instruction.operand,
            target_float_register=_PRIMARY_FLOAT_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        return
    emit_load_operand(
        builder,
        instruction.operand,
        target_register=_PRIMARY_REGISTER,
        target_byte_register=_PRIMARY_BYTE_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    if source_type_name == TYPE_NAME_U64:
        builder.instruction("mov", "rdi", _PRIMARY_REGISTER)
        builder.instruction("call", "rt_cast_u64_to_double")
        return
    builder.instruction("cvtsi2sd", _PRIMARY_FLOAT_REGISTER, _PRIMARY_REGISTER)


def _emit_to_integer_cast(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    source_type_name: str,
    target_type_name: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if source_type_name == TYPE_NAME_DOUBLE:
        emit_load_float_operand(
            builder,
            instruction.operand,
            target_float_register=_PRIMARY_FLOAT_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        if target_type_name == "i64":
            builder.instruction("call", "rt_cast_double_to_i64")
            return
        if target_type_name == TYPE_NAME_U64:
            builder.instruction("call", "rt_cast_double_to_u64")
            return
        if target_type_name == TYPE_NAME_U8:
            builder.instruction("call", "rt_cast_double_to_u8")
            return
        raise BackendTargetLoweringError(
            f"x86_64_sysv double-to-integer cast does not support target '{target_type_name}'"
        )

    emit_load_operand(
        builder,
        instruction.operand,
        target_register=_PRIMARY_REGISTER,
        target_byte_register=_PRIMARY_BYTE_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    if target_type_name == TYPE_NAME_U8:
        builder.instruction("and", _PRIMARY_REGISTER, "255")


def _emit_to_bool_cast(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    source_type_name: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if source_type_name == TYPE_NAME_DOUBLE:
        emit_load_float_operand(
            builder,
            instruction.operand,
            target_float_register=_PRIMARY_FLOAT_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        builder.instruction("xorpd", _SECONDARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
        builder.instruction("ucomisd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
        builder.instruction("setne", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("or", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
        builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
        return

    emit_load_operand(
        builder,
        instruction.operand,
        target_register=_PRIMARY_REGISTER,
        target_byte_register=_PRIMARY_BYTE_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("setne", _PRIMARY_BYTE_REGISTER)
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)


def _emit_class_checked_cast(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    callable_label: str,
    program_context: BackendProgramContext,
) -> None:
    done_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_class_cast_done"
    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("je", done_label)
    builder.instruction("mov", "rdi", _PRIMARY_REGISTER)
    builder.instruction("lea", "rsi", f"[rip + {_type_symbol_for_target(instruction.target_type_ref, program_context=program_context)}]")
    builder.instruction("call", "rt_checked_cast")
    builder.label(done_label)


def _emit_class_type_test(
    builder: X86AsmBuilder,
    instruction: BackendTypeTestInst,
    *,
    program_context: BackendProgramContext,
) -> None:
    builder.instruction("mov", "rdi", _PRIMARY_REGISTER)
    builder.instruction("lea", "rsi", f"[rip + {_type_symbol_for_target(instruction.target_type_ref, program_context=program_context)}]")
    builder.instruction("call", "rt_is_instance_of_type")


def _emit_interface_checked_cast(
    builder: X86AsmBuilder,
    instruction: BackendCastInst,
    *,
    callable_label: str,
    program_context: BackendProgramContext,
) -> None:
    done_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_iface_cast_done"
    match_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_iface_cast_ok"
    slot_index = _interface_slot_index(program_context, instruction.target_type_ref)

    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("je", done_label)
    builder.instruction("mov", _SECONDARY_REGISTER, object_type_operand(_PRIMARY_REGISTER))
    builder.instruction("mov", _SECONDARY_REGISTER, interface_tables_operand(_SECONDARY_REGISTER))
    builder.instruction("mov", _SECONDARY_REGISTER, interface_table_entry_operand(_SECONDARY_REGISTER, slot_index))
    builder.instruction("test", _SECONDARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("jne", match_label)
    builder.instruction("mov", _SECONDARY_REGISTER, object_type_operand(_PRIMARY_REGISTER))
    builder.instruction(
        "mov",
        "rdi",
        type_debug_name_operand(_SECONDARY_REGISTER),
    )
    builder.instruction(
        "lea",
        "rsi",
        f"[rip + {_type_name_symbol_for_target(instruction.target_type_ref, program_context=program_context)}]",
    )
    builder.instruction("call", "rt_panic_bad_cast")
    builder.label(match_label)
    builder.label(done_label)


def _emit_interface_type_test(
    builder: X86AsmBuilder,
    instruction: BackendTypeTestInst,
    *,
    callable_label: str,
    program_context: BackendProgramContext,
) -> None:
    false_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_iface_test_false"
    done_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_iface_test_done"
    slot_index = _interface_slot_index(program_context, instruction.target_type_ref)

    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("je", false_label)
    builder.instruction("mov", _SECONDARY_REGISTER, object_type_operand(_PRIMARY_REGISTER))
    builder.instruction("mov", _SECONDARY_REGISTER, interface_tables_operand(_SECONDARY_REGISTER))
    builder.instruction("mov", _SECONDARY_REGISTER, interface_table_entry_operand(_SECONDARY_REGISTER, slot_index))
    builder.instruction("test", _SECONDARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("setne", _PRIMARY_BYTE_REGISTER)
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
    builder.instruction("jmp", done_label)
    builder.label(false_label)
    builder.instruction("xor", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.label(done_label)


def _emit_array_checked_cast(builder: X86AsmBuilder, instruction: BackendCastInst, *, callable_label: str) -> None:
    expected_kind = _array_runtime_kind_for_type_ref(instruction.target_type_ref)
    expected_kind_tag = array_runtime_kind_tag(expected_kind)
    done_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_cast_done"
    type_ok_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_cast_type_ok"
    kind_ok_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_cast_kind_ok"

    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("je", done_label)
    builder.instruction("mov", _SECONDARY_REGISTER, object_type_operand(_PRIMARY_REGISTER))
    builder.instruction("lea", _TERTIARY_REGISTER, f"[rip + {RT_ARRAY_PRIMITIVE_TYPE_SYMBOL}]")
    builder.instruction("cmp", _SECONDARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("je", type_ok_label)
    builder.instruction("lea", _TERTIARY_REGISTER, f"[rip + {RT_ARRAY_REFERENCE_TYPE_SYMBOL}]")
    builder.instruction("cmp", _SECONDARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("je", type_ok_label)
    builder.instruction("mov", "rdi", type_debug_name_operand(_SECONDARY_REGISTER))
    builder.instruction("lea", "rsi", f"[rip + {_array_kind_name_label(expected_kind_tag)}]")
    builder.instruction("call", "rt_panic_bad_cast")
    builder.label(type_ok_label)
    builder.instruction("cmp", array_element_kind_operand(_PRIMARY_REGISTER), str(expected_kind_tag))
    builder.instruction("je", kind_ok_label)
    builder.instruction("mov", _SECONDARY_REGISTER, array_element_kind_operand(_PRIMARY_REGISTER))
    _emit_array_kind_name_pointer(
        builder,
        kind_register=_SECONDARY_REGISTER,
        target_register="rdi",
        label_stem=f"{callable_label}_i{instruction.inst_id.ordinal}_array_kind_name",
    )
    builder.instruction("lea", "rsi", f"[rip + {_array_kind_name_label(expected_kind_tag)}]")
    builder.instruction("call", "rt_panic_bad_cast")
    builder.label(kind_ok_label)
    builder.label(done_label)


def _emit_array_type_test(builder: X86AsmBuilder, instruction: BackendTypeTestInst, *, callable_label: str) -> None:
    expected_kind = _array_runtime_kind_for_type_ref(instruction.target_type_ref)
    expected_kind_tag = array_runtime_kind_tag(expected_kind)
    false_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_test_false"
    type_ok_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_test_type_ok"
    done_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_array_test_done"

    builder.instruction("test", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("je", false_label)
    builder.instruction("mov", _SECONDARY_REGISTER, object_type_operand(_PRIMARY_REGISTER))
    builder.instruction("lea", _TERTIARY_REGISTER, f"[rip + {RT_ARRAY_PRIMITIVE_TYPE_SYMBOL}]")
    builder.instruction("cmp", _SECONDARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("je", type_ok_label)
    builder.instruction("lea", _TERTIARY_REGISTER, f"[rip + {RT_ARRAY_REFERENCE_TYPE_SYMBOL}]")
    builder.instruction("cmp", _SECONDARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("jne", false_label)
    builder.label(type_ok_label)
    builder.instruction("cmp", array_element_kind_operand(_PRIMARY_REGISTER), str(expected_kind_tag))
    builder.instruction("sete", _PRIMARY_BYTE_REGISTER)
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
    builder.instruction("jmp", done_label)
    builder.label(false_label)
    builder.instruction("xor", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
    builder.label(done_label)


def _emit_array_kind_name_pointer(
    builder: X86AsmBuilder,
    *,
    kind_register: str,
    target_register: str,
    label_stem: str,
) -> None:
    done_label = f".L{label_stem}_done"
    for kind_tag in sorted(_ARRAY_KIND_NAME_LABELS):
        next_label = f".L{label_stem}_next_{kind_tag}"
        builder.instruction("cmp", kind_register, str(kind_tag))
        builder.instruction("jne", next_label)
        builder.instruction("lea", target_register, f"[rip + {_array_kind_name_label(kind_tag)}]")
        builder.instruction("jmp", done_label)
        builder.label(next_label)
    builder.instruction("lea", target_register, f"[rip + {_UNKNOWN_ARRAY_KIND_NAME_LABEL}]")
    builder.label(done_label)


def _array_runtime_kind_for_type_ref(type_ref: SemanticTypeRef) -> ArrayRuntimeKind:
    element_type = semantic_type_array_element(type_ref)
    element_type_name = semantic_type_canonical_name(element_type)
    if element_type_name == "i64":
        return ArrayRuntimeKind.I64
    if element_type_name == TYPE_NAME_U64:
        return ArrayRuntimeKind.U64
    if element_type_name == TYPE_NAME_U8:
        return ArrayRuntimeKind.U8
    if element_type_name == TYPE_NAME_BOOL:
        return ArrayRuntimeKind.BOOL
    if element_type_name == TYPE_NAME_DOUBLE:
        return ArrayRuntimeKind.DOUBLE
    return ArrayRuntimeKind.REF
def _array_kind_name_label(kind_tag: int) -> str:
    return _ARRAY_KIND_NAME_LABELS.get(kind_tag, _UNKNOWN_ARRAY_KIND_NAME_LABEL)


def _interface_slot_index(program_context: BackendProgramContext, type_ref: SemanticTypeRef) -> int:
    interface_id = type_ref.interface_id
    if interface_id is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv interface cast or type test requires an interface target, got '{type_ref.display_name}'"
        )
    for interface_record in program_context.metadata.interfaces:
        if interface_record.interface_id == interface_id:
            return interface_record.slot_index
    raise BackendTargetLoweringError(
        f"x86_64_sysv backend program context is missing interface metadata for '{interface_id}'"
    )


def _type_symbol_for_target(type_ref: SemanticTypeRef, *, program_context: BackendProgramContext) -> str:
    if type_ref.class_id is not None:
        return program_context.symbols.class_symbols(type_ref.class_id).type_symbol
    return mangle_type_symbol(semantic_type_canonical_name(type_ref))


def _type_name_symbol_for_target(type_ref: SemanticTypeRef, *, program_context: BackendProgramContext) -> str:
    if type_ref.interface_id is not None:
        return program_context.symbols.interface_symbols(type_ref.interface_id).name_symbol
    if type_ref.class_id is not None:
        return program_context.symbols.class_symbols(type_ref.class_id).type_name_symbol
    return mangle_type_name_symbol(semantic_type_canonical_name(type_ref))


def _operand_type_name(operand, register_type_name_by_reg_id: dict) -> str:
    if isinstance(operand, BackendRegOperand):
        return register_type_name_by_reg_id[operand.reg_id]
    if isinstance(operand, BackendConstOperand):
        if isinstance(operand.constant, BackendIntConst):
            return operand.constant.type_name
        if isinstance(operand.constant, BackendBoolConst):
            return TYPE_NAME_BOOL
        if isinstance(operand.constant, BackendDoubleConst):
            return TYPE_NAME_DOUBLE
        if isinstance(operand.constant, BackendNullConst):
            return TYPE_NAME_NULL
    raise BackendTargetLoweringError(f"x86_64_sysv cast emission does not support operand '{operand!r}'")


def _escape_c_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


__all__ = [
    "emit_array_kind_name_literals",
    "emit_cast_instruction",
    "emit_type_test_instruction",
]