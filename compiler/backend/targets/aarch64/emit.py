from __future__ import annotations

import os
from pathlib import Path

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBranchTerminator,
    BackendCallInst,
    BackendConstInst,
    BackendCopyInst,
    BackendDirectCallTarget,
    BackendIndirectCallTarget,
    BackendJumpTerminator,
    BackendReturnTerminator,
    BackendRuntimeCallTarget,
    BackendUnaryInst,
)
from compiler.backend.program.symbols import epilogue_label
from compiler.backend.targets import (
    BackendEmitResult,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
)
from compiler.backend.targets.aarch64.abi import AARCH64_ABI
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.aarch64.frame import plan_callable_frame_layout
from compiler.backend.targets.aarch64.instruction_selection import (
    emit_branch_terminator,
    emit_instruction,
    emit_jump_terminator,
    emit_return_terminator,
    register_type_name_by_reg_id,
)
from compiler.backend.targets.aarch64.lower_calls import emit_call_instruction as emit_lowered_call_instruction
from compiler.backend.targets.aarch64.root_codegen import (
    emit_root_frame_pop,
    emit_root_frame_setup,
    emit_root_slot_reload,
    emit_root_slot_sync,
    emit_zero_root_slots,
)
from compiler.backend.targets.aarch64.trace_codegen import (
    TraceDebugRecord,
    emit_trace_debug_literals,
    emit_trace_location,
    emit_trace_pop,
    emit_trace_push,
)
from compiler.semantic.symbols import ConstructorId, FunctionId, MethodId
from compiler.semantic.types import semantic_type_canonical_name


TARGET_NAME = "aarch64"


class AArch64LegalityError(BackendTargetLoweringError):
    """Raised when backend IR falls outside the current AArch64 target scaffold."""


class AArch64Target:
    name = TARGET_NAME

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
        return emit_aarch64_asm(target_input, options=options)


def emit_aarch64_asm(target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
    check_aarch64_legality(target_input)

    builder = AArch64AsmBuilder(emit_debug_comments=options.emit_debug_comments)
    callable_by_id = {callable_decl.callable_id: callable_decl for callable_decl in target_input.program.callables}
    trace_records: list[TraceDebugRecord] = []
    source_root = _common_source_root(target_input)
    builder.blank()
    builder.directive(".text")

    for callable_decl in target_input.program.callables:
        if callable_decl.is_extern:
            continue
        if callable_decl.kind == "constructor":
            raise AArch64LegalityError("aarch64 constructor entry wrappers land in the later object slice")
        builder.blank()
        frame_layout = plan_callable_frame_layout(target_input, callable_decl)
        trace_record = (
            _trace_record_for_callable(target_input, callable_decl, source_root=source_root)
            if options.runtime_trace_enabled
            else None
        )
        if trace_record is not None:
            trace_records.append(trace_record)
        _emit_callable_body(
            builder,
            callable_decl,
            target_input=target_input,
            options=options,
            frame_layout=frame_layout,
            ordered_block_ids=target_input.analysis_for_callable(callable_decl.callable_id).ordered_block_ids,
            callable_by_id=callable_by_id,
            emit_debug_comments=options.emit_debug_comments,
            trace_record=trace_record,
            runtime_trace_enabled=options.runtime_trace_enabled,
        )

    emit_trace_debug_literals(builder, records=tuple(trace_records))

    builder.blank()
    builder.directive('.section .note.GNU-stack,"",@progbits')
    builder.blank()
    return BackendEmitResult(assembly_text=builder.build(), diagnostics=())


def check_aarch64_legality(target_input: BackendTargetInput) -> None:
    for callable_decl in target_input.program.callables:
        _check_callable_shape(callable_decl)
        _check_callable_signature(callable_decl)
        _check_callable_register_types(callable_decl)
        target_input.analysis_for_callable(callable_decl.callable_id)
        for block in callable_decl.blocks:
            for instruction in block.instructions:
                _check_instruction_legality(callable_decl, block, instruction)


def _check_callable_shape(callable_decl) -> None:
    if callable_decl.kind == "function":
        if callable_decl.receiver_reg is not None:
            raise AArch64LegalityError("functions must not declare a receiver register")
        return
    if callable_decl.kind == "method":
        if callable_decl.is_static is True and callable_decl.receiver_reg is None:
            return
        if callable_decl.is_static is False and callable_decl.receiver_reg is not None:
            return
        raise AArch64LegalityError("methods must either be static without a receiver or instance methods with one")
    if callable_decl.kind == "constructor":
        if callable_decl.receiver_reg is None:
            raise AArch64LegalityError("constructors must declare a receiver register")
        return
    raise AArch64LegalityError(f"unsupported callable kind '{callable_decl.kind}'")


def _check_callable_signature(callable_decl) -> None:
    for param_type in callable_decl.signature.param_types:
        if not AARCH64_ABI.supports_passed_type(param_type):
            raise AArch64LegalityError(
                f"unsupported aarch64 parameter type '{param_type.display_name}'"
            )
    if not AARCH64_ABI.supports_passed_type(callable_decl.signature.return_type):
        assert callable_decl.signature.return_type is not None
        raise AArch64LegalityError(
            f"unsupported aarch64 return type '{callable_decl.signature.return_type.display_name}'"
        )


def _check_callable_register_types(callable_decl) -> None:
    for register in callable_decl.registers:
        if not AARCH64_ABI.supports_passed_type(register.type_ref):
            raise AArch64LegalityError(
                f"register 'r{register.reg_id.ordinal}' uses unsupported aarch64 type '{register.type_ref.display_name}'"
            )


def _check_instruction_legality(callable_decl, block: BackendBlock, instruction: object) -> None:
    if isinstance(instruction, (BackendConstInst, BackendCopyInst, BackendUnaryInst, BackendBinaryInst)):
        return
    if isinstance(instruction, BackendCallInst):
        if not isinstance(
            instruction.target,
            (BackendDirectCallTarget, BackendRuntimeCallTarget, BackendIndirectCallTarget),
        ):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call target '{type(instruction.target).__name__}' is not supported before the dispatch slices land",
            )
        for param_type in instruction.signature.param_types:
            if not AARCH64_ABI.supports_passed_type(param_type):
                _instruction_error(
                    callable_decl,
                    block,
                    instruction,
                    f"call parameter type '{param_type.display_name}' is not supported in aarch64",
                )
        if not AARCH64_ABI.supports_passed_type(instruction.signature.return_type):
            assert instruction.signature.return_type is not None
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call return type '{instruction.signature.return_type.display_name}' is not supported in aarch64",
            )
        return
    _instruction_error(
        callable_decl,
        block,
        instruction,
        f"instruction '{type(instruction).__name__}' is not supported in slice 4",
    )


