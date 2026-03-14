from __future__ import annotations

from typing import TYPE_CHECKING

from compiler.ast_nodes import ClassDecl, FunctionDecl
from compiler.codegen.asm import _offset_operand
from compiler.codegen.emitter_expr import emit_expr
from compiler.codegen.model import EmitContext
from compiler.codegen.symbols import _epilogue_label
from compiler.codegen.types import _raise_codegen_error, _type_ref_name

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
    codegen.out.append("")
    codegen.out.append(".section .rodata")
    codegen.out.append(f"{fn_label}:")
    codegen.out.append(f'    .asciz "{codegen._escape_c_string_proxy(function_name)}"')
    codegen.out.append(f"{file_label}:")
    codegen.out.append(f'    .asciz "{codegen._escape_c_string_proxy(file_path)}"')
    codegen.out.append("")
    codegen.out.append(".text")
    return fn_label, file_label


def emit_function(codegen: CodeGenerator, fn: FunctionDecl, *, label: str | None = None) -> None:
    target_label = label if label is not None else fn.name
    epilogue = _epilogue_label(target_label)
    layout = codegen._build_layout_proxy(fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=fn.span.start.path,
    )

    codegen._emit_frame_prologue(target_label, layout, global_symbol=label is None and (fn.is_export or fn.name == "main"))
    codegen._emit_location_comment(
        file_path=fn.span.start.path,
        line=fn.span.start.line,
        column=fn.span.start.column,
    )
    codegen._emit_zero_slots(layout)
    codegen._emit_param_spills(fn.params, layout)

    if layout.root_slot_count > 0:
        if layout.root_slot_names:
            first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        else:
            first_root_offset = layout.temp_root_slot_offsets[0]
        codegen._emit_root_frame_setup(
            layout,
            root_count=layout.root_slot_count,
            first_root_offset=first_root_offset,
        )

    codegen._emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

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

    function_return_type_name = _type_ref_name(fn.return_type)
    for stmt in fn.body.statements:
        codegen._emit_statement(stmt, epilogue, function_return_type_name, emit_ctx, loop_labels=[])

    codegen.out.append(f"{epilogue}:")
    codegen._emit_function_epilogue(layout, function_return_type_name)


def emit_constructor_function(codegen: CodeGenerator, cls: ClassDecl) -> None:
    from compiler.codegen.legacy import _constructor_function_decl

    ctor_layout = codegen.constructor_layouts[cls.name]
    ctor_fn = _constructor_function_decl(cls, ctor_layout.label)
    target_label = ctor_layout.label
    epilogue = _epilogue_label(target_label)
    layout = codegen._build_layout_proxy(ctor_fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=cls.span.start.path,
    )

    codegen._emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen._emit_location_comment(
        file_path=cls.span.start.path,
        line=cls.span.start.line,
        column=cls.span.start.column,
    )
    codegen._emit_zero_slots(layout)
    codegen._emit_param_spills(ctor_fn.params, layout)

    if layout.root_slot_names:
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        codegen._emit_root_frame_setup(
            layout,
            root_count=len(layout.root_slot_names),
            first_root_offset=first_root_offset,
        )

    codegen._emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)

    codegen._emit_runtime_call_hook(
        fn_name=target_label,
        phase="before",
        label_counter=label_counter,
    )
    codegen._emit_root_slot_updates(layout)
    codegen.out.append("    call rt_thread_state")
    codegen.out.append("    mov rdi, rax")
    codegen.out.append(f"    lea rsi, [rip + {ctor_layout.type_symbol}]")
    codegen.out.append(f"    mov rdx, {ctor_layout.payload_bytes}")
    codegen.out.append("    call rt_alloc_obj")
    codegen._emit_runtime_call_hook(
        fn_name=target_label,
        phase="after",
        label_counter=label_counter,
    )
    codegen.out.append(f"    mov {_offset_operand(layout.slot_offsets['__nif_ctor_obj'])}, rax")

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
            codegen.out.append(f"    mov rcx, {_offset_operand(value_offset)}")
        else:
            if field_decl.initializer is None:
                _raise_codegen_error("constructor default initializer missing", span=field_decl.span)
            emit_expr(codegen, field_decl.initializer, emit_ctx)
            codegen.out.append("    mov rcx, rax")

        codegen.out.append(f"    mov rax, {_offset_operand(layout.slot_offsets['__nif_ctor_obj'])}")
        codegen.out.append(f"    mov qword ptr [rax + {field_offset}], rcx")

    codegen.out.append(f"    jmp {epilogue}")

    codegen.out.append(f"{epilogue}:")
    codegen._emit_ref_epilogue(layout)