from __future__ import annotations

from compiler.codegen.asm import AsmBuilder
from compiler.semantic.operations import BinaryOpKind


def emit_unary_negate_double(asm: AsmBuilder) -> None:
    asm.instr("movq xmm0, rax")
    asm.instr("xorpd xmm1, xmm1")
    asm.instr("subsd xmm1, xmm0")
    asm.instr("movq rax, xmm1")


def emit_double_binary_op(asm: AsmBuilder, op_kind: BinaryOpKind) -> bool:
    if op_kind == BinaryOpKind.ADD:
        asm.instr("addsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if op_kind == BinaryOpKind.SUBTRACT:
        asm.instr("subsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if op_kind == BinaryOpKind.MULTIPLY:
        asm.instr("mulsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True
    if op_kind == BinaryOpKind.DIVIDE:
        asm.instr("divsd xmm0, xmm1")
        asm.instr("movq rax, xmm0")
        return True

    if op_kind in (
        BinaryOpKind.EQUAL,
        BinaryOpKind.NOT_EQUAL,
        BinaryOpKind.LESS_THAN,
        BinaryOpKind.LESS_EQUAL,
        BinaryOpKind.GREATER_THAN,
        BinaryOpKind.GREATER_EQUAL,
    ):
        asm.instr("ucomisd xmm0, xmm1")
        if op_kind == BinaryOpKind.EQUAL:
            asm.instr("sete al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif op_kind == BinaryOpKind.NOT_EQUAL:
            asm.instr("setne al")
            asm.instr("setp dl")
            asm.instr("or al, dl")
        elif op_kind == BinaryOpKind.LESS_THAN:
            asm.instr("setb al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif op_kind == BinaryOpKind.LESS_EQUAL:
            asm.instr("setbe al")
            asm.instr("setnp dl")
            asm.instr("and al, dl")
        elif op_kind == BinaryOpKind.GREATER_THAN:
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
