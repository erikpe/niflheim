from __future__ import annotations

from compiler.ast_nodes import ImportDecl, ModuleAst
from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_fn import emit_debug_symbol_literals
from compiler.codegen.model import EmitContext
from compiler.codegen.semantic_emitter_expr import SemanticEmitContext, emit_expr
from compiler.codegen.semantic_emitter_stmt import emit_statement
from compiler.codegen.semantic_layout import build_layout
from compiler.semantic_ir import SemanticBlock, SemanticClass, SemanticFunction, SemanticMethod, SemanticParam, SemanticVarDecl
from compiler.semantic_symbols import FunctionId


def emit_function(codegen, declaration_tables, fn: SemanticFunction, *, label: str | None = None, global_symbol: bool | None = None) -> None:
    if fn.body is None:
        raise ValueError("semantic function emission requires a concrete body")
    target_label = label if label is not None else fn.function_id.name
    epilogue = f".L{target_label}_epilogue"
    layout = build_layout(fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=fn.span.start.path,
    )

    codegen.emit_frame_prologue(
        target_label,
        layout,
        global_symbol=(fn.is_export or fn.function_id.name == "main") if global_symbol is None else global_symbol,
    )
    codegen.emit_location_comment(file_path=fn.span.start.path, line=fn.span.start.line, column=fn.span.start.column)
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_to_ast_params(fn.params), layout)

    if layout.root_slot_count > 0:
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]] if layout.root_slot_names else layout.temp_root_slot_offsets[0]
        codegen.emit_root_frame_setup(layout, root_count=layout.root_slot_count, first_root_offset=first_root_offset)

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

    emit_ctx = SemanticEmitContext(
        emit_ctx=EmitContext(
            layout=layout,
            fn_name=target_label,
            label_counter=label_counter,
            method_labels={},
            method_return_types={},
            method_is_static={},
            constructor_labels={},
            function_return_types={},
            string_literal_labels=codegen.string_literal_labels,
            class_field_type_names={},
            temp_root_depth=[0],
        ),
        declaration_tables=declaration_tables,
    )

    for stmt in fn.body.statements:
        emit_statement(codegen, stmt, epilogue, fn.return_type_name, emit_ctx, loop_labels=[])

    codegen.asm.label(epilogue)
    codegen.emit_function_epilogue(layout, fn.return_type_name)


def emit_method(codegen, declaration_tables, cls: SemanticClass, method: SemanticMethod) -> None:
    method_fn = SemanticFunction(
        function_id=FunctionId(module_path=method.method_id.module_path, name=declaration_tables.method_labels_by_id[method.method_id]),
        params=[*(_receiver_param(cls, method) if not method.is_static else []), *method.params],
        return_type_name=method.return_type_name,
        body=method.body,
        is_export=False,
        is_extern=False,
        span=method.span,
    )
    emit_function(codegen, declaration_tables, method_fn, label=declaration_tables.method_labels_by_id[method.method_id], global_symbol=False)


def emit_constructor(codegen, declaration_tables, cls: SemanticClass) -> None:
    from compiler.semantic_symbols import ConstructorId

    ctor_id = ConstructorId(module_path=cls.class_id.module_path, class_name=cls.class_id.name)
    ctor_layout = declaration_tables.constructor_layouts_by_id[ctor_id]
    ctor_fn = SemanticFunction(
        function_id=FunctionId(module_path=cls.class_id.module_path, name=ctor_layout.label),
        params=[
            SemanticParam(name=field.name, type_name=field.type_name, span=field.span)
            for field in cls.fields
            if field.initializer is None
        ],
        return_type_name=cls.class_id.name,
        body=SemanticBlock(
            statements=[
                SemanticVarDecl(name="__nif_ctor_obj", type_name=cls.class_id.name, initializer=None, span=cls.span)
            ],
            span=cls.span,
        ),
        is_export=False,
        is_extern=False,
        span=cls.span,
    )

    target_label = ctor_layout.label
    epilogue = f".L{target_label}_epilogue"
    layout = build_layout(ctor_fn)
    label_counter = [0]
    fn_debug_name_label, fn_debug_file_label = emit_debug_symbol_literals(
        codegen,
        target_label=target_label,
        function_name=target_label,
        file_path=cls.span.start.path,
    )

    codegen.emit_frame_prologue(target_label, layout, global_symbol=False)
    codegen.emit_location_comment(file_path=cls.span.start.path, line=cls.span.start.line, column=cls.span.start.column)
    codegen.emit_zero_slots(layout)
    codegen.emit_param_spills(_to_ast_params(ctor_fn.params), layout)

    if layout.root_slot_names:
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        codegen.emit_root_frame_setup(layout, root_count=len(layout.root_slot_names), first_root_offset=first_root_offset)

    codegen.emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="before", label_counter=label_counter)
    codegen.emit_root_slot_updates(layout)
    codegen.asm.instr("call rt_thread_state")
    codegen.asm.instr("mov rdi, rax")
    codegen.asm.instr(f"lea rsi, [rip + {ctor_layout.type_symbol}]")
    codegen.asm.instr(f"mov rdx, {ctor_layout.payload_bytes}")
    codegen.asm.instr("call rt_alloc_obj")
    codegen.emit_runtime_call_hook(fn_name=target_label, phase="after", label_counter=label_counter)
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets['__nif_ctor_obj'])}, rax")

    emit_ctx = SemanticEmitContext(
        emit_ctx=EmitContext(
            layout=layout,
            fn_name=target_label,
            label_counter=label_counter,
            method_labels={},
            method_return_types={},
            method_is_static={},
            constructor_labels={},
            function_return_types={},
            string_literal_labels=codegen.string_literal_labels,
            class_field_type_names={},
            temp_root_depth=[0],
        ),
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
        codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets['__nif_ctor_obj'])}")
        codegen.asm.instr(f"mov qword ptr [rax + {field_offset}], rcx")

    codegen.asm.instr(f"jmp {epilogue}")
    codegen.asm.label(epilogue)
    codegen.emit_ref_epilogue(layout)


def _receiver_param(cls: SemanticClass, method: SemanticMethod) -> list[SemanticParam]:
    return [SemanticParam(name="__self", type_name=cls.class_id.name, span=method.span)]


def _to_ast_params(params: list[SemanticParam]):
    from compiler.ast_nodes import ParamDecl, TypeRef

    return [ParamDecl(name=param.name, type_ref=TypeRef(name=param.type_name, span=param.span), span=param.span) for param in params]