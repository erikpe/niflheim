from __future__ import annotations

from compiler.backend.ir import BackendAllocObjectInst, BackendFieldLoadInst, BackendFieldStoreInst, BackendNullCheckInst
from compiler.backend.program import BackendProgramContext
from compiler.backend.program.symbols import mangle_type_name_symbol, mangle_type_symbol
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.backend.targets.x86_64_sysv.instruction_selection import (
    emit_load_float_operand,
    emit_load_operand,
    emit_store_float_result,
    emit_store_result,
)
from compiler.backend.targets.x86_64_sysv.object_runtime import RT_TYPE_FLAG_HAS_REFS


def emit_alloc_object_instruction(
    builder: X86AsmBuilder,
    instruction: BackendAllocObjectInst,
    *,
    frame_layout: X86_64SysVFrameLayout,
    program_context: BackendProgramContext,
) -> None:
    class_symbols = program_context.symbols.class_symbols(instruction.class_id)
    payload_bytes = program_context.class_hierarchy.payload_bytes(instruction.class_id)

    builder.instruction("call", "rt_thread_state")
    builder.instruction("mov", "rdi", "rax")
    builder.instruction("lea", "rsi", f"[rip + {class_symbols.type_symbol}]")
    builder.instruction("mov", "rdx", str(payload_bytes))
    builder.instruction("call", "rt_alloc_obj")
    emit_store_result(builder, instruction.dest, frame_layout=frame_layout)


