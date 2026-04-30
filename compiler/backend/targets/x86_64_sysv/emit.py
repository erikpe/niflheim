from __future__ import annotations

import os
from pathlib import Path

from compiler.backend.program.symbols import epilogue_label
from compiler.backend.ir import (
    BackendAllocObjectInst,
    BackendArrayAllocInst,
    BackendArrayLengthInst,
    BackendArrayLoadInst,
    BackendArraySliceInst,
    BackendArraySliceStoreInst,
    BackendArrayStoreInst,
    BackendBlock,
    BackendBranchTerminator,
    BackendBoundsCheckInst,
    BackendCallInst,
    BackendCastInst,
    BackendConstOperand,
    BackendDirectCallTarget,
    BackendIndirectCallTarget,
    BackendInterfaceCallTarget,
    BackendRuntimeCallTarget,
    BackendFieldLoadInst,
    BackendFieldStoreInst,
    BackendJumpTerminator,
    BackendNullCheckInst,
    BackendReturnTerminator,
    BackendTypeTestInst,
    BackendVirtualCallTarget,
)
from compiler.backend.targets import (
    BackendEmitResult,
    BackendTarget,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
)
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import plan_callable_frame_layout
from compiler.backend.targets.x86_64_sysv.root_codegen import (
    emit_root_frame_pop,
    emit_root_frame_setup,
    emit_root_slot_reload,
    emit_root_slot_sync,
    emit_zero_root_slots,
)
from compiler.backend.targets.x86_64_sysv.instruction_selection import (
    emit_branch_terminator,
    emit_instruction,
    emit_jump_terminator,
    emit_load_operand,
    emit_return_terminator,
    register_type_name_by_reg_id,
)
from compiler.backend.targets.x86_64_sysv.cast_codegen import (
    emit_array_kind_name_literals,
    emit_cast_instruction,
    emit_type_test_instruction,
)
from compiler.backend.targets.x86_64_sysv.array_codegen import (
    emit_array_alloc_instruction,
    emit_array_length_instruction,
    emit_array_load_instruction,
    emit_array_slice_instruction,
    emit_array_slice_store_instruction,
    emit_array_store_instruction,
    emit_bounds_check_instruction,
)
from compiler.backend.targets.x86_64_sysv.lower_calls import emit_call_instruction as emit_lowered_call_instruction
from compiler.backend.targets.x86_64_sysv.object_codegen import (
    emit_alloc_object_instruction,
    emit_field_load_instruction,
    emit_field_store_instruction,
    emit_null_check_instruction,
    emit_program_metadata_sections,
)
from compiler.backend.targets.x86_64_sysv.trace_codegen import (
    TraceDebugRecord,
    emit_trace_debug_literals,
    emit_trace_location,
    emit_trace_pop,
    emit_trace_push,
)
from compiler.backend.ir import BackendEffects, BackendInstId, BackendRegOperand
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, MethodId
from compiler.semantic.operations import CastSemanticsKind, TypeTestSemanticsKind
from compiler.semantic.types import semantic_type_canonical_name, semantic_type_is_interface, semantic_type_is_reference


TARGET_NAME = "x86_64_sysv"


class X86_64SysVLegalityError(BackendTargetLoweringError):
    """Raised when backend IR falls outside the current x86-64 SysV experimental slice."""


class X86_64SysVTarget:
    name = TARGET_NAME

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
        return emit_x86_64_sysv_asm(target_input, options=options)


def emit_x86_64_sysv_asm(target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
    check_x86_64_sysv_legality(target_input)

    builder = X86AsmBuilder(emit_debug_comments=options.emit_debug_comments)
    callable_by_id = {callable_decl.callable_id: callable_decl for callable_decl in target_input.program.callables}
    trace_records: list[TraceDebugRecord] = []
    source_root = _common_source_root(target_input)
    builder.blank()
    builder.directive(".text")

    for callable_decl in target_input.program.callables:
        if callable_decl.is_extern:
            continue
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
            frame_layout=frame_layout,
            ordered_block_ids=target_input.analysis_for_callable(callable_decl.callable_id).ordered_block_ids,
            callable_by_id=callable_by_id,
            emit_debug_comments=options.emit_debug_comments,
            trace_record=trace_record,
            runtime_trace_enabled=options.runtime_trace_enabled,
        )

    emit_program_metadata_sections(builder, program_context=target_input.program_context)
    emit_array_kind_name_literals(builder)
    emit_trace_debug_literals(builder, records=tuple(trace_records))

    builder.blank()
    builder.directive('.section .note.GNU-stack,"",@progbits')
    builder.blank()
    return BackendEmitResult(assembly_text=builder.build(), diagnostics=())


