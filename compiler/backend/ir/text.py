"""Deterministic human-readable text dump helpers for backend IR phase-1 work."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping

from compiler.backend.ir import model as ir_model
from compiler.backend.ir._ordering import (
    block_id_sort_key,
    block_sort_key,
    callable_id_sort_key,
    class_id_sort_key,
    data_blob_sort_key,
    inst_id_sort_key,
    instruction_sort_key,
    interface_id_sort_key,
    interface_method_id_sort_key,
    reg_id_sort_key,
    register_sort_key,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_UNIT
from compiler.semantic.types import SemanticTypeRef, semantic_type_display_name


_ARRAY_RUNTIME_KIND_TO_TEXT = {
    ArrayRuntimeKind.I64: "i64",
    ArrayRuntimeKind.U64: "u64",
    ArrayRuntimeKind.U8: "u8",
    ArrayRuntimeKind.BOOL: "bool",
    ArrayRuntimeKind.DOUBLE: "double",
    ArrayRuntimeKind.REF: "ref",
}


def dump_backend_program_text(
    program: ir_model.BackendProgram,
    *,
    analysis_by_callable: Mapping[
        ir_model.BackendCallableId, ir_model.BackendFunctionAnalysisDump
    ]
    | None = None,
    preserve_block_order: bool = False,
) -> str:
    analysis_lookup = {} if analysis_by_callable is None else analysis_by_callable
    sections = [f"backend_ir {program.schema_version} entry={_format_function_id(program.entry_callable_id)}"]

    data_section = _format_data_section(program.data_blobs)
    if data_section is not None:
        sections.append(data_section)

    interfaces_section = _format_interfaces_section(program.interfaces)
    if interfaces_section is not None:
        sections.append(interfaces_section)

    classes_section = _format_classes_section(program.classes)
    if classes_section is not None:
        sections.append(classes_section)

    for callable_decl in sorted(program.callables, key=lambda decl: callable_id_sort_key(decl.callable_id)):
        sections.append(
            "\n".join(
                _format_callable_lines(
                    callable_decl,
                    analysis_dump=analysis_lookup.get(callable_decl.callable_id),
                    preserve_block_order=preserve_block_order,
                )
            )
        )

    return "\n\n".join(section for section in sections if section)


def _format_data_section(data_blobs: tuple[ir_model.BackendDataBlob, ...]) -> str | None:
    if not data_blobs:
        return None

    lines = ["data:"]
    for blob in sorted(data_blobs, key=data_blob_sort_key):
        readonly_text = "readonly" if blob.readonly else "mutable"
        lines.append(
            f"  {_format_data_id(blob.data_id)} {json.dumps(blob.debug_name)} "
            f"align={blob.alignment} {readonly_text} bytes={blob.bytes_hex}"
        )
    return "\n".join(lines)


def _format_interfaces_section(interfaces: tuple[ir_model.BackendInterfaceDecl, ...]) -> str | None:
    if not interfaces:
        return None

    lines = ["interfaces:"]
    for interface_decl in sorted(interfaces, key=lambda decl: interface_id_sort_key(decl.interface_id)):
        lines.extend(_format_interface_decl_lines(interface_decl))
    return "\n".join(lines)


def _format_interface_decl_lines(interface_decl: ir_model.BackendInterfaceDecl) -> list[str]:
    lines = [f"  interface {_format_interface_id(interface_decl.interface_id)}"]
    if interface_decl.methods:
        lines.append("    methods:")
        for method_id in sorted(interface_decl.methods, key=interface_method_id_sort_key):
            lines.append(f"      {_format_interface_method_id(method_id)}")
    return lines


def _format_classes_section(classes: tuple[ir_model.BackendClassDecl, ...]) -> str | None:
    if not classes:
        return None

    lines = ["classes:"]
    for class_decl in sorted(classes, key=lambda decl: class_id_sort_key(decl.class_id)):
        lines.extend(_format_class_decl_lines(class_decl))
    return "\n".join(lines)


def _format_class_decl_lines(class_decl: ir_model.BackendClassDecl) -> list[str]:
    header = f"  class {_format_class_id(class_decl.class_id)}"
    if class_decl.superclass_id is not None:
        header += f" extends {_format_class_id(class_decl.superclass_id)}"
    if class_decl.implemented_interfaces:
        implemented = ", ".join(
            _format_interface_id(interface_id)
            for interface_id in sorted(class_decl.implemented_interfaces, key=interface_id_sort_key)
        )
        header += f" implements {implemented}"

    lines = [header]
    if class_decl.fields:
        lines.append("    fields:")
        for field_decl in class_decl.fields:
            modifiers = []
            if field_decl.is_private:
                modifiers.append("private")
            if field_decl.is_final:
                modifiers.append("final")
            prefix = f"{' '.join(modifiers)} " if modifiers else ""
            lines.append(
                f"      {prefix}{field_decl.name}: {_format_type(field_decl.type_ref)}"
            )
    if class_decl.methods:
        lines.append("    methods:")
        for method_id in sorted(class_decl.methods, key=callable_id_sort_key):
            lines.append(f"      {_format_method_id(method_id)}")
    if class_decl.constructors:
        lines.append("    constructors:")
        for constructor_id in sorted(class_decl.constructors, key=callable_id_sort_key):
            lines.append(f"      {_format_constructor_id(constructor_id)}")
    return lines


def _format_callable_lines(
    callable_decl: ir_model.BackendCallableDecl,
    *,
    analysis_dump: ir_model.BackendFunctionAnalysisDump | None,
    preserve_block_order: bool,
) -> list[str]:
    register_lookup = {register.reg_id: register for register in callable_decl.registers}
    lines = [_format_callable_header(callable_decl, register_lookup)]
    lines.append("  regs:")

    registers = sorted(callable_decl.registers, key=register_sort_key)
    if registers:
        for register in registers:
            lines.append(f"    {_format_register(register)}")
    else:
        lines.append("    <none>")

    blocks = list(callable_decl.blocks) if preserve_block_order else sorted(callable_decl.blocks, key=block_sort_key)
    if blocks:
        lines.append("")
        for index, block in enumerate(blocks):
            if index > 0:
                lines.append("")
            lines.extend(_format_block_lines(block))

    if analysis_dump is not None:
        lines.append("")
        lines.extend(_format_analysis_lines(analysis_dump))

    lines.append("}")
    return lines


def _format_callable_header(
    callable_decl: ir_model.BackendCallableDecl,
    register_lookup: Mapping[ir_model.BackendRegId, ir_model.BackendRegister],
) -> str:
    modifiers: list[str] = []
    if callable_decl.is_extern:
        modifiers.append("extern")
    if callable_decl.is_export:
        modifiers.append("export")
    if callable_decl.is_static:
        modifiers.append("static")
    if callable_decl.is_private:
        modifiers.append("private")

    callable_kind = "func" if callable_decl.kind == "function" else callable_decl.kind
    header_prefix = f"{' '.join(modifiers)} {callable_kind}" if modifiers else callable_kind
    params_text = _format_callable_params(callable_decl, register_lookup)
    return (
        f"{header_prefix} {_format_callable_id(callable_decl.callable_id)}({params_text}) "
        f"-> {_format_return_type(callable_decl.signature.return_type)} {{"
    )


def _format_callable_params(
    callable_decl: ir_model.BackendCallableDecl,
    register_lookup: Mapping[ir_model.BackendRegId, ir_model.BackendRegister],
) -> str:
    parts: list[str] = []
    if callable_decl.receiver_reg is not None:
        parts.append(
            f"receiver={_format_reg_id(callable_decl.receiver_reg)}: "
            f"{_lookup_register_type_name(register_lookup, callable_decl.receiver_reg)}"
        )

    for index, reg_id in enumerate(sorted(callable_decl.param_regs, key=reg_id_sort_key)):
        fallback_type = callable_decl.signature.param_types[index] if index < len(callable_decl.signature.param_types) else None
        parts.append(
            f"{_format_reg_id(reg_id)}: {_lookup_register_type_name(register_lookup, reg_id, fallback_type)}"
        )
    return ", ".join(parts)


def _lookup_register_type_name(
    register_lookup: Mapping[ir_model.BackendRegId, ir_model.BackendRegister],
    reg_id: ir_model.BackendRegId,
    fallback_type: SemanticTypeRef | None = None,
) -> str:
    register = register_lookup.get(reg_id)
    if register is not None:
        return _format_type(register.type_ref)
    if fallback_type is not None:
        return _format_type(fallback_type)
    return "<?>"


def _format_register(register: ir_model.BackendRegister) -> str:
    debug_name = f" {register.debug_name}" if register.debug_name else ""
    return (
        f"{_format_reg_id(register.reg_id)} {register.origin_kind}{debug_name}: "
        f"{_format_type(register.type_ref)}"
    )


def _format_block_lines(block: ir_model.BackendBlock) -> list[str]:
    lines = [f"  {_format_block_id(block.block_id)} {block.debug_name}:"]
    for instruction in sorted(block.instructions, key=instruction_sort_key):
        lines.append(f"    {_format_instruction(instruction)}")
    lines.append(f"    {_format_terminator(block.terminator)}")
    return lines


def _format_instruction(instruction: ir_model.BackendInstruction) -> str:
    inst_prefix = f"{_format_inst_id(instruction.inst_id)} "
    if isinstance(instruction, ir_model.BackendConstInst):
        return f"{inst_prefix}{_format_reg_id(instruction.dest)} = {_format_constant(instruction.constant)}"
    if isinstance(instruction, ir_model.BackendCopyInst):
        return f"{inst_prefix}{_format_reg_id(instruction.dest)} = copy {_format_operand(instruction.source)}"
    if isinstance(instruction, ir_model.BackendUnaryInst):
        op_name = f"unary.{instruction.op.kind.value}.{instruction.op.flavor.value}"
        return f"{inst_prefix}{_format_reg_id(instruction.dest)} = {op_name} {_format_operand(instruction.operand)}"
    if isinstance(instruction, ir_model.BackendBinaryInst):
        op_name = f"binary.{instruction.op.kind.value}.{instruction.op.flavor.value}"
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = {op_name} "
            f"{_format_operand(instruction.left)}, {_format_operand(instruction.right)}"
        )
    if isinstance(instruction, ir_model.BackendCastInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = cast.{instruction.cast_kind.value} "
            f"{_format_operand(instruction.operand)} -> {_format_type(instruction.target_type_ref)} "
            f"trap_on_failure={str(instruction.trap_on_failure).lower()}"
        )
    if isinstance(instruction, ir_model.BackendTypeTestInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = type_test.{instruction.test_kind.value} "
            f"{_format_operand(instruction.operand)} against {_format_type(instruction.target_type_ref)}"
        )
    if isinstance(instruction, ir_model.BackendAllocObjectInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = alloc_object "
            f"{_format_class_id(instruction.class_id)} {_format_effects(instruction.effects)}"
        )
    if isinstance(instruction, ir_model.BackendFieldLoadInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = field_load "
            f"{_format_operand(instruction.object_ref)} {_format_class_id(instruction.owner_class_id)}.{instruction.field_name}"
        )
    if isinstance(instruction, ir_model.BackendFieldStoreInst):
        return (
            f"{inst_prefix}field_store {instruction.field_name} on {_format_operand(instruction.object_ref)} "
            f"via {_format_class_id(instruction.owner_class_id)} <- {_format_operand(instruction.value)}"
        )
    if isinstance(instruction, ir_model.BackendArrayAllocInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = array_alloc."
            f"{_format_array_runtime_kind(instruction.array_runtime_kind)} {_format_operand(instruction.length)} "
            f"{_format_effects(instruction.effects)}"
        )
    if isinstance(instruction, ir_model.BackendArrayLengthInst):
        return f"{inst_prefix}{_format_reg_id(instruction.dest)} = array_len {_format_operand(instruction.array_ref)}"
    if isinstance(instruction, ir_model.BackendArrayLoadInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = array_load."
            f"{_format_array_runtime_kind(instruction.array_runtime_kind)} "
            f"{_format_operand(instruction.array_ref)}[{_format_operand(instruction.index)}]"
        )
    if isinstance(instruction, ir_model.BackendArrayStoreInst):
        return (
            f"{inst_prefix}array_store.{_format_array_runtime_kind(instruction.array_runtime_kind)} "
            f"{_format_operand(instruction.array_ref)}[{_format_operand(instruction.index)}] <- "
            f"{_format_operand(instruction.value)}"
        )
    if isinstance(instruction, ir_model.BackendArraySliceInst):
        return (
            f"{inst_prefix}{_format_reg_id(instruction.dest)} = array_slice."
            f"{_format_array_runtime_kind(instruction.array_runtime_kind)} "
            f"{_format_operand(instruction.array_ref)}[{_format_operand(instruction.begin)}:{_format_operand(instruction.end)}] "
            f"{_format_effects(instruction.effects)}"
        )
    if isinstance(instruction, ir_model.BackendArraySliceStoreInst):
        return (
            f"{inst_prefix}array_slice_store.{_format_array_runtime_kind(instruction.array_runtime_kind)} "
            f"{_format_operand(instruction.array_ref)}[{_format_operand(instruction.begin)}:{_format_operand(instruction.end)}] <- "
            f"{_format_operand(instruction.value)}"
        )
    if isinstance(instruction, ir_model.BackendNullCheckInst):
        return f"{inst_prefix}null_check {_format_operand(instruction.value)}"
    if isinstance(instruction, ir_model.BackendBoundsCheckInst):
        return (
            f"{inst_prefix}bounds_check {_format_operand(instruction.array_ref)}, "
            f"{_format_operand(instruction.index)}"
        )
    if isinstance(instruction, ir_model.BackendCallInst):
        target_text = _format_call_target(instruction.target)
        args_text = ", ".join(_format_operand(argument) for argument in instruction.args)
        dest_text = "" if instruction.dest is None else f"{_format_reg_id(instruction.dest)} = "
        return (
            f"{inst_prefix}{dest_text}call {target_text}({args_text}) "
            f"sig={_format_signature(instruction.signature)} {_format_effects(instruction.effects)}"
        )
    raise TypeError(f"Unsupported backend instruction type: {type(instruction).__name__}")


def _format_terminator(terminator: ir_model.BackendTerminator) -> str:
    if isinstance(terminator, ir_model.BackendJumpTerminator):
        return f"jump {_format_block_id(terminator.target_block_id)}"
    if isinstance(terminator, ir_model.BackendBranchTerminator):
        return (
            f"branch {_format_operand(terminator.condition)} ? {_format_block_id(terminator.true_block_id)} : "
            f"{_format_block_id(terminator.false_block_id)}"
        )
    if isinstance(terminator, ir_model.BackendReturnTerminator):
        return "ret" if terminator.value is None else f"ret {_format_operand(terminator.value)}"
    if isinstance(terminator, ir_model.BackendTrapTerminator):
        message = "" if terminator.message is None else f" {json.dumps(terminator.message)}"
        return f"trap {terminator.trap_kind}{message}"
    raise TypeError(f"Unsupported backend terminator type: {type(terminator).__name__}")


def _format_call_target(target: ir_model.BackendCallTarget) -> str:
    if isinstance(target, ir_model.BackendDirectCallTarget):
        return f"direct {_format_callable_id(target.callable_id)}"
    if isinstance(target, ir_model.BackendRuntimeCallTarget):
        ref_args = ", ".join(str(index) for index in target.ref_arg_indices)
        return f"runtime {target.name} ref_args=[{ref_args}]"
    if isinstance(target, ir_model.BackendIndirectCallTarget):
        return f"indirect {_format_operand(target.callee)}"
    if isinstance(target, ir_model.BackendVirtualCallTarget):
        return (
            f"virtual slot_owner={_format_class_id(target.slot_owner_class_id)} "
            f"method={target.method_name} selected={_format_method_id(target.selected_method_id)}"
        )
    if isinstance(target, ir_model.BackendInterfaceCallTarget):
        return f"interface {_format_interface_method_id(target.method_id)}"
    raise TypeError(f"Unsupported backend call target type: {type(target).__name__}")


def _format_operand(operand: ir_model.BackendOperand) -> str:
    if isinstance(operand, ir_model.BackendRegOperand):
        return _format_reg_id(operand.reg_id)
    if isinstance(operand, ir_model.BackendConstOperand):
        return _format_constant(operand.constant)
    if isinstance(operand, ir_model.BackendDataOperand):
        return _format_data_id(operand.data_id)
    raise TypeError(f"Unsupported backend operand type: {type(operand).__name__}")


def _format_constant(constant: ir_model.BackendConstant) -> str:
    if isinstance(constant, ir_model.BackendIntConst):
        return f"const.{constant.type_name} {constant.value}"
    if isinstance(constant, ir_model.BackendBoolConst):
        return f"const.bool {str(constant.value).lower()}"
    if isinstance(constant, ir_model.BackendDoubleConst):
        bits_hex = f"{_double_value_bits(constant.value):016x}"
        return f"const.double bits=0x{bits_hex}"
    if isinstance(constant, ir_model.BackendNullConst):
        return "const.null"
    if isinstance(constant, ir_model.BackendUnitConst):
        return "const.unit"
    raise TypeError(f"Unsupported backend constant type: {type(constant).__name__}")


def _format_effects(effects: ir_model.BackendEffects) -> str:
    active_effects: list[str] = []
    if effects.reads_memory:
        active_effects.append("reads_memory")
    if effects.writes_memory:
        active_effects.append("writes_memory")
    if effects.may_gc:
        active_effects.append("may_gc")
    if effects.may_trap:
        active_effects.append("may_trap")
    if effects.is_noreturn:
        active_effects.append("is_noreturn")
    if effects.needs_safepoint_hooks:
        active_effects.append("needs_safepoint_hooks")
    if not active_effects:
        active_effects.append("none")
    return f"effects[{', '.join(active_effects)}]"


def _format_signature(signature: ir_model.BackendSignature) -> str:
    params = ", ".join(_format_type(param_type) for param_type in signature.param_types)
    return f"({params}) -> {_format_return_type(signature.return_type)}"


def _format_type(type_ref: SemanticTypeRef) -> str:
    return semantic_type_display_name(type_ref)


def _format_return_type(type_ref: SemanticTypeRef | None) -> str:
    return TYPE_NAME_UNIT if type_ref is None else _format_type(type_ref)


def _format_analysis_lines(analysis_dump: ir_model.BackendFunctionAnalysisDump) -> list[str]:
    lines = ["  analysis:"]
    lines.extend(
        _format_mapping_section(
            title="predecessors",
            mapping=analysis_dump.predecessors,
            key_formatter=_format_block_id,
            key_sort_key=block_id_sort_key,
            value_formatter=_format_block_id_list,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="successors",
            mapping=analysis_dump.successors,
            key_formatter=_format_block_id,
            key_sort_key=block_id_sort_key,
            value_formatter=_format_block_id_list,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="live_in",
            mapping=analysis_dump.live_in,
            key_formatter=_format_block_id,
            key_sort_key=block_id_sort_key,
            value_formatter=_format_reg_id_list,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="live_out",
            mapping=analysis_dump.live_out,
            key_formatter=_format_block_id,
            key_sort_key=block_id_sort_key,
            value_formatter=_format_reg_id_list,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="safepoint_live_regs",
            mapping=analysis_dump.safepoint_live_regs,
            key_formatter=_format_inst_id,
            key_sort_key=inst_id_sort_key,
            value_formatter=_format_reg_id_list,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="root_slot_by_reg",
            mapping=analysis_dump.root_slot_by_reg,
            key_formatter=_format_reg_id,
            key_sort_key=reg_id_sort_key,
            value_formatter=str,
        )
    )
    lines.extend(
        _format_mapping_section(
            title="stack_home_by_reg",
            mapping=analysis_dump.stack_home_by_reg,
            key_formatter=_format_reg_id,
            key_sort_key=reg_id_sort_key,
            value_formatter=str,
        )
    )
    return lines


def _format_mapping_section(title: str, mapping, key_formatter, key_sort_key, value_formatter) -> list[str]:
    lines = [f"    {title}:"]
    if not mapping:
        lines.append("      <none>")
        return lines
    for key in sorted(mapping, key=key_sort_key):
        lines.append(f"      {key_formatter(key)}: {value_formatter(mapping[key])}")
    return lines


def _format_reg_id_list(reg_ids: tuple[ir_model.BackendRegId, ...]) -> str:
    return f"[{', '.join(_format_reg_id(reg_id) for reg_id in sorted(reg_ids, key=reg_id_sort_key))}]"


def _format_block_id_list(block_ids: tuple[ir_model.BackendBlockId, ...]) -> str:
    return f"[{', '.join(_format_block_id(block_id) for block_id in sorted(block_ids, key=block_id_sort_key))}]"


def _format_callable_id(callable_id: ir_model.BackendCallableId) -> str:
    if isinstance(callable_id, ir_model.FunctionId):
        return _format_function_id(callable_id)
    if isinstance(callable_id, ir_model.MethodId):
        return _format_method_id(callable_id)
    return _format_constructor_id(callable_id)


def _format_function_id(function_id: ir_model.FunctionId) -> str:
    return f"{_format_module_path(function_id.module_path)}::{function_id.name}"


def _format_method_id(method_id: ir_model.MethodId) -> str:
    return f"{_format_class_owner(method_id.module_path, method_id.class_name)}.{method_id.name}"


def _format_constructor_id(constructor_id: ir_model.ConstructorId) -> str:
    return f"{_format_class_owner(constructor_id.module_path, constructor_id.class_name)}#{constructor_id.ordinal}"


def _format_class_owner(module_path: tuple[str, ...], class_name: str) -> str:
    return f"{_format_module_path(module_path)}::{class_name}"


def _format_class_id(class_id: ir_model.ClassId) -> str:
    return _format_class_owner(class_id.module_path, class_id.name)


def _format_interface_id(interface_id: ir_model.InterfaceId) -> str:
    return f"{_format_module_path(interface_id.module_path)}::{interface_id.name}"


def _format_interface_method_id(method_id: ir_model.InterfaceMethodId) -> str:
    return f"{_format_module_path(method_id.module_path)}::{method_id.interface_name}.{method_id.name}"


def _format_module_path(module_path: tuple[str, ...]) -> str:
    return ".".join(module_path) if module_path else "<root>"


def _format_reg_id(reg_id: ir_model.BackendRegId) -> str:
    return f"r{reg_id.ordinal}"


def _format_block_id(block_id: ir_model.BackendBlockId) -> str:
    return f"b{block_id.ordinal}"


def _format_inst_id(inst_id: ir_model.BackendInstId) -> str:
    return f"i{inst_id.ordinal}"


def _format_data_id(data_id: ir_model.BackendDataId) -> str:
    return f"d{data_id.ordinal}"


def _format_array_runtime_kind(runtime_kind: ArrayRuntimeKind) -> str:
    return _ARRAY_RUNTIME_KIND_TO_TEXT[runtime_kind]


def _double_value_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


__all__ = ["dump_backend_program_text"]