def _emit_callable_body(
    builder: AArch64AsmBuilder,
    callable_decl,
    *,
    target_input: BackendTargetInput,
    options: BackendTargetOptions,
    frame_layout,
    ordered_block_ids,
    callable_by_id,
    emit_debug_comments: bool,
    trace_record,
    runtime_trace_enabled: bool,
) -> None:
    del options
    callable_analysis = target_input.analysis_for_callable(callable_decl.callable_id)
    callable_symbols = target_input.program_context.symbols.callable(callable_decl.callable_id)
    if callable_symbols.emitted_label is None:
        raise BackendTargetLoweringError(
            f"aarch64 backend program context is missing an emitted label for '{_format_callable_id(callable_decl.callable_id)}'"
        )
    ordered_blocks = _ordered_blocks_for_callable(callable_decl, ordered_block_ids=ordered_block_ids)
    resolved_type_names = register_type_name_by_reg_id(callable_decl)
    target_label = callable_symbols.emitted_label
    callable_label_for_calls = callable_symbols.emitted_label or callable_symbols.direct_call_symbol
    block_label_by_id = {
        block.block_id: _block_label(target_label, block.block_id.ordinal)
        for block in ordered_blocks
    }

    def emit_safepoint_preamble(instruction: BackendCallInst) -> None:
        if frame_layout.has_root_frame and (instruction.effects.may_gc or instruction.effects.needs_safepoint_hooks):
            live_reg_ids = callable_analysis.safepoints.live_regs_for_instruction(instruction.inst_id)
            emit_root_slot_sync(builder, frame_layout=frame_layout, live_reg_ids=live_reg_ids)

    def emit_safepoint_postamble(instruction: BackendCallInst) -> None:
        if not frame_layout.has_root_frame or not instruction.effects.may_gc:
            return
        live_reg_ids = callable_analysis.safepoints.live_regs_for_instruction(instruction.inst_id)
        emit_root_slot_reload(builder, frame_layout=frame_layout, live_reg_ids=live_reg_ids)

    def emit_call_instruction(instruction: BackendCallInst) -> None:
        if runtime_trace_enabled:
            emit_trace_location(builder, line=instruction.span.start.line, column=instruction.span.start.column)
        emit_lowered_call_instruction(
            builder,
            instruction,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=resolved_type_names,
            callable_decl_by_id=callable_by_id,
            program_symbols=target_input.program_context.symbols,
            callable_label=callable_label_for_calls,
            emit_safepoint_preamble=emit_safepoint_preamble,
            emit_safepoint_postamble=emit_safepoint_postamble,
        )

    if callable_symbols.global_label is not None:
        builder.global_symbol(target_label)
    builder.label(target_label)
    for alias_label in callable_symbols.alias_labels:
        builder.label(alias_label)

    builder.instruction("stp", "x29", "x30", "[sp, #-16]!")
    builder.instruction("mov", "x29", "sp")
    if frame_layout.stack_size > 0:
        builder.instruction("sub", "sp", "sp", f"#{frame_layout.stack_size}")

    _emit_param_spills(builder, callable_decl, frame_layout=frame_layout)
    if frame_layout.has_root_frame:
        emit_zero_root_slots(builder, frame_layout=frame_layout)
        emit_root_frame_setup(builder, frame_layout=frame_layout)
    if runtime_trace_enabled and trace_record is not None:
        emit_trace_push(
            builder,
            trace_record,
            line=callable_decl.span.start.line,
            column=callable_decl.span.start.column,
        )
    if emit_debug_comments:
        for slot in frame_layout.slots:
            builder.comment(f"{slot.home_name} -> {format_stack_slot_operand('x29', slot.byte_offset)}")

    for block in ordered_blocks:
        builder.label(block_label_by_id[block.block_id])
        for instruction in block.instructions:
            emit_instruction(
                builder,
                instruction,
                block=block,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=resolved_type_names,
                call_emitter=emit_call_instruction,
                program_symbols=target_input.program_context.symbols,
            )
        _emit_terminator(
            builder,
            block,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=resolved_type_names,
            block_label_by_id=block_label_by_id,
            epilogue_label_text=epilogue_label(target_label),
            program_symbols=target_input.program_context.symbols,
        )

    builder.label(epilogue_label(target_label))
    _emit_runtime_epilogue_cleanup_preserving_return(
        builder,
        callable_decl,
        frame_layout=frame_layout,
        runtime_trace_enabled=runtime_trace_enabled and trace_record is not None,
    )
    builder.instruction("mov", "sp", "x29")
    builder.instruction("ldp", "x29", "x30", "[sp], #16")
    builder.instruction("ret")