def check_x86_64_sysv_legality(target_input: BackendTargetInput) -> None:
    for callable_decl in target_input.program.callables:
        _check_callable_shape(callable_decl)
        _check_callable_signature(callable_decl)
        _check_callable_register_types(callable_decl)
        _check_callable_analysis(target_input, callable_decl)
        for block in callable_decl.blocks:
            for instruction in block.instructions:
                _check_instruction_legality(callable_decl, block, instruction)


def _check_callable_shape(callable_decl) -> None:
    if callable_decl.kind == "function":
        if callable_decl.receiver_reg is not None:
            _callable_error(callable_decl, "functions must not declare a receiver register")
        return
    if callable_decl.kind == "method":
        if callable_decl.is_static is True and callable_decl.receiver_reg is None:
            return
        if callable_decl.is_static is False and callable_decl.receiver_reg is not None:
            return
        _callable_error(callable_decl, "methods must either be static without a receiver or instance methods with one")
    if callable_decl.kind == "constructor":
        if callable_decl.receiver_reg is None:
            _callable_error(callable_decl, "constructors must declare a receiver register")
        return


def _check_callable_signature(callable_decl) -> None:
    for param_type in callable_decl.signature.param_types:
        if not X86_64_SYSV_ABI.supports_passed_type(param_type):
            _callable_error(
                callable_decl,
                f"unsupported x86_64_sysv parameter type '{param_type.display_name}'",
            )
    if not X86_64_SYSV_ABI.supports_passed_type(callable_decl.signature.return_type):
        assert callable_decl.signature.return_type is not None
        _callable_error(
            callable_decl,
            f"unsupported x86_64_sysv return type '{callable_decl.signature.return_type.display_name}'",
        )


def _check_callable_register_types(callable_decl) -> None:
    for register in callable_decl.registers:
        if not X86_64_SYSV_ABI.supports_passed_type(register.type_ref):
            _callable_error(
                callable_decl,
                f"register 'r{register.reg_id.ordinal}' uses unsupported x86_64_sysv type '{register.type_ref.display_name}'",
            )


def _check_callable_analysis(target_input: BackendTargetInput, callable_decl) -> None:
    target_input.analysis_for_callable(callable_decl.callable_id)


def _check_instruction_legality(callable_decl, block: BackendBlock, instruction: object) -> None:
    if isinstance(instruction, BackendTypeTestInst):
        _check_type_test_instruction_legality(callable_decl, block, instruction)
        return

    if isinstance(instruction, BackendCastInst):
        _check_cast_instruction_legality(callable_decl, block, instruction)
        return

    if isinstance(instruction, BackendCallInst):
        if not isinstance(
            instruction.target,
            (
                BackendDirectCallTarget,
                BackendRuntimeCallTarget,
                BackendIndirectCallTarget,
                BackendVirtualCallTarget,
                BackendInterfaceCallTarget,
            ),
        ):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call target '{type(instruction.target).__name__}' is not supported before the dispatch slices land",
            )
        for param_type in instruction.signature.param_types:
            if not X86_64_SYSV_ABI.supports_passed_type(param_type):
                _instruction_error(
                    callable_decl,
                    block,
                    instruction,
                    f"call parameter type '{param_type.display_name}' is not supported in x86_64_sysv",
                )
        if not X86_64_SYSV_ABI.supports_passed_type(instruction.signature.return_type):
            assert instruction.signature.return_type is not None
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call return type '{instruction.signature.return_type.display_name}' is not supported in x86_64_sysv",
            )


