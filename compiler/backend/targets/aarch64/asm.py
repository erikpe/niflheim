from __future__ import annotations


def format_memory_operand(base_register: str, byte_offset: int = 0) -> str:
    if byte_offset == 0:
        return f"[{base_register}]"
    return f"[{base_register}, #{byte_offset}]"


def format_stack_slot_operand(base_register: str, byte_offset: int) -> str:
    return format_memory_operand(base_register, byte_offset)


def word_register_name(register_name: str) -> str:
    if register_name == "xzr":
        return "wzr"
    if register_name == "sp":
        return "wsp"
    if register_name.startswith("x"):
        return f"w{register_name[1:]}"
    raise ValueError(f"Unsupported AArch64 register '{register_name}'")


def emit_load_immediate(builder: "AArch64AsmBuilder", target_register: str, value: int) -> None:
    masked_value = value & ((1 << 64) - 1)
    if masked_value == 0:
        builder.instruction("mov", target_register, "xzr")
        return

    halfwords = tuple((masked_value >> shift) & 0xFFFF for shift in (0, 16, 32, 48))
    first_index = next(index for index, halfword in enumerate(halfwords) if halfword != 0)
    first_shift = first_index * 16
    first_operands = [target_register, f"#{halfwords[first_index]}"]
    if first_shift != 0:
        first_operands.append(f"lsl #{first_shift}")
    builder.instruction("movz", *first_operands)

    for index, halfword in enumerate(halfwords):
        if index == first_index or halfword == 0:
            continue
        shift = index * 16
        operands = [target_register, f"#{halfword}"]
        if shift != 0:
            operands.append(f"lsl #{shift}")
        builder.instruction("movk", *operands)


def emit_add_address(
    builder: "AArch64AsmBuilder",
    target_register: str,
    base_register: str,
    byte_offset: int,
) -> None:
    if byte_offset == 0:
        if target_register != base_register:
            builder.instruction("mov", target_register, base_register)
        return
    mnemonic = "add" if byte_offset > 0 else "sub"
    builder.instruction(mnemonic, target_register, base_register, f"#{abs(byte_offset)}")


def emit_materialize_symbol_address(
    builder: "AArch64AsmBuilder",
    target_register: str,
    symbol_name: str,
) -> None:
    builder.instruction("adrp", target_register, symbol_name)
    builder.instruction("add", target_register, target_register, f":lo12:{symbol_name}")


class AArch64AsmBuilder:
    def __init__(self, *, emit_debug_comments: bool = False) -> None:
        self._emit_debug_comments = emit_debug_comments
        self._lines: list[str] = []

    def raw(self, line: str) -> None:
        self._lines.append(line)

    def blank(self) -> None:
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    def directive(self, text: str) -> None:
        self._lines.append(text)

    def section(self, name: str) -> None:
        self.directive(f".section {name}")

    def global_symbol(self, symbol_name: str) -> None:
        self.directive(f".globl {symbol_name}")

    def label(self, name: str) -> None:
        self._lines.append(f"{name}:")

    def instruction(self, mnemonic: str, *operands: str) -> None:
        if operands:
            self._lines.append(f"    {mnemonic} {', '.join(operands)}")
            return
        self._lines.append(f"    {mnemonic}")

    def comment(self, text: str) -> None:
        if self._emit_debug_comments:
            self._lines.append(f"    // {text}")

    def build(self) -> str:
        rendered_lines = list(self._lines)
        while rendered_lines and rendered_lines[-1] == "":
            rendered_lines.pop()
        return "\n".join(rendered_lines) + "\n"


__all__ = [
    "AArch64AsmBuilder",
    "emit_add_address",
    "emit_load_immediate",
    "emit_materialize_symbol_address",
    "format_memory_operand",
    "format_stack_slot_operand",
    "word_register_name",
]