def _emit_terminator(
    builder: AArch64AsmBuilder,
    block: BackendBlock,
    *,
    frame_layout,
    register_type_name_by_reg_id: dict,
    block_label_by_id: dict,
    epilogue_label_text: str,
    program_symbols,
) -> None:
    terminator = block.terminator
    if isinstance(terminator, BackendReturnTerminator):
        emit_return_terminator(
            builder,
            terminator,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            epilogue_label_text=epilogue_label_text,
            program_symbols=program_symbols,
        )
        return
    if isinstance(terminator, BackendJumpTerminator):
        emit_jump_terminator(builder, terminator, target_label=block_label_by_id[terminator.target_block_id])
        return
    if isinstance(terminator, BackendBranchTerminator):
        emit_branch_terminator(
            builder,
            terminator,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            true_label=block_label_by_id[terminator.true_block_id],
            false_label=block_label_by_id[terminator.false_block_id],
        )
        return
    raise BackendTargetLoweringError(
        f"aarch64 terminator '{type(terminator).__name__}' is not supported in slice 4"
    )


def _ordered_blocks_for_callable(callable_decl, *, ordered_block_ids) -> tuple[BackendBlock, ...]:
    block_by_id = {block.block_id: block for block in callable_decl.blocks}
    try:
        return tuple(block_by_id[block_id] for block_id in ordered_block_ids)
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"aarch64 ordered block sequence references undeclared block '{exc.args[0]}'"
        ) from exc


def _block_label(target_label: str, block_ordinal: int) -> str:
    return f".L{target_label}_b{block_ordinal}"