def _emit_callable_body(
    builder,
    callable_decl,
    *,
    target_input,
    frame_layout,
    ordered_block_ids,
    callable_by_id,
    emit_debug_comments: bool,
    trace_record,
    runtime_trace_enabled: bool,
) -> None:
    callable_analysis = target_input.analysis_for_callable(callable_decl.callable_id)
    callable_symbols = target_input.program_context.symbols.callable(callable_decl.callable_id)
    if callable_symbols.emitted_label is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv backend program context is missing an emitted label for '{_format_callable_id(callable_decl.callable_id)}'"
        )
    ordered_blocks = _ordered_blocks_for_callable(callable_decl, ordered_block_ids=ordered_block_ids)
    resolved_type_names = register_type_name_by_reg_id(callable_decl)
    interface_method_slot_by_id = {
        method_id: slot_index
        for interface_decl in target_input.program.interfaces
        for slot_index, method_id in enumerate(interface_decl.methods)
    }
    callable_label_for_calls = callable_symbols.emitted_label or callable_symbols.direct_call_symbol

    def emit_location_hook(*, line: int, column: int) -> None:
        emit_trace_location(builder, line=line, column=column)

    def emit_safepoint_preamble(instruction) -> None:
        if frame_layout.has_root_frame:
            live_reg_ids = callable_analysis.safepoints.live_regs_for_instruction(instruction.inst_id)
            emit_root_slot_sync(builder, frame_layout=frame_layout, live_reg_ids=live_reg_ids)
        if runtime_trace_enabled and instruction.effects.needs_safepoint_hooks:
            emit_location_hook(line=instruction.span.start.line, column=instruction.span.start.column)

    def emit_safepoint_postamble(instruction) -> None:
        if not frame_layout.has_root_frame:
            return
        live_reg_ids = callable_analysis.safepoints.live_regs_for_instruction(instruction.inst_id)
        emit_root_slot_reload(builder, frame_layout=frame_layout, live_reg_ids=live_reg_ids)

    def emit_call_instruction(instruction: BackendCallInst) -> None:
        emit_lowered_call_instruction(
            builder,
            instruction,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=resolved_type_names,
            callable_decl_by_id=callable_by_id,
            program_symbols=target_input.program_context.symbols,
            program_context=target_input.program_context,
            interface_method_slot_by_id=interface_method_slot_by_id,
            callable_label=callable_label_for_calls,
            emit_safepoint_preamble=emit_safepoint_preamble,
            emit_safepoint_postamble=emit_safepoint_postamble,
        )

    if callable_decl.kind == "constructor":
        _emit_constructor_entry_wrapper(
            builder,
            callable_decl,
            target_input=target_input,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=resolved_type_names,
            emit_call_instruction=emit_call_instruction,
            emit_location_hook=emit_location_hook if runtime_trace_enabled else None,
            trace_record=trace_record,
            runtime_trace_enabled=runtime_trace_enabled,
        )
        builder.blank()
        target_label = _constructor_init_label(target_input, callable_decl.callable_id)
        global_symbol = False
        alias_labels = ()
        body_trace_record = None
    else:
        target_label = callable_symbols.emitted_label
        global_symbol = callable_symbols.global_label is not None
        alias_labels = callable_symbols.alias_labels
        body_trace_record = trace_record

    epilogue = epilogue_label(target_label)
    block_label_by_id = {
        block.block_id: _block_label(target_label, block.block_id.ordinal)
        for block in ordered_blocks
    }

    if global_symbol:
        builder.global_symbol(target_label)
    builder.label(target_label)
    for alias_label in alias_labels:
        builder.label(alias_label)

    builder.instruction("push", "rbp")
    builder.instruction("mov", "rbp", "rsp")
    if frame_layout.stack_size > 0:
        builder.instruction("sub", "rsp", str(frame_layout.stack_size))

    _emit_param_spills(builder, callable_decl, frame_layout=frame_layout)
    if frame_layout.has_root_frame:
        emit_zero_root_slots(builder, frame_layout=frame_layout)
        emit_root_frame_setup(builder, frame_layout=frame_layout)
    if runtime_trace_enabled and body_trace_record is not None:
        emit_trace_push(
            builder,
            body_trace_record,
            line=callable_decl.span.start.line,
            column=callable_decl.span.start.column,
        )
    if emit_debug_comments:
        for slot in frame_layout.slots:
            builder.comment(f"{slot.home_name} -> {format_stack_slot_operand('rbp', slot.byte_offset)}")

    for block in ordered_blocks:
        builder.label(block_label_by_id[block.block_id])
        for instruction in block.instructions:
            if isinstance(instruction, BackendAllocObjectInst):
                emit_alloc_object_instruction(
                    builder,
                    instruction,
                    frame_layout=frame_layout,
                    program_context=target_input.program_context,
                    emit_safepoint_preamble=emit_safepoint_preamble,
                    emit_safepoint_postamble=emit_safepoint_postamble,
                )
                continue
            if isinstance(instruction, BackendFieldLoadInst):
                emit_field_load_instruction(
                    builder,
                    instruction,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=resolved_type_names,
                    program_context=target_input.program_context,
                )
                continue
            if isinstance(instruction, BackendFieldStoreInst):
                emit_field_store_instruction(
                    builder,
                    instruction,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=resolved_type_names,
                    program_context=target_input.program_context,
                )
                continue
            if isinstance(instruction, BackendNullCheckInst):
                emit_null_check_instruction(
                    builder,
                    instruction,
                    callable_label=target_label,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=resolved_type_names,
                )
                continue
            if isinstance(instruction, BackendArrayAllocInst):
                emit_array_alloc_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendArrayLengthInst):
                emit_array_length_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendArrayLoadInst):
                emit_array_load_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendArrayStoreInst):
                emit_array_store_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendArraySliceInst):
                emit_array_slice_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendArraySliceStoreInst):
                emit_array_slice_store_instruction(builder, instruction, emit_call_instruction=emit_call_instruction)
                continue
            if isinstance(instruction, BackendBoundsCheckInst):
                emit_bounds_check_instruction(builder, instruction)
                continue
            if isinstance(instruction, BackendCastInst):
                emit_cast_instruction(
                    builder,
                    instruction,
                    callable_label=target_label,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=resolved_type_names,
                    program_context=target_input.program_context,
                )
                continue
            if isinstance(instruction, BackendTypeTestInst):
                emit_type_test_instruction(
                    builder,
                    instruction,
                    callable_label=target_label,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=resolved_type_names,
                    program_context=target_input.program_context,
                )
                continue
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
            epilogue_label_text=epilogue,
            program_symbols=target_input.program_context.symbols,
        )

    builder.label(epilogue)
    _emit_runtime_epilogue_cleanup_preserving_return(
        builder,
        callable_decl,
        frame_layout=frame_layout,
        runtime_trace_enabled=runtime_trace_enabled and body_trace_record is not None,
    )
    builder.instruction("mov", "rsp", "rbp")
    builder.instruction("pop", "rbp")
    builder.instruction("ret")


