from __future__ import annotations

from pathlib import Path

from compiler.ast_nodes import (
    ArrayCtorExpr,
    ArrayTypeRef,
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    BreakStmt,
    CallExpr,
    CastExpr,
    ClassDecl,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    FunctionTypeRef,
    FunctionDecl,
    IdentifierExpr,
    IndexExpr,
    IfStmt,
    LiteralExpr,
    MethodDecl,
    ModuleAst,
    NullExpr,
    ParamDecl,
    ContinueStmt,
    ForInStmt,
    ReturnStmt,
    Statement,
    TypeRef,
    TypeRefNode,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

from compiler.codegen.model import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_GET_RUNTIME_CALLS,
    ARRAY_SET_RUNTIME_CALLS,
    ARRAY_SET_SLICE_RUNTIME_CALLS,
    ARRAY_SLICE_RUNTIME_CALLS,
    ConstructorLayout,
    EmitContext,
    FLOAT_PARAM_REGISTERS,
    FunctionLayout,
    RUNTIME_REF_ARG_INDICES,
    RUNTIME_RETURN_TYPES,
)
from compiler.codegen.asm import AsmBuilder, _offset_operand, _stack_slot_operand
from compiler.codegen.abi_sysv import _plan_sysv_arg_locations
from compiler.codegen.call_resolution import (
    _field_receiver_type_name,
    _infer_expression_type_name,
    _resolve_call_target_name,
    _resolve_callable_value_label,
)
from compiler.codegen.emitter_expr import emit_expr
from compiler.codegen.emitter_stmt import emit_statement
from compiler.codegen.layout import _build_layout
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double
from compiler.codegen.ops_int import emit_integer_binary_op, emit_integer_unary_op
from compiler.codegen.strings import (
    STR_CLASS_NAME,
    collect_string_literals,
    decode_char_literal,
    decode_string_literal,
    escape_asm_string_bytes,
    escape_c_string,
    is_str_type_name,
)
from compiler.codegen.symbols import (
    _epilogue_label,
    _is_runtime_call_name,
    _mangle_constructor_symbol,
    _mangle_method_symbol,
    _mangle_type_name_symbol,
    _mangle_type_symbol,
    _next_label,
)
from compiler.codegen.types import (
    _array_element_runtime_kind,
    _array_element_type_name,
    _double_literal_bits,
    _function_type_return_type_name,
    _is_array_type_name,
    _is_double_literal_text,
    _is_function_type_name,
    _is_reference_type_name,
    _raise_codegen_error,
    _type_ref_name,
)


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _collect_reference_cast_types_from_expr(expr: Expression, out: set[str]) -> None:
    if isinstance(expr, CastExpr):
        target_type_name = _type_ref_name(expr.type_ref)
        if _is_reference_type_name(target_type_name):
            out.add(target_type_name)
        _collect_reference_cast_types_from_expr(expr.operand, out)
        return

    if isinstance(expr, BinaryExpr):
        _collect_reference_cast_types_from_expr(expr.left, out)
        _collect_reference_cast_types_from_expr(expr.right, out)
        return

    if isinstance(expr, UnaryExpr):
        _collect_reference_cast_types_from_expr(expr.operand, out)
        return

    if isinstance(expr, CallExpr):
        _collect_reference_cast_types_from_expr(expr.callee, out)
        for arg in expr.arguments:
            _collect_reference_cast_types_from_expr(arg, out)
        return


