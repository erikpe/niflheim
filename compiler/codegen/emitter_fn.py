from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_expr import EmitContext, emit_expr
from compiler.codegen.emitter_stmt import emit_statement
from compiler.codegen.layout import build_constructor_layout, build_layout
from compiler.codegen.model import CONSTRUCTOR_OBJECT_SLOT_NAME
from compiler.codegen.strings import escape_c_string
from compiler.semantic.ir import *
from compiler.semantic.symbols import FunctionId


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


def _param_specs(params: list[SemanticParam]) -> list[tuple[str, str, object]]:
    return [(param.name, param.type_name, param.span) for param in params]


def emit_function(
    codegen, declaration_tables, fn: SemanticFunction, *, label: str | None = None, global_symbol: bool | None = None
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
    codegen.emit_param_spills(_param_specs(fn.params), layout)

    if layout.root_slot_count > 0:
        first_root_offset = (
            layout.root_slot_offsets[layout.root_slot_names[0]]
            if layout.root_slot_names
            else layout.temp_root_slot_offsets[0]
        )
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        current_module_path=fn.function_id.module_path,
        label_counter=label_counter,
        string_literal_labels=codegen.string_literal_labels,
        temp_root_depth=[0],
        declaration_tables=declaration_tables,
    )

    for stmt in fn.body.statements:
        emit_statement(codegen, stmt, epilogue, fn.return_type_name, emit_ctx, loop_labels=[])

    codegen.asm.label(epilogue)
    codegen.emit_function_epilogue(layout, fn.return_type_name)


def emit_method(codegen, declaration_tables, cls: SemanticClass, method: SemanticMethod) -> None:
    method_label = declaration_tables.method_label(method.method_id)
    if method_label is None:
        raise ValueError(f"Missing method label for {method.method_id}")
    method_fn = SemanticFunction(
        function_id=FunctionId(
            module_path=method.method_id.module_path, name=method_label
        ),
        params=[*(_receiver_param(cls, method) if not method.is_static else []), *method.params],
        return_type_name=method.return_type_name,
        body=method.body,
        is_export=False,
        is_extern=False,
        span=method.span,
    )
    emit_function(
        codegen,
        declaration_tables,
        method_fn,
        label=method_label,
        global_symbol=False,
    )


def emit_constructor(codegen, declaration_tables, cls: SemanticClass) -> None:
    from compiler.semantic.symbols import ConstructorId

    ctor_id = ConstructorId(module_path=cls.class_id.module_path, class_name=cls.class_id.name)
    ctor_layout = declaration_tables.constructor_layout(ctor_id)
    if ctor_layout is None:
        raise ValueError(f"Missing constructor layout for {ctor_id}")
    ctor_params = [
        SemanticParam(name=field.name, type_name=field.type_name, span=field.span)
        for field in cls.fields
        if field.initializer is None
    ]

    target_label = ctor_layout.label
    epilogue = f".L{target_label}_epilogue"
    layout = build_constructor_layout(cls, ctor_layout, constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = _emit_debug_symbol_literals(
        codegen, target_label=target_label, function_name=target_label, file_path=cls.span.start.path
    )

    codegen.emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen.emit_location_comment(file_path=cls.span.start.path, line=cls.span.start.line, column=cls.span.start.column)
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_param_specs(ctor_params), layout)

    if layout.root_slot_count > 0:
        first_root_offset = (
            layout.root_slot_offsets[layout.root_slot_names[0]]
            if layout.root_slot_names
            else layout.temp_root_slot_offsets[0]
        )
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="before", label_counter=label_counter)
    codegen.emit_root_slot_updates(layout)
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
        label_counter=label_counter,
        string_literal_labels=codegen.string_literal_labels,
        temp_root_depth=[0],
        declaration_tables=declaration_tables,
    )

    param_fields = set(ctor_layout.param_field_names)
    field_decl_by_name = {field.name: field for field in cls.fields}
    for field_index, field_name in enumerate(ctor_layout.field_names):
        field_offset = 24 + (8 * field_index)
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


def _receiver_param(cls: SemanticClass, method: SemanticMethod) -> list[SemanticParam]:
    return [SemanticParam(name="__self", type_name=cls.class_id.name, span=method.span)]