def _emit_param_spills(builder: AArch64AsmBuilder, callable_decl, *, frame_layout) -> None:
    includes_receiver = callable_decl.receiver_reg is not None
    arg_locations = AARCH64_ABI.plan_argument_locations(
        callable_decl.signature.param_types,
        includes_receiver=includes_receiver,
    )
    ordered_arg_regs = callable_decl.param_regs
    if includes_receiver:
        if callable_decl.receiver_reg is None:
            raise BackendTargetLoweringError("aarch64 receiver spills require a receiver register")
        ordered_arg_regs = (callable_decl.receiver_reg, *ordered_arg_regs)
    resolved_type_names = register_type_name_by_reg_id(callable_decl)
    for reg_id, arg_location in zip(ordered_arg_regs, arg_locations, strict=True):
        slot = frame_layout.for_reg(reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 frame layout is missing a home for parameter register 'r{reg_id.ordinal}'"
            )
        stack_operand = format_stack_slot_operand("x29", slot.byte_offset)
        if arg_location.kind == "int_reg":
            assert arg_location.register_name is not None
            builder.instruction("str", arg_location.register_name, stack_operand)
            continue
        if arg_location.kind == "float_reg":
            assert arg_location.register_name is not None
            builder.instruction("str", arg_location.register_name, stack_operand)
            continue
        if arg_location.kind == "stack":
            assert arg_location.stack_slot_index is not None
            incoming_offset = AARCH64_ABI.incoming_stack_arg_byte_offset(arg_location.stack_slot_index)
            if resolved_type_names[reg_id] == "double":
                builder.instruction("ldr", "d16", f"[x29, #{incoming_offset}]")
                builder.instruction("str", "d16", stack_operand)
            else:
                builder.instruction("ldr", "x9", f"[x29, #{incoming_offset}]")
                builder.instruction("str", "x9", stack_operand)
            continue
        raise BackendTargetLoweringError(
            f"aarch64 parameter spill does not support location kind '{arg_location.kind}'"
        )


def _trace_record_for_callable(target_input: BackendTargetInput, callable_decl, *, source_root: Path | None):
    callable_symbols = target_input.program_context.symbols.callable(callable_decl.callable_id)
    if callable_symbols.emitted_label is None:
        return None
    return TraceDebugRecord(
        target_label=callable_symbols.emitted_label,
        function_name=_format_callable_id(callable_decl.callable_id),
        file_path=_normalize_trace_file_path(callable_decl.span.start.path, source_root=source_root),
    )


def _common_source_root(target_input: BackendTargetInput) -> Path | None:
    source_paths = [
        Path(callable_decl.span.start.path)
        for callable_decl in target_input.program.callables
        if callable_decl.span.start.path
    ]
    if not source_paths:
        return None
    try:
        return Path(os.path.commonpath([str(path) for path in source_paths]))
    except ValueError:
        return None


def _normalize_trace_file_path(source_path: str, *, source_root: Path | None) -> str:
    path = Path(source_path)
    if source_root is not None:
        try:
            return path.relative_to(source_root).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _emit_runtime_epilogue_cleanup_preserving_return(
    builder: AArch64AsmBuilder,
    callable_decl,
    *,
    frame_layout,
    runtime_trace_enabled: bool,
) -> None:
    return_type = callable_decl.signature.return_type
    if return_type is None:
        if frame_layout.has_root_frame:
            emit_root_frame_pop(builder, frame_layout=frame_layout)
        if runtime_trace_enabled:
            emit_trace_pop(builder)
        return

    return_type_name = semantic_type_canonical_name(return_type)
    builder.instruction("sub", "sp", "sp", "#16")
    if return_type_name == "double":
        builder.instruction("str", "d0", "[sp]")
    else:
        builder.instruction("str", "x0", "[sp]")
    if frame_layout.has_root_frame:
        emit_root_frame_pop(builder, frame_layout=frame_layout)
    if runtime_trace_enabled:
        emit_trace_pop(builder)
    if return_type_name == "double":
        builder.instruction("ldr", "d0", "[sp]")
    else:
        builder.instruction("ldr", "x0", "[sp]")
    builder.instruction("add", "sp", "sp", "#16")


def _instruction_error(callable_decl, block: BackendBlock, instruction: object, message: str) -> None:
    raise AArch64LegalityError(
        f"{_format_callable_id(callable_decl.callable_id)}:{block.block_id.ordinal}:"
        f"i{getattr(instruction, 'inst_id', '?')} {message}"
    )


def _format_callable_id(callable_id) -> str:
    if isinstance(callable_id, FunctionId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.name}"
    if isinstance(callable_id, MethodId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
    if isinstance(callable_id, ConstructorId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
    raise TypeError(f"Unsupported backend callable ID '{callable_id!r}'")


AARCH64_TARGET = AArch64Target()


__all__ = [
    "AARCH64_TARGET",
    "AArch64LegalityError",
    "AArch64Target",
    "TARGET_NAME",
    "check_aarch64_legality",
    "emit_aarch64_asm",
]