def _emit_terminator(
    builder,
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
        f"x86_64_sysv terminator '{type(terminator).__name__}' is not supported in PR4 control-flow emission"
    )


def _ordered_blocks_for_callable(callable_decl, *, ordered_block_ids) -> tuple[BackendBlock, ...]:
    block_by_id = {block.block_id: block for block in callable_decl.blocks}
    try:
        return tuple(block_by_id[block_id] for block_id in ordered_block_ids)
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"x86_64_sysv ordered block sequence references undeclared block '{exc.args[0]}'"
        ) from exc


def _block_label(target_label: str, block_ordinal: int) -> str:
    return f".L{target_label}_b{block_ordinal}"


def _emit_param_spills(builder, callable_decl, *, frame_layout, includes_receiver: bool | None = None) -> None:
    resolved_includes_receiver = callable_decl.receiver_reg is not None if includes_receiver is None else includes_receiver
    arg_locations = X86_64_SYSV_ABI.plan_argument_locations(
        callable_decl.signature.param_types,
        includes_receiver=resolved_includes_receiver,
    )
    ordered_arg_regs = callable_decl.param_regs
    if resolved_includes_receiver:
        if callable_decl.receiver_reg is None:
            raise BackendTargetLoweringError("x86_64_sysv receiver spills require a receiver register")
        ordered_arg_regs = (callable_decl.receiver_reg, *ordered_arg_regs)
    for reg_id, arg_location in zip(ordered_arg_regs, arg_locations, strict=True):
        slot = frame_layout.for_reg(reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv frame layout is missing a home for parameter register 'r{reg_id.ordinal}'"
            )
        stack_operand = format_stack_slot_operand("rbp", slot.byte_offset)
        if arg_location.kind == "int_reg":
            assert arg_location.register_name is not None
            builder.instruction("mov", stack_operand, arg_location.register_name)
            continue
        if arg_location.kind == "float_reg":
            assert arg_location.register_name is not None
            builder.instruction("movq", stack_operand, arg_location.register_name)
            continue
        if arg_location.kind == "stack":
            assert arg_location.stack_slot_index is not None
            incoming_offset = X86_64_SYSV_ABI.incoming_stack_arg_byte_offset(arg_location.stack_slot_index)
            builder.instruction("mov", "rax", f"qword ptr [rbp + {incoming_offset}]")
            builder.instruction("mov", stack_operand, "rax")
            continue
        raise BackendTargetLoweringError(f"unsupported reduced-scope parameter location kind '{arg_location.kind}'")


