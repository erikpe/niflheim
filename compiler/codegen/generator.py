from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from compiler.common.type_names import TYPE_NAME_DOUBLE
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.model import FunctionLayout, RUNTIME_REF_ARG_INDICES
from compiler.codegen.asm import AsmBuilder, offset_operand, stack_slot_operand
from compiler.codegen.abi_sysv import plan_sysv_arg_locations

if TYPE_CHECKING:
    from compiler.codegen.linker import CodegenProgram


class CodeGenerator:
    def __init__(self) -> None:
        self.asm = AsmBuilder()
        self.string_literal_labels: dict[str, tuple[str, int]] = {}
        self.runtime_panic_message_labels: dict[str, str] = {}
        self.source_lines_by_path: dict[str, list[str] | None] = {}
        self.last_emitted_comment_location: tuple[str, int] | None = None
        self.aligned_call_label_counter: int = 0

    def runtime_panic_message_label(self, message: str) -> str:
        label = self.runtime_panic_message_labels.get(message)
        if label is not None:
            return label
        label = f"__nif_runtime_panic_msg_{len(self.runtime_panic_message_labels)}"
        self.runtime_panic_message_labels[message] = label
        return label

    def emit_aligned_call(self, target: str) -> None:
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

    def emit_location_comment(self, *, file_path: str, line: int, column: int) -> None:
        location_key = (file_path, line)
        if self.last_emitted_comment_location == location_key:
            return
        source_line = self._source_line_text(file_path, line)
        self.asm.comment(f"{file_path}:{line}:{column} | {source_line}")
        self.last_emitted_comment_location = location_key

    def emit_frame_prologue(self, target_label: str, layout: FunctionLayout, *, global_symbol: bool) -> None:
        if global_symbol:
            self.asm.directive(f".globl {target_label}")
        self.asm.label(target_label)
        self.asm.instr("push rbp")
        self.asm.instr("mov rbp, rsp")
        if layout.stack_size > 0:
            self.asm.instr(f"sub rsp, {layout.stack_size}")

    def emit_zero_slots(self, layout: FunctionLayout) -> None:
        for name in layout.slot_names:
            self.asm.instr(f"mov {offset_operand(layout.slot_offsets[name])}, 0")
        for name in layout.root_slot_names:
            self.asm.instr(f"mov {offset_operand(layout.root_slot_offsets[name])}, 0")
        for offset in layout.temp_root_slot_offsets:
            self.asm.instr(f"mov {offset_operand(offset)}, 0")

    def emit_param_spills(self, params: list[tuple[str, str, object | None]], layout: FunctionLayout) -> None:
        param_type_names = [type_name for _name, type_name, _span in params]
        arg_locations = plan_sysv_arg_locations(param_type_names)

        for (param_name, _param_type_name, param_span), (location_kind, location_register, stack_index) in zip(
            params, arg_locations
        ):
            offset = layout.slot_offsets.get(param_name)
            if offset is None:
                continue

            if location_kind == "int_reg":
                self.asm.instr(f"mov {offset_operand(offset)}, {location_register}")
                continue

            if location_kind == "float_reg":
                self.asm.instr(f"movq {offset_operand(offset)}, {location_register}")
                continue

            if location_kind == "stack":
                if stack_index is None:
                    codegen_types.raise_codegen_error(
                        "missing stack argument index while spilling parameters", span=param_span
                    )
                incoming_stack_offset = 16 + (stack_index * 8)
                self.asm.instr(f"mov rax, qword ptr [rbp + {incoming_stack_offset}]")
                self.asm.instr(f"mov {offset_operand(offset)}, rax")
                continue

            codegen_types.raise_codegen_error(f"unsupported argument location kind '{location_kind}'", span=param_span)

    def emit_trace_push(self, fn_debug_name_label: str, fn_debug_file_label: str, line: int, column: int) -> None:
        self.asm.instr(f"lea rdi, [rip + {fn_debug_name_label}]")
        self.asm.instr(f"lea rsi, [rip + {fn_debug_file_label}]")
        self.asm.instr(f"mov edx, {line}")
        self.asm.instr(f"mov ecx, {column}")
        self.asm.instr("call rt_trace_push")

    def emit_root_frame_setup(self, layout: FunctionLayout, *, root_count: int, first_root_offset: int) -> None:
        self.asm.instr("call rt_thread_state")
        self.asm.instr(f"mov {offset_operand(layout.thread_state_offset)}, rax")
        self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr(f"lea rsi, [rbp - {abs(first_root_offset)}]")
        self.asm.instr(f"mov edx, {root_count}")
        self.asm.instr("call rt_root_frame_init")
        self.asm.instr(f"mov rdi, {offset_operand(layout.thread_state_offset)}")
        self.asm.instr(f"lea rsi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr("call rt_push_roots")

    def emit_function_epilogue(self, layout: FunctionLayout, return_type_name: str) -> None:
        if return_type_name == TYPE_NAME_DOUBLE:
            self.asm.instr("sub rsp, 8")
            self.asm.instr("movq qword ptr [rsp], xmm0")
        else:
            self.asm.instr("push rax")
        if layout.root_slot_count > 0:
            self.asm.instr(f"mov rdi, {offset_operand(layout.thread_state_offset)}")
            self.asm.instr("call rt_pop_roots")
        self.asm.instr("call rt_trace_pop")
        if return_type_name == TYPE_NAME_DOUBLE:
            self.asm.instr("movq xmm0, qword ptr [rsp]")
            self.asm.instr("add rsp, 8")
        else:
            self.asm.instr("pop rax")
        self.asm.instr("mov rsp, rbp")
        self.asm.instr("pop rbp")
        self.asm.instr("ret")

    def emit_ref_epilogue(self, layout: FunctionLayout) -> None:
        self.asm.instr("push rax")
        if layout.root_slot_names:
            self.asm.instr(f"mov rdi, {offset_operand(layout.thread_state_offset)}")
            self.asm.instr("call rt_pop_roots")
        self.asm.instr("call rt_trace_pop")
        self.asm.instr("pop rax")
        self.asm.instr("mov rsp, rbp")
        self.asm.instr("pop rbp")
        self.asm.instr("ret")

    def emit_runtime_call_hook(
        self, *, fn_name: str, phase: str, label_counter: list[int], line: int | None = None, column: int | None = None
    ) -> None:
        label = codegen_symbols.next_label(fn_name, f"rt_safepoint_{phase}", label_counter)
        self.asm.label(label)
        self.asm.comment("runtime safepoint hook")
        if phase == "before" and line is not None and column is not None:
            self.asm.instr(f"mov edi, {line}")
            self.asm.instr(f"mov esi, {column}")
            self.asm.instr("call rt_trace_set_location")

    def emit_root_slot_updates(self, layout: FunctionLayout) -> None:
        if not layout.root_slot_names:
            return

        self.asm.comment("spill reference-typed roots to root slots")
        for name in layout.root_slot_names:
            value_offset = layout.slot_offsets[name]
            slot_index = layout.root_slot_indices[name]
            self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            self.asm.instr(f"mov rdx, {offset_operand(value_offset)}")
            self.asm.instr(f"mov esi, {slot_index}")
            self.asm.instr("call rt_root_slot_store")

    def emit_runtime_call_arg_temp_roots(
        self, layout: FunctionLayout, target_name: str, arg_count: int, *, span: object | None = None
    ) -> int:
        if layout.root_slot_count <= 0:
            return 0
        ref_indices = [index for index in RUNTIME_REF_ARG_INDICES.get(target_name, ()) if index < arg_count]
        if not ref_indices:
            return 0
        if len(ref_indices) > len(layout.temp_root_slot_offsets):
            codegen_types.raise_codegen_error(
                "insufficient temporary root slots for runtime call argument rooting", span=span
            )

        for temp_index, arg_index in enumerate(ref_indices):
            self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            if arg_index == 0:
                self.asm.instr("mov rdx, qword ptr [rsp]")
            else:
                self.asm.instr(f"mov rdx, qword ptr [rsp + {arg_index * 8}]")
            self.asm.instr(f"mov esi, {layout.temp_root_slot_start_index + temp_index}")
            self.asm.instr("call rt_root_slot_store")
        return len(ref_indices)

    def emit_clear_runtime_call_arg_temp_roots(self, layout: FunctionLayout, rooted_count: int) -> None:
        self.emit_clear_temp_root_slots(layout, 0, rooted_count)

    def emit_clear_temp_root_slots(self, layout: FunctionLayout, start_index: int, count: int) -> None:
        for temp_index in range(start_index, start_index + count):
            self.asm.instr(f"mov {offset_operand(layout.temp_root_slot_offsets[temp_index])}, 0")

    def emit_temp_arg_root_from_rsp(
        self, layout: FunctionLayout, temp_slot_index: int, stack_byte_offset: int, *, span: object | None = None
    ) -> None:
        if not layout.temp_root_slot_offsets:
            return
        if temp_slot_index >= len(layout.temp_root_slot_offsets):
            codegen_types.raise_codegen_error("insufficient temporary root slots for call argument rooting", span=span)

        self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr(f"mov rdx, {stack_slot_operand('rsp', stack_byte_offset)}")
        self.asm.instr(f"mov esi, {layout.temp_root_slot_start_index + temp_slot_index}")
        self.asm.instr("call rt_root_slot_store")

    def emit_temp_root_slot_store(
        self, layout: FunctionLayout, temp_slot_index: int, source_register: str, *, span: object | None = None
    ) -> None:
        if not layout.temp_root_slot_offsets:
            return
        if temp_slot_index >= len(layout.temp_root_slot_offsets):
            codegen_types.raise_codegen_error("insufficient temporary root slots for interface dispatch", span=span)

        self.asm.instr(f"mov {offset_operand(layout.temp_root_slot_offsets[temp_slot_index])}, {source_register}")
        self.asm.instr(f"lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.asm.instr(f"mov rdx, {source_register}")
        self.asm.instr(f"mov esi, {layout.temp_root_slot_start_index + temp_slot_index}")
        self.asm.instr("call rt_root_slot_store")

    def emit_bool_normalize(self) -> None:
        self.asm.instr("cmp rax, 0")
        self.asm.instr("setne al")
        self.asm.instr("movzx rax, al")


def emit_asm(program: CodegenProgram) -> str:
    from compiler.codegen.program_generator import emit_program

    return emit_program(program)