def emit_field_load_instruction(
    builder: X86AsmBuilder,
    instruction: BackendFieldLoadInst,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_context: BackendProgramContext,
) -> None:
    field_slot = _field_slot(program_context, instruction.owner_class_id, instruction.field_name)
    emit_load_operand(
        builder,
        instruction.object_ref,
        target_register="rax",
        target_byte_register="al",
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    if field_slot.type_ref.canonical_name == "double":
        builder.instruction("movq", "xmm0", format_stack_slot_operand("rax", field_slot.offset))
        emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
        return
    builder.instruction("mov", "rax", format_stack_slot_operand("rax", field_slot.offset))
    emit_store_result(builder, instruction.dest, frame_layout=frame_layout)


def emit_field_store_instruction(
    builder: X86AsmBuilder,
    instruction: BackendFieldStoreInst,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_context: BackendProgramContext,
) -> None:
    field_slot = _field_slot(program_context, instruction.owner_class_id, instruction.field_name)
    emit_load_operand(
        builder,
        instruction.object_ref,
        target_register="rcx",
        target_byte_register="cl",
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    if field_slot.type_ref.canonical_name == "double":
        emit_load_float_operand(
            builder,
            instruction.value,
            target_float_register="xmm0",
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        builder.instruction("movq", format_stack_slot_operand("rcx", field_slot.offset), "xmm0")
        return
    emit_load_operand(
        builder,
        instruction.value,
        target_register="rax",
        target_byte_register="al",
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("mov", format_stack_slot_operand("rcx", field_slot.offset), "rax")


def emit_null_check_instruction(
    builder: X86AsmBuilder,
    instruction: BackendNullCheckInst,
    *,
    callable_label: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    non_null_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_nonnull"
    emit_load_operand(
        builder,
        instruction.value,
        target_register="rax",
        target_byte_register="al",
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("test", "rax", "rax")
    builder.instruction("jne", non_null_label)
    builder.instruction("call", "rt_panic_null_deref")
    builder.label(non_null_label)


def emit_program_metadata_sections(builder: X86AsmBuilder, *, program_context: BackendProgramContext) -> None:
    metadata = program_context.metadata
    if not metadata.classes and not metadata.interfaces and not metadata.extra_runtime_types and not metadata.data_blobs:
        return

    readonly_blobs = tuple(blob for blob in metadata.data_blobs if blob.readonly)
    writable_blobs = tuple(blob for blob in metadata.data_blobs if not blob.readonly)

    builder.blank()
    builder.directive(".section .rodata")
    for class_record in metadata.classes:
        for alias in class_record.aliases:
            builder.label(mangle_type_name_symbol(alias))
        builder.directive(f'.asciz "{_escape_c_string(class_record.display_name)}"')
    for runtime_type in metadata.extra_runtime_types:
        for alias in runtime_type.aliases:
            builder.label(mangle_type_name_symbol(alias))
        builder.directive(f'.asciz "{_escape_c_string(runtime_type.display_name)}"')
    for interface_record in metadata.interfaces:
        builder.label(interface_record.name_symbol)
        builder.directive(f'.asciz "{_escape_c_string(interface_record.display_name)}"')
    for class_record in metadata.classes:
        if class_record.pointer_offsets_symbol is None:
            continue
        _emit_alignment(builder, 8)
        builder.label(class_record.pointer_offsets_symbol)
        for offset in class_record.pointer_offsets:
            builder.directive(f".long {offset}")
    for blob in readonly_blobs:
        _emit_blob(builder, blob)

    builder.blank()
    builder.directive(".data")
    for blob in writable_blobs:
        _emit_blob(builder, blob)
    for interface_record in metadata.interfaces:
        _emit_alignment(builder, 8)
        builder.label(interface_record.descriptor_symbol)
        builder.directive(f".quad {interface_record.name_symbol}")
        builder.directive(f".long {interface_record.slot_index}")
        builder.directive(f".long {interface_record.method_count}")
        builder.directive(".long 0")
    for class_record in metadata.classes:
        for interface_method_table in class_record.interface_method_tables:
            _emit_alignment(builder, 8)
            builder.label(interface_method_table.method_table_symbol)
            for method_label in interface_method_table.method_labels:
                builder.directive(f".quad {method_label}")
        if class_record.interface_tables_symbol is not None:
            _emit_alignment(builder, 8)
            builder.label(class_record.interface_tables_symbol)
            for entry in class_record.interface_table_entries:
                builder.directive(f".quad {entry or '0'}")
    for class_record in metadata.classes:
        if class_record.class_vtable_symbol is None:
            continue
        _emit_alignment(builder, 8)
        builder.label(class_record.class_vtable_symbol)
        for method_label in class_record.class_vtable_labels:
            builder.directive(f".quad {method_label}")
    for class_record in metadata.classes:
        _emit_alignment(builder, 8)
        for alias in class_record.aliases:
            builder.label(mangle_type_symbol(alias))
        _emit_rt_type_record(
            builder,
            flags=RT_TYPE_FLAG_HAS_REFS if class_record.pointer_offsets else 0,
            name_symbol=class_record.type_name_symbol,
            pointer_offsets_symbol=class_record.pointer_offsets_symbol,
            pointer_offsets_count=len(class_record.pointer_offsets),
            super_type_symbol=class_record.superclass_symbol,
            interface_tables_symbol=class_record.interface_tables_symbol,
            interface_slot_count=class_record.interface_table_slot_count,
            class_vtable_symbol=class_record.class_vtable_symbol,
            class_vtable_count=len(class_record.class_vtable_labels),
        )
    for runtime_type in metadata.extra_runtime_types:
        _emit_alignment(builder, 8)
        for alias in runtime_type.aliases:
            builder.label(mangle_type_symbol(alias))
        _emit_rt_type_record(
            builder,
            flags=0,
            name_symbol=runtime_type.type_name_symbol,
            pointer_offsets_symbol=None,
            pointer_offsets_count=0,
            super_type_symbol=None,
            interface_tables_symbol=None,
            interface_slot_count=0,
            class_vtable_symbol=None,
            class_vtable_count=0,
        )


def _field_slot(program_context: BackendProgramContext, owner_class_id, field_name: str):
    for field_slot in program_context.class_hierarchy.effective_field_slots(owner_class_id):
        if field_slot.field_name == field_name:
            return field_slot
    raise BackendTargetLoweringError(
        f"x86_64_sysv backend program context is missing field layout for '{owner_class_id.name}.{field_name}'"
    )


def _emit_alignment(builder: X86AsmBuilder, alignment_bytes: int) -> None:
    if alignment_bytes <= 0 or alignment_bytes & (alignment_bytes - 1):
        raise ValueError("alignment bytes must be a positive power of two")
    builder.directive(f".p2align {alignment_bytes.bit_length() - 1}")


def _emit_blob(builder: X86AsmBuilder, blob) -> None:
    _emit_alignment(builder, blob.alignment)
    builder.label(blob.symbol)
    if blob.byte_length == 0:
        builder.directive(".byte 0")
        return
    byte_values = ", ".join(f"0x{blob.bytes_hex[index:index + 2]}" for index in range(0, len(blob.bytes_hex), 2))
    builder.directive(f".byte {byte_values}")


def _emit_rt_type_record(
    builder: X86AsmBuilder,
    *,
    flags: int,
    name_symbol: str,
    pointer_offsets_symbol: str | None,
    pointer_offsets_count: int,
    super_type_symbol: str | None,
    interface_tables_symbol: str | None,
    interface_slot_count: int,
    class_vtable_symbol: str | None,
    class_vtable_count: int,
) -> None:
    builder.directive(".long 0")
    builder.directive(f".long {flags}")
    builder.directive(".long 1")
    builder.directive(".long 8")
    builder.directive(".quad 0")
    builder.directive(f".quad {name_symbol}")
    builder.directive(".quad 0")
    builder.directive(f".quad {pointer_offsets_symbol or '0'}")
    builder.directive(f".long {pointer_offsets_count}")
    builder.directive(".long 0")
    builder.directive(f".quad {super_type_symbol or '0'}")
    builder.directive(f".quad {interface_tables_symbol or '0'}")
    builder.directive(f".long {interface_slot_count}")
    builder.directive(".long 0")
    builder.directive(f".quad {class_vtable_symbol or '0'}")
    builder.directive(f".long {class_vtable_count}")
    builder.directive(".long 0")


def _escape_c_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


__all__ = [
    "emit_alloc_object_instruction",
    "emit_field_load_instruction",
    "emit_field_store_instruction",
    "emit_null_check_instruction",
    "emit_program_metadata_sections",
]