def _emit_constructor_entry_wrapper(
    builder,
    callable_decl,
    *,
    target_input,
    frame_layout,
    register_type_name_by_reg_id: dict,
    emit_call_instruction,
    emit_location_hook,
    trace_record,
    runtime_trace_enabled: bool,
) -> None:
    callable_symbols = target_input.program_context.symbols.callable(callable_decl.callable_id)
    target_label = callable_symbols.emitted_label
    if target_label is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv backend program context is missing an emitted label for '{_format_callable_id(callable_decl.callable_id)}'"
        )
    if callable_symbols.global_label is not None:
        builder.global_symbol(target_label)
    builder.label(target_label)
    for alias_label in callable_symbols.alias_labels:
        builder.label(alias_label)

    epilogue = epilogue_label(target_label)
    builder.instruction("push", "rbp")
    builder.instruction("mov", "rbp", "rsp")
    if frame_layout.stack_size > 0:
        builder.instruction("sub", "rsp", str(frame_layout.stack_size))

    _emit_param_spills(builder, callable_decl, frame_layout=frame_layout, includes_receiver=False)
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
    receiver_reg = callable_decl.receiver_reg
    if receiver_reg is None:
        raise BackendTargetLoweringError("constructor wrapper emission requires a receiver register")
    class_id = ClassId(module_path=callable_decl.callable_id.module_path, name=callable_decl.callable_id.class_name)
    emit_alloc_object_instruction(
        builder,
        BackendAllocObjectInst(
            inst_id=BackendInstId(owner_id=callable_decl.callable_id, ordinal=0),
            dest=receiver_reg,
            class_id=class_id,
            effects=BackendEffects(reads_memory=True, writes_memory=True, may_gc=True, needs_safepoint_hooks=True),
            span=callable_decl.span,
        ),
        frame_layout=frame_layout,
        program_context=target_input.program_context,
        emit_safepoint_preamble=(
            (lambda instruction: emit_location_hook(line=instruction.span.start.line, column=instruction.span.start.column))
            if emit_location_hook is not None
            else None
        ),
    )
    init_call = BackendCallInst(
        inst_id=BackendInstId(owner_id=callable_decl.callable_id, ordinal=1),
        dest=receiver_reg,
        target=BackendDirectCallTarget(callable_id=callable_decl.callable_id),
        args=(BackendRegOperand(reg_id=receiver_reg),) + tuple(BackendRegOperand(reg_id=reg_id) for reg_id in callable_decl.param_regs),
        signature=callable_decl.signature,
        effects=BackendEffects(reads_memory=True, writes_memory=True),
        span=callable_decl.span,
    )
    emit_call_instruction(init_call)
    emit_load_operand(
        builder,
        BackendRegOperand(reg_id=receiver_reg),
        target_register="rax",
        target_byte_register="al",
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("jmp", epilogue)
    builder.label(epilogue)
    _emit_runtime_epilogue_cleanup_preserving_return(
        builder,
        callable_decl,
        frame_layout=frame_layout,
        runtime_trace_enabled=runtime_trace_enabled and trace_record is not None,
    )
    builder.instruction("mov", "rsp", "rbp")
    builder.instruction("pop", "rbp")
    builder.instruction("ret")


def _trace_record_for_callable(target_input: BackendTargetInput, callable_decl, *, source_root: Path | None) -> TraceDebugRecord | None:
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
    builder,
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
    if return_type_name == "double":
        builder.instruction("sub", "rsp", "16")
        builder.instruction("movq", "qword ptr [rsp]", "xmm0")
        if frame_layout.has_root_frame:
            emit_root_frame_pop(builder, frame_layout=frame_layout)
        if runtime_trace_enabled:
            emit_trace_pop(builder)
        builder.instruction("movq", "xmm0", "qword ptr [rsp]")
        builder.instruction("add", "rsp", "16")
        return
    builder.instruction("sub", "rsp", "16")
    builder.instruction("mov", "qword ptr [rsp]", "rax")
    if frame_layout.has_root_frame:
        emit_root_frame_pop(builder, frame_layout=frame_layout)
    if runtime_trace_enabled:
        emit_trace_pop(builder)
    builder.instruction("mov", "rax", "qword ptr [rsp]")
    builder.instruction("add", "rsp", "16")


def _constructor_init_label(target_input: BackendTargetInput, callable_id: ConstructorId) -> str:
    callable_symbols = target_input.program_context.symbols.callable(callable_id)
    if callable_symbols.constructor_init_symbol is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv constructor '{_format_callable_id(callable_id)}' is missing an init symbol"
        )
    return callable_symbols.constructor_init_symbol


