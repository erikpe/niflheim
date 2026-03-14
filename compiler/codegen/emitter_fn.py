from __future__ import annotations

from typing import TYPE_CHECKING

import compiler.codegen.layout as codegen_layout
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.ast_nodes import ClassDecl, FunctionDecl
from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_stmt import emit_statement
from compiler.codegen.emitter_expr import emit_expr
from compiler.codegen.model import EmitContext
from compiler.codegen.strings import escape_c_string

if TYPE_CHECKING:
    from compiler.codegen.legacy import CodeGenerator


def emit_debug_symbol_literals(
    codegen: CodeGenerator,
    *,
    target_label: str,
    function_name: str,
    file_path: str,
) -> tuple[str, str]:
    safe_target = target_label.replace(".", "_").replace(":", "_")
    fn_label = f"__nif_dbg_fn_{safe_target}"
    file_label = f"__nif_dbg_file_{safe_target}"
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    codegen.asm.label(fn_label)
    codegen.asm.asciz(escape_c_string(function_name))
    codegen.asm.label(file_label)
    codegen.asm.asciz(escape_c_string(file_path))
    codegen.asm.blank()
    codegen.asm.directive(".text")
    return fn_label, file_label


def method_function_decl(class_decl: ClassDecl, method_decl, label: str) -> FunctionDecl:
    from compiler.ast_nodes import ParamDecl, TypeRef

    receiver_params: list[ParamDecl] = []
    if not method_decl.is_static:
        receiver_params.append(
            ParamDecl(
                name="__self",
                type_ref=TypeRef(name=class_decl.name, span=method_decl.span),
                span=method_decl.span,
            )
        )
    return FunctionDecl(
        name=label,
        params=[*receiver_params, *method_decl.params],
        return_type=method_decl.return_type,
        body=method_decl.body,
        is_export=False,
        is_extern=False,
        span=method_decl.span,
    )


def constructor_function_decl(class_decl: ClassDecl, label: str) -> FunctionDecl:
    from compiler.ast_nodes import BlockStmt, ParamDecl, TypeRef, VarDeclStmt

    params = [
        ParamDecl(name=field.name, type_ref=field.type_ref, span=field.span)
        for field in class_decl.fields
        if field.initializer is None
    ]
    return FunctionDecl(
        name=label,
        params=params,
        return_type=TypeRef(name=class_decl.name, span=class_decl.span),
        body=BlockStmt(
            statements=[
                VarDeclStmt(
                    name="__nif_ctor_obj",
                    type_ref=TypeRef(name=class_decl.name, span=class_decl.span),
                    initializer=None,
                    span=class_decl.span,
                )
            ],
            span=class_decl.span,
        ),
        is_export=False,
        is_extern=False,
        span=class_decl.span,
    )


def emit_function(codegen: CodeGenerator, fn: FunctionDecl, *, label: str | None = None) -> None:
    target_label = label if label is not None else fn.name
    epilogue = codegen_symbols.epilogue_label(target_label)
    layout = codegen_layout.build_layout(fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=fn.span.start.path,
    )

    codegen.emit_frame_prologue(target_label, layout, global_symbol=label is None and (fn.is_export or fn.name == "main"))
    codegen.emit_location_comment(
        file_path=fn.span.start.path,
        line=fn.span.start.line,
        column=fn.span.start.column,
    )
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(fn.params, layout)

    if layout.root_slot_count > 0:
        if layout.root_slot_names:
            first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        else:
            first_root_offset = layout.temp_root_slot_offsets[0]
        codegen.emit_root_frame_setup(
            layout,
            root_count=layout.root_slot_count,
            first_root_offset=first_root_offset,
        )

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        label_counter=label_counter,
        method_labels=codegen.method_labels,
        method_return_types=codegen.method_return_types,
        method_is_static=codegen.method_is_static,
        constructor_labels=codegen.constructor_labels,
        function_return_types=codegen.function_return_types,
        string_literal_labels=codegen.string_literal_labels,
        class_field_type_names=codegen.class_field_type_names,
        temp_root_depth=[0],
    )

    function_return_type_name = codegen_types.type_ref_name(fn.return_type)
    for stmt in fn.body.statements:
        emit_statement(codegen, stmt, epilogue, function_return_type_name, emit_ctx, loop_labels=[])

    codegen.asm.label(epilogue)
    codegen.emit_function_epilogue(layout, function_return_type_name)


def emit_constructor_function(codegen: CodeGenerator, cls: ClassDecl) -> None:
    ctor_layout = codegen.constructor_layouts[cls.name]
    ctor_fn = constructor_function_decl(cls, ctor_layout.label)
    target_label = ctor_layout.label
    epilogue = codegen_symbols.epilogue_label(target_label)
    layout = codegen_layout.build_layout(ctor_fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=cls.span.start.path,
    )

    codegen.emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen.emit_location_comment(
        file_path=cls.span.start.path,
        line=cls.span.start.line,
        column=cls.span.start.column,
    )
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(ctor_fn.params, layout)

    if layout.root_slot_names:
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        codegen.emit_root_frame_setup(
            layout,
            root_count=len(layout.root_slot_names),
            first_root_offset=first_root_offset,
        )

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)

    codegen.emit_runtime_call_hook(
        fn_name=target_label,
        phase="before",
        label_counter=label_counter,
    )
    codegen.emit_root_slot_updates(layout)
    codegen.asm.instr("call rt_thread_state")
    codegen.asm.instr("mov rdi, rax")
    codegen.asm.instr(f"lea rsi, [rip + {ctor_layout.type_symbol}]")
    codegen.asm.instr(f"mov rdx, {ctor_layout.payload_bytes}")
    codegen.asm.instr("call rt_alloc_obj")
    codegen.emit_runtime_call_hook(
        fn_name=target_label,
        phase="after",
        label_counter=label_counter,
    )
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets['__nif_ctor_obj'])}, rax")

    emit_ctx = EmitContext(
        layout=layout,
        fn_name=target_label,
        label_counter=label_counter,
        method_labels=codegen.method_labels,
        method_return_types=codegen.method_return_types,
        method_is_static=codegen.method_is_static,
        constructor_labels=codegen.constructor_labels,
        function_return_types=codegen.function_return_types,
        string_literal_labels=codegen.string_literal_labels,
        class_field_type_names=codegen.class_field_type_names,
        temp_root_depth=[0],
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
                codegen_types.raise_codegen_error("constructor default initializer missing", span=field_decl.span)
            emit_expr(codegen, field_decl.initializer, emit_ctx)
            codegen.asm.instr("mov rcx, rax")

        codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets['__nif_ctor_obj'])}")
        codegen.asm.instr(f"mov qword ptr [rax + {field_offset}], rcx")

    codegen.asm.instr(f"jmp {epilogue}")

    codegen.asm.label(epilogue)
    codegen.emit_ref_epilogue(layout)