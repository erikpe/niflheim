from __future__ import annotations


def format_stack_slot_operand(base_register: str, byte_offset: int) -> str:
    if byte_offset == 0:
        return f"[{base_register}]"
    return f"[{base_register}, #{byte_offset}]"


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


__all__ = ["AArch64AsmBuilder", "format_stack_slot_operand"]