def _callable_error(callable_decl, message: str) -> None:
    raise X86_64SysVLegalityError(
        f"Backend target '{TARGET_NAME}' callable '{_format_callable_id(callable_decl.callable_id)}': {message}"
    )


def _instruction_error(callable_decl, block: BackendBlock, instruction: object, message: str) -> None:
    inst_id = getattr(instruction, "inst_id", None)
    inst_name = "terminator" if inst_id is None else f"instruction 'i{inst_id.ordinal}'"
    raise X86_64SysVLegalityError(
        f"Backend target '{TARGET_NAME}' callable '{_format_callable_id(callable_decl.callable_id)}' "
        f"block 'b{block.block_id.ordinal}' {inst_name}: {message}"
    )


def _format_callable_id(callable_id) -> str:
    if isinstance(callable_id, FunctionId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.name}"
    if isinstance(callable_id, MethodId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
    if isinstance(callable_id, ConstructorId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
    raise TypeError(f"Unsupported backend callable ID '{callable_id!r}'")


def _check_cast_instruction_legality(callable_decl, block: BackendBlock, instruction: BackendCastInst) -> None:
    target_type_name = semantic_type_canonical_name(instruction.target_type_ref)

    if instruction.cast_kind is CastSemanticsKind.IDENTITY:
        return
    if instruction.cast_kind is CastSemanticsKind.TO_BOOL:
        if target_type_name != "bool":
            _instruction_error(callable_decl, block, instruction, "TO_BOOL casts must target 'bool'")
        return
    if instruction.cast_kind is CastSemanticsKind.TO_DOUBLE:
        if target_type_name != "double":
            _instruction_error(callable_decl, block, instruction, "TO_DOUBLE casts must target 'double'")
        return
    if instruction.cast_kind is CastSemanticsKind.TO_INTEGER:
        if target_type_name not in {"i64", "u64", "u8"}:
            _instruction_error(callable_decl, block, instruction, f"unsupported integer cast target '{target_type_name}'")
        return
    if instruction.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY:
        if not (semantic_type_is_reference(instruction.target_type_ref) or semantic_type_is_interface(instruction.target_type_ref)):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"reference casts require a reference or interface target, got '{instruction.target_type_ref.display_name}'",
            )
        return
    _instruction_error(
        callable_decl,
        block,
        instruction,
        f"instruction '{type(instruction).__name__}' uses unsupported cast kind '{instruction.cast_kind.value}'",
    )


def _check_type_test_instruction_legality(callable_decl, block: BackendBlock, instruction: BackendTypeTestInst) -> None:
    if instruction.test_kind is TypeTestSemanticsKind.INTERFACE_COMPATIBILITY:
        if not semantic_type_is_interface(instruction.target_type_ref):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"interface type tests require an interface target, got '{instruction.target_type_ref.display_name}'",
            )
        return
    if instruction.test_kind is TypeTestSemanticsKind.CLASS_COMPATIBILITY:
        if semantic_type_is_interface(instruction.target_type_ref):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"class type tests cannot target interface type '{instruction.target_type_ref.display_name}'",
            )
        if not semantic_type_is_reference(instruction.target_type_ref):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"class type tests require a reference target, got '{instruction.target_type_ref.display_name}'",
            )
        return
    _instruction_error(
        callable_decl,
        block,
        instruction,
        f"instruction '{type(instruction).__name__}' uses unsupported test kind '{instruction.test_kind.value}'",
    )


def _operand_type_name(callable_decl, operand) -> str:
    if isinstance(operand, BackendRegOperand):
        register_by_id = {register.reg_id: register for register in callable_decl.registers}
        return semantic_type_canonical_name(register_by_id[operand.reg_id].type_ref)
    if isinstance(operand, BackendConstOperand):
        if hasattr(operand.constant, "type_name"):
            return operand.constant.type_name
        return "Obj"
    raise TypeError(f"Unsupported backend operand '{operand!r}'")


X86_64_SYSV_TARGET: BackendTarget = X86_64SysVTarget()


__all__ = [
    "TARGET_NAME",
    "X86_64_SYSV_TARGET",
    "X86_64SysVLegalityError",
    "X86_64SysVTarget",
    "check_x86_64_sysv_legality",
    "emit_x86_64_sysv_asm",
]