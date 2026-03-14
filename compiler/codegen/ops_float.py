from __future__ import annotations

from compiler.codegen.asm import AsmBuilder


def emit_unary_negate_double(asm: AsmBuilder) -> None:
    asm.instr("movq xmm0, rax")
    asm.instr("xorpd xmm1, xmm1")
    asm.instr("subsd xmm1, xmm0")
    asm.instr("movq rax, xmm1")


def emit_double_binary_op(asm: AsmBuilder, operator: str) -> bool:
    if operator == "+":
        asm.instr("addsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if operator == "-":
        asm.instr("subsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if operator == "*":
        asm.instr("mulsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if operator == "/":
        asm.instr("divsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True

    if operator in ("==", "!=", "<", "<=", ">", ">="):
        asm.instr("ucomisd xmm0, xmm1")
        if operator == "==":
            asm.instr("sete al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif operator == "!=":
            asm.instr("setne al")
            asm.instr("setp dl")
            asm.instr("or al, dl")
        elif operator == "<":
            asm.instr("setb al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif operator == "<=":
            asm.instr("setbe al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif operator == ">":
            asm.instr("seta al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        else:
            asm.instr("setae al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        asm.instr("movzx rax, al")
        return True

    return False