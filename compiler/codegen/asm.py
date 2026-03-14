from __future__ import annotations


def offset_operand(offset: int) -> str:
    sign = "+" if offset >= 0 else "-"
    return f"qword ptr [rbp {sign} {abs(offset)}]"


def stack_slot_operand(base_register: str, byte_offset: int) -> str:
    if byte_offset == 0:
        return f"qword ptr [{base_register}]"
    sign = "+" if byte_offset > 0 else "-"
    return f"qword ptr [{base_register} {sign} {abs(byte_offset)}]"


class AsmBuilder:
    def __init__(self) -> None:
        self.lines: list[str] = [".intel_syntax noprefix"]

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def blank(self) -> None:
        self.lines.append("")

    def directive(self, text: str) -> None:
        self.lines.append(text)

    def label(self, name: str) -> None:
        self.lines.append(f"{name}:")

    def instr(self, text: str) -> None:
        self.lines.append(f"    {text}")

    def comment(self, text: str) -> None:
        self.lines.append(f"    # {text}")

    def build(self) -> str:
        return "\n".join(self.lines)