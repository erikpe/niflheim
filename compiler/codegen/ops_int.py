from __future__ import annotations

from collections.abc import Callable

from compiler.codegen.asm import AsmBuilder


def emit_integer_unary_op(
    asm: AsmBuilder,
    *,
    operator: str,
    operand_type_name: str,
    emit_bool_normalize: Callable[[], None],
) -> bool:
    if operator == "-":
        asm.instr("neg rax")
        if operand_type_name == "u8":
            asm.instr("and rax, 255")
        return True

    if operator == "~":
        asm.instr("not rax")
        if operand_type_name == "u8":
            asm.instr("and rax, 255")
        return True

    if operator == "!":
        emit_bool_normalize()
        asm.instr("xor rax, 1")
        return True

    return False


def emit_integer_binary_op(
    asm: AsmBuilder,
    *,
    operator: str,
    operand_type_name: str,
    fn_name: str,
    label_counter: list[int],
    next_label: Callable[[str, str, list[int]], str],
    runtime_panic_message_label: Callable[[str], str],
    emit_aligned_call: Callable[[str], None],
) -> bool:
    is_unsigned = operand_type_name in {"u64", "u8"}
    if operator == "+":
        asm.instr("add rax, rcx")
        return True
    if operator == "-":
        asm.instr("sub rax, rcx")
        return True
    if operator == "*":
        asm.instr("imul rax, rcx")
        return True
    if operator == "**":
        pow_loop_label = next_label(fn_name, "pow_loop", label_counter)
        pow_done_label = next_label(fn_name, "pow_done", label_counter)
        pow_skip_mul_label = next_label(fn_name, "pow_skip_mul", label_counter)
        asm.instr("mov r8, 1")
        asm.instr("mov r9, rax")
        asm.label(pow_loop_label)
        asm.instr("test rcx, rcx")
        asm.instr(f"je {pow_done_label}")
        asm.instr("test rcx, 1")
        asm.instr(f"je {pow_skip_mul_label}")
        asm.instr("imul r8, r9")
        asm.label(pow_skip_mul_label)
        asm.instr("imul r9, r9")
        asm.instr("shr rcx, 1")
        asm.instr(f"jmp {pow_loop_label}")
        asm.label(pow_done_label)
        asm.instr("mov rax, r8")
        return True
    if operator == "/":
        if is_unsigned:
            asm.instr("xor rdx, rdx")
            asm.instr("div rcx")
        else:
            asm.instr("cqo")
            asm.instr("idiv rcx")
            done_label = next_label(fn_name, "sdiv_done", label_counter)
            asm.instr("test rdx, rdx")
            asm.instr(f"je {done_label}")
            asm.instr("mov r8, rdx")
            asm.instr("xor r8, rcx")
            asm.instr(f"jns {done_label}")
            asm.instr("sub rax, 1")
            asm.label(done_label)
        return True
    if operator == "%":
        if is_unsigned:
            asm.instr("xor rdx, rdx")
            asm.instr("div rcx")
        else:
            asm.instr("cqo")
            asm.instr("idiv rcx")
            done_label = next_label(fn_name, "smod_done", label_counter)
            asm.instr("mov rax, rdx")
            asm.instr("test rax, rax")
            asm.instr(f"je {done_label}")
            asm.instr("mov r8, rax")
            asm.instr("xor r8, rcx")
            asm.instr(f"jns {done_label}")
            asm.instr("add rax, rcx")
            asm.label(done_label)
            return True
        asm.instr("mov rax, rdx")
        return True

    if operator == "&":
        asm.instr("and rax, rcx")
        return True
    if operator == "|":
        asm.instr("or rax, rcx")
        return True
    if operator == "^":
        asm.instr("xor rax, rcx")
        return True

    if operator in {"<<", ">>"}:
        max_shift = 8 if operand_type_name == "u8" else 64
        shift_ok_label = next_label(fn_name, "shift_ok", label_counter)
        panic_message_label = runtime_panic_message_label("invalid shift count")
        asm.instr(f"cmp rcx, {max_shift}")
        asm.instr(f"jb {shift_ok_label}")
        asm.instr(f"lea rdi, [rip + {panic_message_label}]")
        emit_aligned_call("rt_panic")
        asm.label(shift_ok_label)
        if operator == "<<":
            asm.instr("shl rax, cl")
        elif is_unsigned:
            asm.instr("shr rax, cl")
        else:
            asm.instr("sar rax, cl")
        return True

    if operator in ("==", "!=", "<", "<=", ">", ">="):
        asm.instr("cmp rax, rcx")
        if operator == "==":
            asm.instr("sete al")
        elif operator == "!=":
            asm.instr("setne al")
        elif operator == "<":
            asm.instr("setb al" if is_unsigned else "setl al")
        elif operator == "<=":
            asm.instr("setbe al" if is_unsigned else "setle al")
        elif operator == ">":
            asm.instr("seta al" if is_unsigned else "setg al")
        else:
            asm.instr("setae al" if is_unsigned else "setge al")
        asm.instr("movzx rax, al")
        return True

    return False