def _collect_reference_cast_types_from_stmt(stmt: Statement, out: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            _collect_reference_cast_types_from_expr(stmt.initializer, out)
        return

    if isinstance(stmt, AssignStmt):
        _collect_reference_cast_types_from_expr(stmt.value, out)
        return

    if isinstance(stmt, ExprStmt):
        _collect_reference_cast_types_from_expr(stmt.expression, out)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_reference_cast_types_from_expr(stmt.value, out)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_reference_cast_types_from_stmt(nested, out)
        return

    if isinstance(stmt, IfStmt):
        _collect_reference_cast_types_from_expr(stmt.condition, out)
        _collect_reference_cast_types_from_stmt(stmt.then_branch, out)
        if stmt.else_branch is not None:
            _collect_reference_cast_types_from_stmt(stmt.else_branch, out)
        return

    if isinstance(stmt, WhileStmt):
        _collect_reference_cast_types_from_expr(stmt.condition, out)
        _collect_reference_cast_types_from_stmt(stmt.body, out)
        return


def _collect_reference_cast_types(module_ast: ModuleAst) -> list[str]:
    names: set[str] = set()
    for cls in module_ast.classes:
        names.add(cls.name)
    for fn in module_ast.functions:
        if fn.body is None:
            continue
        for stmt in fn.body.statements:
            _collect_reference_cast_types_from_stmt(stmt, names)
    for cls in module_ast.classes:
        for method in cls.methods:
            for stmt in method.body.statements:
                _collect_reference_cast_types_from_stmt(stmt, names)
    return sorted(names)


def _method_function_decl(class_decl: ClassDecl, method_decl: MethodDecl, label: str) -> FunctionDecl:
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


def _constructor_function_decl(class_decl: ClassDecl, label: str) -> FunctionDecl:
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


class CodeGenerator:
    def __init__(self, module_ast: ModuleAst) -> None:
        self.module_ast = module_ast
        self.asm = AsmBuilder()
        self.out = self.asm.lines
        self.method_labels: dict[tuple[str, str], str] = {}
        self.method_return_types: dict[tuple[str, str], str] = {}
        self.method_is_static: dict[tuple[str, str], bool] = {}
        self.function_return_types: dict[str, str] = {}
        self.constructor_layouts: dict[str, ConstructorLayout] = {}
        self.constructor_labels: dict[str, str] = {}
        self.class_field_offsets: dict[tuple[str, str], int] = {}
        self.class_field_type_names: dict[tuple[str, str], str] = {}
        self.string_literal_labels: dict[str, tuple[str, int]] = {}
        self.runtime_panic_message_labels: dict[str, str] = {}
        self.source_lines_by_path: dict[str, list[str] | None] = {}
        self.last_emitted_comment_location: tuple[str, int] | None = None
        self.aligned_call_label_counter: int = 0

    def _runtime_panic_message_label(self, message: str) -> str:
        label = self.runtime_panic_message_labels.get(message)
        if label is not None:
            return label
        label = f"__nif_runtime_panic_msg_{len(self.runtime_panic_message_labels)}"
        self.runtime_panic_message_labels[message] = label
        return label

    def _emit_aligned_call(self, target: str) -> None:
        # Keep call-site stack ABI-correct even when surrounding code has
        # temporary pushes we do not explicitly track in codegen state.
        label_id = self.aligned_call_label_counter
        self.aligned_call_label_counter += 1
        aligned_label = f".L__nif_aligned_call_{label_id}"
        done_label = f".L__nif_aligned_call_done_{label_id}"
        self.asm.instr("test rsp, 8")
        self.asm.instr(f"jz {aligned_label}")
        self.asm.instr("sub rsp, 8")
        self.asm.instr(f"call {target}")
        self.asm.instr("add rsp, 8")
        self.asm.instr(f"jmp {done_label}")
        self.asm.label(aligned_label)
        self.asm.instr(f"call {target}")
        self.asm.label(done_label)

    def _source_line_text(self, file_path: str, line: int) -> str:
        if line <= 0:
            return ""
        lines = self.source_lines_by_path.get(file_path)
        if lines is None and file_path not in self.source_lines_by_path:
            try:
                lines = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = None
            self.source_lines_by_path[file_path] = lines
        if lines is None or line > len(lines):
            return ""
        return lines[line - 1].strip()

    def _emit_location_comment(self, *, file_path: str, line: int, column: int) -> None:
        location_key = (file_path, line)
        if self.last_emitted_comment_location == location_key:
            return
        source_line = self._source_line_text(file_path, line)
        self.asm.comment(f"{file_path}:{line}:{column} | {source_line}")
        self.last_emitted_comment_location = location_key

    def _build_symbol_tables(self) -> None:
        for cls in self.module_ast.classes:
            for method in cls.methods:
                self.method_labels[(cls.name, method.name)] = _mangle_method_symbol(cls.name, method.name)
                self.method_return_types[(cls.name, method.name)] = _type_ref_name(method.return_type)
                self.method_is_static[(cls.name, method.name)] = method.is_static

        for fn in self.module_ast.functions:
            self.function_return_types[fn.name] = _type_ref_name(fn.return_type)

        for cls in self.module_ast.classes:
            ctor_label = _mangle_constructor_symbol(cls.name)
            ctor_layout = ConstructorLayout(
                class_name=cls.name,
                label=ctor_label,
                type_symbol=_mangle_type_symbol(cls.name),
                payload_bytes=len(cls.fields) * 8,
                field_names=[field.name for field in cls.fields],
                param_field_names=[field.name for field in cls.fields if field.initializer is None],
            )
            self.constructor_layouts[cls.name] = ctor_layout
            self.constructor_labels[cls.name] = ctor_label
            for field_index, field in enumerate(cls.fields):
                self.class_field_offsets[(cls.name, field.name)] = 24 + (8 * field_index)
                self.class_field_type_names[(cls.name, field.name)] = _type_ref_name(field.type_ref)

    def _emit_frame_prologue(self, target_label: str, layout: FunctionLayout, *, global_symbol: bool) -> None:
        if global_symbol:
            self.asm.directive(f".globl {target_label}")
        self.asm.label(target_label)
        self.asm.instr("push rbp")
        self.asm.instr("mov rbp, rsp")
        if layout.stack_size > 0:
            self.asm.instr(f"sub rsp, {layout.stack_size}")

    def _emit_zero_slots(self, layout: FunctionLayout) -> None:
        for name in layout.slot_names:
            self.asm.instr(f"mov {_offset_operand(layout.slot_offsets[name])}, 0")
        for name in layout.root_slot_names:
            self.asm.instr(f"mov {_offset_operand(layout.root_slot_offsets[name])}, 0")
        for offset in layout.temp_root_slot_offsets:
            self.asm.instr(f"mov {_offset_operand(offset)}, 0")

    def _emit_param_spills(self, params: list[ParamDecl], layout: FunctionLayout) -> None:
        param_type_names = [_type_ref_name(param.type_ref) for param in params]
        arg_locations = _plan_sysv_arg_locations(param_type_names)

        for param, (location_kind, location_register, stack_index) in zip(params, arg_locations):
            offset = layout.slot_offsets.get(param.name)
            if offset is None:
                continue

            if location_kind == "int_reg":
                self.asm.instr(f"mov {_offset_operand(offset)}, {location_register}")
                continue

            if location_kind == "float_reg":
                self.asm.instr(f"movq {_offset_operand(offset)}, {location_register}")
                continue

            if location_kind == "stack":
                if stack_index is None:
                    _raise_codegen_error("missing stack argument index while spilling parameters", span=param.span)
                incoming_stack_offset = 16 + (stack_index * 8)
                self.asm.instr(f"mov rax, qword ptr [rbp + {incoming_stack_offset}]")
                self.asm.instr(f"mov {_offset_operand(offset)}, rax")
                continue

            _raise_codegen_error(f"unsupported argument location kind '{location_kind}'", span=param.span)

    def _emit_trace_push(self, fn_debug_name_label: str, fn_debug_file_label: str, line: int, column: int) -> None:
        self.asm.instr(f"lea rdi, [rip + {fn_debug_name_label}]")
        self.asm.instr(f"lea rsi, [rip + {fn_debug_file_label}]")
        self.asm.instr(f"mov edx, {line}")
        self.asm.instr(f"mov ecx, {column}")
        self.asm.instr("call rt_trace_push")

    def _emit_root_frame_setup(self, layout: FunctionLayout, *, root_count: int, first_root_offset: int) -> None:
        self.asm.instr("call rt_thread_state")
        self.asm.instr(f"mov {_offset_operand(layout.thread_state_offset)}, rax")
        self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr(f"lea rsi, [rbp - {abs(first_root_offset)}]")
        self.asm.instr(f"mov edx, {root_count}")
        self.asm.instr("call rt_root_frame_init")
        self.asm.instr(f"mov rdi, {_offset_operand(layout.thread_state_offset)}")
        self.asm.instr(f"lea rsi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr("call rt_push_roots")

    def _emit_function_epilogue(self, layout: FunctionLayout, return_type_name: str) -> None:
        if return_type_name == "double":
            self.asm.instr("sub rsp, 8")
            self.asm.instr("movq qword ptr [rsp], xmm0")
        else:
            self.asm.instr("push rax")
        if layout.root_slot_count > 0:
            self.asm.instr(f"mov rdi, {_offset_operand(layout.thread_state_offset)}")
            self.asm.instr("call rt_pop_roots")
        self.asm.instr("call rt_trace_pop")
        if return_type_name == "double":
            self.asm.instr("movq xmm0, qword ptr [rsp]")
            self.asm.instr("add rsp, 8")
        else:
            self.asm.instr("pop rax")
        self.asm.instr("mov rsp, rbp")
        self.asm.instr("pop rbp")
        self.asm.instr("ret")

    def _emit_ref_epilogue(self, layout: FunctionLayout) -> None:
        self.asm.instr("push rax")
        if layout.root_slot_names:
            self.asm.instr(f"mov rdi, {_offset_operand(layout.thread_state_offset)}")
            self.asm.instr("call rt_pop_roots")
        self.asm.instr("call rt_trace_pop")
        self.asm.instr("pop rax")
        self.asm.instr("mov rsp, rbp")
        self.asm.instr("pop rbp")
        self.asm.instr("ret")

    def _emit_runtime_call_hook(
        self,
        *,
        fn_name: str,
        phase: str,
        label_counter: list[int],
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        label = _next_label(fn_name, f"rt_safepoint_{phase}", label_counter)
        self.asm.label(label)
        self.asm.comment("runtime safepoint hook")
        if phase == "before" and line is not None and column is not None:
            self.asm.instr(f"mov edi, {line}")
            self.asm.instr(f"mov esi, {column}")
            self.asm.instr("call rt_trace_set_location")

    def _emit_root_slot_updates(self, layout: FunctionLayout) -> None:
        if not layout.root_slot_names:
            return

        self.out.append("    # spill reference-typed roots to root slots")
        for name in layout.root_slot_names:
            value_offset = layout.slot_offsets[name]
            slot_index = layout.root_slot_indices[name]
            self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            self.out.append(f"    mov rdx, {_offset_operand(value_offset)}")
            self.out.append(f"    mov esi, {slot_index}")
            self.out.append("    call rt_root_slot_store")

    def _emit_runtime_call_arg_temp_roots(
        self,
        layout: FunctionLayout,
        target_name: str,
        arg_count: int,
        *,
        span: object | None = None,
    ) -> int:
        if layout.root_slot_count <= 0:
            return 0
        ref_indices = [index for index in RUNTIME_REF_ARG_INDICES.get(target_name, ()) if index < arg_count]
        if not ref_indices:
            return 0
        if len(ref_indices) > len(layout.temp_root_slot_offsets):
            _raise_codegen_error("insufficient temporary root slots for runtime call argument rooting", span=span)

        for temp_index, arg_index in enumerate(ref_indices):
            self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            if arg_index == 0:
                self.out.append("    mov rdx, qword ptr [rsp]")
            else:
                self.out.append(f"    mov rdx, qword ptr [rsp + {arg_index * 8}]")
            self.out.append(f"    mov esi, {layout.temp_root_slot_start_index + temp_index}")
            self.out.append("    call rt_root_slot_store")
        return len(ref_indices)

    def _emit_clear_runtime_call_arg_temp_roots(self, layout: FunctionLayout, rooted_count: int) -> None:
        self._emit_clear_temp_root_slots(layout, 0, rooted_count)

    def _emit_clear_temp_root_slots(self, layout: FunctionLayout, start_index: int, count: int) -> None:
        for temp_index in range(start_index, start_index + count):
            self.out.append(f"    mov {_offset_operand(layout.temp_root_slot_offsets[temp_index])}, 0")

    def _emit_temp_arg_root_from_rsp(
        self,
        layout: FunctionLayout,
        temp_slot_index: int,
        stack_byte_offset: int,
        *,
        span: object | None = None,
    ) -> None:
        if not layout.temp_root_slot_offsets:
            return
        if temp_slot_index >= len(layout.temp_root_slot_offsets):
            _raise_codegen_error("insufficient temporary root slots for call argument rooting", span=span)

        self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.out.append(f"    mov rdx, {_stack_slot_operand('rsp', stack_byte_offset)}")
        self.out.append(f"    mov esi, {layout.temp_root_slot_start_index + temp_slot_index}")
        self.out.append("    call rt_root_slot_store")

    def _emit_bool_normalize(self) -> None:
        self.out.append("    cmp rax, 0")
        self.out.append("    setne al")
        self.out.append("    movzx rax, al")

    def _mangle_type_symbol_proxy(self, type_name: str) -> str:
        return _mangle_type_symbol(type_name)

    def _emit_expr(self, expr: Expression, ctx: EmitContext) -> None:
        emit_expr(self, expr, ctx)

    def _emit_call_expr(self, expr: CallExpr, ctx: EmitContext) -> None:
        emit_expr(self, expr, ctx)

    def _emit_unary_expr(self, expr: UnaryExpr, ctx: EmitContext) -> None:
        emit_expr(self, expr, ctx)

    def _emit_logical_binary_expr(self, expr: BinaryExpr, *, fn_name: str, label_counter: list[int], ctx: EmitContext) -> bool:
        before = len(self.out)
        emit_expr(self, expr, ctx)
        return len(self.out) != before

    def _emit_binary_expr(self, expr: BinaryExpr, ctx: EmitContext) -> None:
        emit_expr(self, expr, ctx)

    def _emit_statement(
        self,
        stmt: Statement,
        epilogue_label: str,
        function_return_type_name: str,
        ctx: EmitContext,
        loop_labels: list[tuple[str, str]],
    ) -> None:
        emit_statement(self, stmt, epilogue_label, function_return_type_name, ctx, loop_labels)

    def _emit_debug_symbol_literals(
        self,
        *,
        target_label: str,
        function_name: str,
        file_path: str,
    ) -> tuple[str, str]:
        safe_target = target_label.replace(".", "_").replace(":", "_")
        fn_label = f"__nif_dbg_fn_{safe_target}"
        file_label = f"__nif_dbg_file_{safe_target}"
        self.out.append("")
        self.out.append(".section .rodata")
        self.out.append(f"{fn_label}:")
        self.out.append(f'    .asciz "{escape_c_string(function_name)}"')
        self.out.append(f"{file_label}:")
        self.out.append(f'    .asciz "{escape_c_string(file_path)}"')
        self.out.append("")
        self.out.append(".text")
        return fn_label, file_label

    def _emit_function(self, fn: FunctionDecl, *, label: str | None = None) -> None:
        target_label = label if label is not None else fn.name
        epilogue = _epilogue_label(target_label)
        layout = _build_layout(fn)
        label_counter = [0]
        fn_debug_name_label, fn_debug_file_label = self._emit_debug_symbol_literals(
            target_label=target_label,
            function_name=target_label,
            file_path=fn.span.start.path,
        )

        self._emit_frame_prologue(target_label, layout, global_symbol=label is None and (fn.is_export or fn.name == "main"))
        self._emit_location_comment(
            file_path=fn.span.start.path,
            line=fn.span.start.line,
            column=fn.span.start.column,
        )
        self._emit_zero_slots(layout)
        self._emit_param_spills(fn.params, layout)

        if layout.root_slot_count > 0:
            if layout.root_slot_names:
                first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
            else:
                first_root_offset = layout.temp_root_slot_offsets[0]
            self._emit_root_frame_setup(
                layout,
                root_count=layout.root_slot_count,
                first_root_offset=first_root_offset,
            )

        self._emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

        emit_ctx = EmitContext(
            layout=layout,
            fn_name=target_label,
            label_counter=label_counter,
            method_labels=self.method_labels,
            method_return_types=self.method_return_types,
            method_is_static=self.method_is_static,
            constructor_labels=self.constructor_labels,
            function_return_types=self.function_return_types,
            string_literal_labels=self.string_literal_labels,
            class_field_type_names=self.class_field_type_names,
            temp_root_depth=[0],
        )

        for stmt in fn.body.statements:
            self._emit_statement(stmt, epilogue, _type_ref_name(fn.return_type), emit_ctx, loop_labels=[])

        self.out.append(f"{epilogue}:")
        self._emit_function_epilogue(layout, _type_ref_name(fn.return_type))

    def _emit_constructor_function(self, cls: ClassDecl) -> None:
        ctor_layout = self.constructor_layouts[cls.name]
        ctor_fn = _constructor_function_decl(cls, ctor_layout.label)
        target_label = ctor_layout.label
        epilogue = _epilogue_label(target_label)
        layout = _build_layout(ctor_fn)
        label_counter = [0]
        fn_debug_name_label, fn_debug_file_label = self._emit_debug_symbol_literals(
            target_label=target_label,
            function_name=target_label,
            file_path=cls.span.start.path,
        )

        self._emit_frame_prologue(target_label, layout, global_symbol=False)
        self._emit_location_comment(
            file_path=cls.span.start.path,
            line=cls.span.start.line,
            column=cls.span.start.column,
        )
        self._emit_zero_slots(layout)
        self._emit_param_spills(ctor_fn.params, layout)

        if layout.root_slot_names:
            first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
            self._emit_root_frame_setup(
                layout,
                root_count=len(layout.root_slot_names),
                first_root_offset=first_root_offset,
            )

        self._emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)

        self._emit_runtime_call_hook(
            fn_name=target_label,
            phase="before",
            label_counter=label_counter,
        )
        self._emit_root_slot_updates(layout)
        self.out.append("    call rt_thread_state")
        self.out.append("    mov rdi, rax")
        self.out.append(f"    lea rsi, [rip + {ctor_layout.type_symbol}]")
        self.out.append(f"    mov rdx, {ctor_layout.payload_bytes}")
        self.out.append("    call rt_alloc_obj")
        self._emit_runtime_call_hook(
            fn_name=target_label,
            phase="after",
            label_counter=label_counter,
        )
        self.out.append(f"    mov {_offset_operand(layout.slot_offsets['__nif_ctor_obj'])}, rax")

        emit_ctx = EmitContext(
            layout=layout,
            fn_name=target_label,
            label_counter=label_counter,
            method_labels=self.method_labels,
            method_return_types=self.method_return_types,
            method_is_static=self.method_is_static,
            constructor_labels=self.constructor_labels,
            function_return_types=self.function_return_types,
            string_literal_labels=self.string_literal_labels,
            class_field_type_names=self.class_field_type_names,
            temp_root_depth=[0],
        )

        param_fields = set(ctor_layout.param_field_names)
        field_decl_by_name = {field.name: field for field in cls.fields}

        for field_index, field_name in enumerate(ctor_layout.field_names):
            field_offset = 24 + (8 * field_index)
            field_decl = field_decl_by_name[field_name]
            if field_name in param_fields:
                value_offset = layout.slot_offsets[field_name]
                self.out.append(f"    mov rcx, {_offset_operand(value_offset)}")
            else:
                if field_decl.initializer is None:
                    _raise_codegen_error("constructor default initializer missing", span=field_decl.span)
                self._emit_expr(field_decl.initializer, emit_ctx)
                self.out.append("    mov rcx, rax")

            self.out.append(f"    mov rax, {_offset_operand(layout.slot_offsets['__nif_ctor_obj'])}")
            self.out.append(f"    mov qword ptr [rax + {field_offset}], rcx")

        self.out.append(f"    jmp {epilogue}")

        self.out.append(f"{epilogue}:")
        self._emit_ref_epilogue(layout)

    def _emit_string_literal_section(self) -> dict[str, tuple[str, int]]:
        string_literals = collect_string_literals(self.module_ast)
        labels: dict[str, tuple[str, int]] = {}
        if not string_literals:
            return labels

        self.out.append("")
        self.out.append(".section .rodata")
        for index, literal in enumerate(string_literals):
            label = f"__nif_str_lit_{index}"
            data = decode_string_literal(literal)
            labels[literal] = (label, len(data))
            self.out.append(f"{label}:")
            self.out.append(f'    .asciz "{escape_asm_string_bytes(data)}"')

        return labels

    def _emit_type_metadata_section(self) -> None:
        class_type_names = [cls.name for cls in self.module_ast.classes]
        cast_type_names = _collect_reference_cast_types(self.module_ast)
        type_names = sorted(set(class_type_names) | set(cast_type_names))
        if not type_names:
            return

        class_decls_by_name = {cls.name: cls for cls in self.module_ast.classes}
        pointer_offset_symbols: dict[str, tuple[str, list[int]]] = {}
        for type_name in type_names:
            class_decl = class_decls_by_name.get(type_name)
            if class_decl is None:
                continue
            pointer_offsets = [
                24 + (8 * field_index)
                for field_index, field in enumerate(class_decl.fields)
                if _is_reference_type_name(_type_ref_name(field.type_ref))
            ]
            if pointer_offsets:
                pointer_offset_symbols[type_name] = (
                    f"{_mangle_type_name_symbol(type_name)}__ptr_offsets",
                    pointer_offsets,
                )

        self.out.append("")
        self.out.append(".section .rodata")
        for type_name in type_names:
            self.out.append(f"{_mangle_type_name_symbol(type_name)}:")
            self.out.append(f'    .asciz "{type_name}"')
        for symbol, pointer_offsets in pointer_offset_symbols.values():
            self.out.append(f"{symbol}:")
            for offset in pointer_offsets:
                self.out.append(f"    .long {offset}")

        self.out.append("")
        self.out.append(".data")
        for type_name in type_names:
            type_sym = _mangle_type_symbol(type_name)
            name_sym = _mangle_type_name_symbol(type_name)
            pointer_offsets_meta = pointer_offset_symbols.get(type_name)
            if pointer_offsets_meta is None:
                type_flags = 0
                pointer_offsets_sym = "0"
                pointer_offsets_count = 0
            else:
                pointer_offsets_sym = pointer_offsets_meta[0]
                pointer_offsets_count = len(pointer_offsets_meta[1])
                type_flags = 1
            self.out.append("    .p2align 3")
            self.out.append(f"{type_sym}:")
            self.out.append("    .long 0")
            self.out.append(f"    .long {type_flags}")
            self.out.append("    .long 1")
            self.out.append("    .long 8")
            self.out.append("    .quad 0")
            self.out.append(f"    .quad {name_sym}")
            self.out.append("    .quad 0")
            self.out.append(f"    .quad {pointer_offsets_sym}")
            self.out.append(f"    .long {pointer_offsets_count}")
            self.out.append("    .long 0")

    def _emit_runtime_panic_messages_section(self) -> None:
        if not self.runtime_panic_message_labels:
            return

        self.out.append("")
        self.out.append(".section .rodata")
        for message, label in self.runtime_panic_message_labels.items():
            self.out.append(f"{label}:")
            self.out.append(f'    .asciz "{escape_c_string(message)}"')

    def generate(self) -> str:
        self._emit_type_metadata_section()
        self.string_literal_labels = self._emit_string_literal_section()

        self.asm.blank()
        self.asm.directive(".text")

        self._build_symbol_tables()

        for fn in self.module_ast.functions:
            if fn.is_extern:
                continue
            self.asm.blank()
            self._emit_function(fn)

        for cls in self.module_ast.classes:
            for method in cls.methods:
                self.asm.blank()
                method_label = self.method_labels[(cls.name, method.name)]
                method_fn = _method_function_decl(cls, method, method_label)
                self._emit_function(method_fn, label=method_label)

        for cls in self.module_ast.classes:
            self.asm.blank()
            self._emit_constructor_function(cls)

        self._emit_runtime_panic_messages_section()

        self.asm.blank()
        self.asm.directive('.section .note.GNU-stack,"",@progbits')
        self.asm.blank()
        return self.asm.build()


def emit_asm(module_ast: ModuleAst) -> str:
    return CodeGenerator(module_ast).generate()
