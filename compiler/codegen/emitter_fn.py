from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_expr import EmitContext, emit_expr
from compiler.codegen.emitter_stmt import emit_statement
from compiler.codegen.layout import build_constructor_layout, build_layout
from compiler.codegen.model import CONSTRUCTOR_OBJECT_SLOT_NAME
from compiler.codegen.root_liveness import analyze_named_root_liveness
from compiler.codegen.strings import escape_c_string
from compiler.semantic.ir import *
from compiler.semantic.lowered_ir import (
    LoweredSemanticClass,
    LoweredSemanticConstructor,
    LoweredSemanticFunction,
    LoweredSemanticMethod,
)
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_type_ref_for_class_id


def _emit_debug_symbol_literals(codegen, *, target_label: str, function_name: str, file_path: str) -> tuple[str, str]:
    fn_label = codegen_symbols.mangle_debug_function_symbol(target_label)
    file_label = codegen_symbols.mangle_debug_file_symbol(target_label)
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    codegen.asm.label(fn_label)
    codegen.asm.asciz(escape_c_string(function_name))
    codegen.asm.label(file_label)
    codegen.asm.asciz(escape_c_string(file_path))
    codegen.asm.blank()
    codegen.asm.directive(".text")
    return fn_label, file_label


def _function_param_spills(fn: SemanticFunction | LoweredSemanticFunction, layout) -> list[tuple[int, SemanticTypeRef, object]]:
    param_locals = sorted(
        (local_info for local_info in fn.local_info_by_id.values() if local_info.binding_kind in {"receiver", "param"}),
        key=lambda local_info: local_info.local_id.ordinal,
    )
    if len(param_locals) != len(fn.params):
        raise ValueError("function emission requires owner-local metadata for every parameter slot")
    return [
        (layout.local_slot_offsets[local_info.local_id], param.type_ref, param.span)
        for param, local_info in zip(fn.params, param_locals, strict=True)
    ]


def _constructor_param_spills(params: list[SemanticParam], layout) -> list[tuple[int, SemanticTypeRef, object]]:
    return [(layout.slot_offsets[param.name], param.type_ref, param.span) for param in params]


def _explicit_constructor_param_spills(
    constructor: SemanticConstructor | LoweredSemanticConstructor,
    layout,
) -> list[tuple[int, SemanticTypeRef, object]]:
    param_locals = sorted(
        (local_info for local_info in constructor.local_info_by_id.values() if local_info.binding_kind == "param"),
        key=lambda local_info: local_info.local_id.ordinal,
    )
    if len(param_locals) != len(constructor.params):
        raise ValueError("constructor emission requires owner-local metadata for every constructor parameter slot")
    return [
        (layout.local_slot_offsets[local_info.local_id], param.type_ref, param.span)
        for param, local_info in zip(constructor.params, param_locals, strict=True)
    ]


def _constructor_receiver_local_id(constructor: SemanticConstructor | LoweredSemanticConstructor) -> LocalId:
    receiver_locals = [
        local_info.local_id for local_info in constructor.local_info_by_id.values() if local_info.binding_kind == "receiver"
    ]
    if len(receiver_locals) != 1:
        raise ValueError("constructor emission requires exactly one receiver local")
    return receiver_locals[0]


def _tracked_named_root_local_ids(layout) -> frozenset[LocalId]:
    return frozenset(layout.root_slot_offsets_by_local_id)


def _initial_dirty_named_root_local_ids(
    owner: SemanticFunction
    | SemanticMethod
    | SemanticConstructor
    | LoweredSemanticFunction
    | LoweredSemanticMethod
    | LoweredSemanticConstructor,
    layout,
) -> set[LocalId]:
    tracked_local_ids = _tracked_named_root_local_ids(layout)
    return {
        local_info.local_id
        for local_info in owner.local_info_by_id.values()
        if local_info.local_id in tracked_local_ids
        and local_info.binding_kind in {"receiver", "param"}
        and codegen_types.is_reference_type_ref(local_info.type_ref)
    }


def emit_function(
    codegen,
    declaration_tables,
    fn: SemanticFunction | LoweredSemanticFunction,
    *,
    label: str | None = None,
    global_symbol: bool | None = None,
) -> None:
    if fn.body is None:
        raise ValueError("semantic function emission requires a concrete body")
    target_label = label if label is not None else fn.function_id.name
    epilogue = f".L{target_label}_epilogue"
    layout = build_layout(fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = _emit_debug_symbol_literals(
        codegen, target_label=target_label, function_name=target_label, file_path=fn.span.start.path
    )

    codegen.emit_frame_prologue(
        target_label,
        layout,
        global_symbol=(fn.is_export or fn.function_id.name == "main") if global_symbol is None else global_symbol,
    )
    codegen.emit_location_comment(file_path=fn.span.start.path, line=fn.span.start.line, column=fn.span.start.column)
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_function_param_spills(fn, layout))

    if layout.root_slot_count > 0:
        first_root_offset = (
            layout.root_slots[0].root_offset
            if layout.root_slots
            else layout.temp_root_slot_offsets[0]
        )
        if first_root_offset is None:
            raise ValueError("root slot metadata missing offset for first function root")
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        current_module_path=fn.function_id.module_path,
        owner=fn,
        label_counter=label_counter,
        string_literal_labels=codegen.string_literal_labels,
        temp_root_depth=[0],
        call_scratch_depth=[0],
        declaration_tables=declaration_tables,
        named_root_liveness=analyze_named_root_liveness(fn),
        tracked_named_root_local_ids=_tracked_named_root_local_ids(layout),
        dirty_named_root_local_ids=_initial_dirty_named_root_local_ids(fn, layout),
        known_cleared_named_root_local_ids=set(_tracked_named_root_local_ids(layout)),
    )

    for stmt in fn.body.statements:
        emit_statement(codegen, stmt, epilogue, fn.return_type_ref, emit_ctx, loop_labels=[])

    codegen.asm.label(epilogue)
    codegen.emit_function_epilogue(layout, fn.return_type_ref)


