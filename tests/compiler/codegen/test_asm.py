from compiler.codegen.asm import AsmBuilder, offset_operand, stack_slot_operand


def test_asm_builder_formats_operands_and_lines() -> None:
    builder = AsmBuilder()

    builder.directive(".text")
    builder.label("main")
    builder.instr(f"mov {offset_operand(-8)}, 0")
    builder.instr(f"mov rax, {stack_slot_operand('rsp', 16)}")
    builder.comment("generated")
    builder.blank()

    assert builder.lines == [
        ".intel_syntax noprefix",
        ".text",
        "main:",
        "    mov qword ptr [rbp - 8], 0",
        "    mov rax, qword ptr [rsp + 16]",
        "    # generated",
        "",
    ]


def test_asm_operand_helpers_format_zero_positive_and_negative_offsets() -> None:
    assert offset_operand(8) == "qword ptr [rbp + 8]"
    assert stack_slot_operand("rsp", 0) == "qword ptr [rsp]"
    assert stack_slot_operand("rsp", -16) == "qword ptr [rsp - 16]"
