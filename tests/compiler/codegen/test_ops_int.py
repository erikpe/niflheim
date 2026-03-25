from compiler.codegen.asm import AsmBuilder
from compiler.codegen.ops_int import emit_integer_binary_op, emit_integer_unary_op
from compiler.codegen.symbols import next_label
from compiler.semantic.operations import BinaryOpKind, UnaryOpKind


def test_ops_int_emitters_cover_signed_divmod_shift_and_unary_paths() -> None:
    builder = AsmBuilder()
    label_counter = [0]
    panic_messages: list[str] = []
    aligned_calls: list[str] = []

    def runtime_panic_message_label(message: str) -> str:
        panic_messages.append(message)
        return "__panic_msg"

    def emit_aligned_call(target: str) -> None:
        aligned_calls.append(target)
        builder.instr(f"call {target}")

    emit_integer_unary_op(
        builder,
        op_kind=UnaryOpKind.BITWISE_NOT,
        operand_type_name="u8",
        emit_bool_normalize=lambda: builder.instr("normalize-bool"),
    )
    emit_integer_unary_op(
        builder,
        op_kind=UnaryOpKind.LOGICAL_NOT,
        operand_type_name="bool",
        emit_bool_normalize=lambda: builder.instr("normalize-bool"),
    )
    div_ok = emit_integer_binary_op(
        builder,
        op_kind=BinaryOpKind.DIVIDE,
        operand_type_name="i64",
        fn_name="f",
        label_counter=label_counter,
        next_label=next_label,
        runtime_panic_message_label=runtime_panic_message_label,
        emit_aligned_call=emit_aligned_call,
    )
    mod_ok = emit_integer_binary_op(
        builder,
        op_kind=BinaryOpKind.REMAINDER,
        operand_type_name="i64",
        fn_name="f",
        label_counter=label_counter,
        next_label=next_label,
        runtime_panic_message_label=runtime_panic_message_label,
        emit_aligned_call=emit_aligned_call,
    )
    shift_ok = emit_integer_binary_op(
        builder,
        op_kind=BinaryOpKind.SHIFT_RIGHT,
        operand_type_name="u8",
        fn_name="f",
        label_counter=label_counter,
        next_label=next_label,
        runtime_panic_message_label=runtime_panic_message_label,
        emit_aligned_call=emit_aligned_call,
    )

    assert div_ok is True
    assert mod_ok is True
    assert shift_ok is True
    assert "    not rax" in builder.lines
    assert builder.lines.count("    and rax, 255") >= 1
    assert "    normalize-bool" in builder.lines
    assert "    xor rax, 1" in builder.lines
    assert "    cqo" in builder.lines
    assert "    idiv rcx" in builder.lines
    assert "    test rdx, rdx" in builder.lines
    assert "    add rax, rcx" in builder.lines
    assert "    cmp rcx, 8" in builder.lines
    assert aligned_calls == ["rt_panic"]
    assert panic_messages == ["invalid shift count"]