def emit_method(codegen, declaration_tables, cls: LoweredSemanticClass, method: LoweredSemanticMethod) -> None:
    method_label = declaration_tables.method_label(method.method_id)
    if method_label is None:
        raise ValueError(f"Missing method label for {method.method_id}")
    method_fn = LoweredSemanticFunction(
        function_id=FunctionId(
            module_path=method.method_id.module_path, name=method_label
        ),
        params=[*(_receiver_param(cls, method) if not method.is_static else []), *method.params],
        return_type_ref=method.return_type_ref,
        body=method.body,
        is_export=False,
        is_extern=False,
        span=method.span,
        local_info_by_id=method.local_info_by_id,
    )
    emit_function(
        codegen,
        declaration_tables,
        method_fn,
        label=method_label,
        global_symbol=False,
    )


def emit_constructor(
    codegen,
    declaration_tables,
    cls: LoweredSemanticClass,
    constructor: LoweredSemanticConstructor,
) -> None:
    ctor_layout = declaration_tables.constructor_layout(constructor.constructor_id)
    if ctor_layout is None:
        raise ValueError(f"Missing constructor layout for {constructor.constructor_id}")

    if constructor.body is None:
        _emit_compatibility_constructor(codegen, declaration_tables, cls, constructor, ctor_layout)
        return

    _emit_explicit_constructor(codegen, declaration_tables, cls, constructor, ctor_layout)


def _emit_compatibility_constructor(
    codegen,
    declaration_tables,
    cls: LoweredSemanticClass,
    constructor: LoweredSemanticConstructor,
    ctor_layout,
) -> None:
    ctor_params = constructor.params

    target_label = ctor_layout.label
    epilogue = f".L{target_label}_epilogue"
    layout = build_constructor_layout(cls, ctor_layout, constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = _emit_debug_symbol_literals(
        codegen, target_label=target_label, function_name=target_label, file_path=constructor.span.start.path
    )

    codegen.emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen.emit_location_comment(
        file_path=constructor.span.start.path,
        line=constructor.span.start.line,
        column=constructor.span.start.column,
    )
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_constructor_param_spills(ctor_params, layout))

    if layout.root_slot_count > 0:
        first_root_offset = (
            layout.root_slots[0].root_offset
            if layout.root_slots
            else layout.temp_root_slot_offsets[0]
        )
        if first_root_offset is None:
            raise ValueError("root slot metadata missing offset for first constructor root")
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(
        fn_debug_name_label,
        fn_debug_file_label,
        constructor.span.start.line,
        constructor.span.start.column,
    )
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="before", label_counter=label_counter)
    codegen.emit_named_root_slot_updates(layout)
    codegen.asm.instr("call rt_thread_state")
    codegen.asm.instr("mov rdi, rax")
    codegen.asm.instr(f"lea rsi, [rip + {ctor_layout.type_symbol}]")
    codegen.asm.instr(f"mov rdx, {ctor_layout.payload_bytes}")
    codegen.asm.instr("call rt_alloc_obj")
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="after", label_counter=label_counter)
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[CONSTRUCTOR_OBJECT_SLOT_NAME])}, rax")

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        current_module_path=cls.class_id.module_path,
        owner=None,
        label_counter=label_counter,
        string_literal_labels=codegen.string_literal_labels,
        temp_root_depth=[0],
        call_scratch_depth=[0],
        declaration_tables=declaration_tables,
        named_root_liveness=None,
    )

    param_fields = set(ctor_layout.param_field_names)
    field_decl_by_name = {field.name: field for field in cls.fields}
    for field_name in ctor_layout.field_names:
        field_offset = declaration_tables.class_field_offset(cls.class_id, field_name)
        if field_offset is None:
            raise ValueError(f"constructor codegen missing field '{cls.class_id.name}.{field_name}'")
        field_decl = field_decl_by_name[field_name]
        if field_name in param_fields:
            value_offset = layout.slot_offsets[field_name]
            codegen.asm.instr(f"mov rcx, {offset_operand(value_offset)}")
        else:
            if field_decl.initializer is None:
                raise ValueError("constructor default initializer missing")
            emit_expr(codegen, field_decl.initializer, emit_ctx)
            codegen.asm.instr("mov rcx, rax")
        codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[CONSTRUCTOR_OBJECT_SLOT_NAME])}")
        codegen.asm.instr(f"mov qword ptr [rax + {field_offset}], rcx")

    codegen.asm.instr(f"jmp {epilogue}")
    codegen.asm.label(epilogue)
    codegen.emit_ref_epilogue(layout)


def _emit_explicit_constructor(
    codegen,
    declaration_tables,
    cls: LoweredSemanticClass,
    constructor: LoweredSemanticConstructor,
    ctor_layout,
) -> None:
    target_label = ctor_layout.label
    epilogue = f".L{target_label}_epilogue"
    layout = build_constructor_layout(
        cls,
        ctor_layout,
        constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME,
        constructor=constructor,
    )
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = _emit_debug_symbol_literals(
        codegen, target_label=target_label, function_name=target_label, file_path=constructor.span.start.path
    )
    receiver_local_id = _constructor_receiver_local_id(constructor)
    receiver_offset = layout.local_slot_offsets.get(receiver_local_id)
    if receiver_offset is None:
        raise ValueError("constructor emission requires a materialized receiver slot")

    codegen.emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen.emit_location_comment(
        file_path=constructor.span.start.path,
        line=constructor.span.start.line,
        column=constructor.span.start.column,
    )
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_explicit_constructor_param_spills(constructor, layout))

    if layout.root_slot_count > 0:
        first_root_offset = (
            layout.root_slots[0].root_offset if layout.root_slots else layout.temp_root_slot_offsets[0]
        )
        if first_root_offset is None:
            raise ValueError("root slot metadata missing offset for first constructor root")
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(
        fn_debug_name_label,
        fn_debug_file_label,
        constructor.span.start.line,
        constructor.span.start.column,
    )

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        current_module_path=cls.class_id.module_path,
        owner=constructor,
        label_counter=label_counter,
        string_literal_labels=codegen.string_literal_labels,
        temp_root_depth=[0],
        call_scratch_depth=[0],
        declaration_tables=declaration_tables,
        named_root_liveness=analyze_named_root_liveness(constructor),
        tracked_named_root_local_ids=_tracked_named_root_local_ids(layout),
        dirty_named_root_local_ids=_initial_dirty_named_root_local_ids(constructor, layout),
        known_cleared_named_root_local_ids=set(_tracked_named_root_local_ids(layout)),
    )
    initial_sync_local_ids = frozenset(emit_ctx.dirty_named_root_local_ids or ())

    codegen.emit_runtime_call_hook(fn_name=target_label, phase="before", label_counter=label_counter)
    if initial_sync_local_ids:
        codegen.emit_named_root_slot_updates(layout, local_ids=initial_sync_local_ids)
        emit_ctx.mark_named_roots_synced(initial_sync_local_ids)
    codegen.asm.instr("call rt_thread_state")
    codegen.asm.instr("mov rdi, rax")
    codegen.asm.instr(f"lea rsi, [rip + {ctor_layout.type_symbol}]")
    codegen.asm.instr(f"mov rdx, {ctor_layout.payload_bytes}")
    codegen.asm.instr("call rt_alloc_obj")
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="after", label_counter=label_counter)
    codegen.asm.instr(f"mov {offset_operand(receiver_offset)}, rax")
    emit_ctx.mark_named_root_dirty(receiver_local_id)
    codegen.emit_named_root_slot_updates(layout, local_ids={receiver_local_id})
    emit_ctx.mark_named_roots_synced({receiver_local_id})

    for field_decl in cls.fields:
        if field_decl.initializer is None:
            continue
        field_offset = declaration_tables.class_field_offset(cls.class_id, field_decl.name)
        if field_offset is None:
            raise ValueError(f"constructor codegen missing field '{cls.class_id.name}.{field_decl.name}'")
        emit_expr(codegen, field_decl.initializer, emit_ctx)
        codegen.asm.instr("mov rcx, rax")
        codegen.asm.instr(f"mov rax, {offset_operand(receiver_offset)}")
        codegen.asm.instr(f"mov qword ptr [rax + {field_offset}], rcx")

    return_type_ref = semantic_type_ref_for_class_id(cls.class_id, display_name=cls.class_id.name)
    for stmt in constructor.body.statements:
        emit_statement(codegen, stmt, epilogue, return_type_ref, emit_ctx, loop_labels=[])

    codegen.asm.instr(f"jmp {epilogue}")
    codegen.asm.label(epilogue)
    codegen.asm.instr(f"mov rax, {offset_operand(receiver_offset)}")
    codegen.emit_ref_epilogue(layout)


def _receiver_param(cls: LoweredSemanticClass, method: LoweredSemanticMethod) -> list[SemanticParam]:
    return [
        SemanticParam(
            name="__self",
            type_ref=semantic_type_ref_for_class_id(cls.class_id, display_name=cls.class_id.name),
            span=method.span,
        )
    ]
