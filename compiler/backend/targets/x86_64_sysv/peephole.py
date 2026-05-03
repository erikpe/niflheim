from __future__ import annotations

import re
from dataclasses import dataclass


_REGISTER_NAMES = frozenset(
    {
        "rax",
        "rbx",
        "rcx",
        "rdx",
        "rsi",
        "rdi",
        "rbp",
        "rsp",
        "r8",
        "r9",
        "r10",
        "r11",
        "r12",
        "r13",
        "r14",
        "r15",
        "eax",
        "ebx",
        "ecx",
        "edx",
        "esi",
        "edi",
        "ebp",
        "esp",
        "r8d",
        "r9d",
        "r10d",
        "r11d",
        "r12d",
        "r13d",
        "r14d",
        "r15d",
        "ax",
        "bx",
        "cx",
        "dx",
        "si",
        "di",
        "bp",
        "sp",
        "r8w",
        "r9w",
        "r10w",
        "r11w",
        "r12w",
        "r13w",
        "r14w",
        "r15w",
        "al",
        "bl",
        "cl",
        "dl",
        "sil",
        "dil",
        "bpl",
        "spl",
        "r8b",
        "r9b",
        "r10b",
        "r11b",
        "r12b",
        "r13b",
        "r14b",
        "r15b",
    }
)
_MOV_REG_REG_RE = re.compile(r"^    mov (?P<dest>[A-Za-z][A-Za-z0-9]*), (?P<source>[A-Za-z][A-Za-z0-9]*)$")


@dataclass(frozen=True, slots=True)
class _RegisterMove:
    dest: str
    source: str


def cleanup_x86_64_sysv_assembly(assembly_text: str) -> str:
    """Remove tiny local redundancies from rendered x86-64 SysV assembly."""

    lines = assembly_text.splitlines()
    cleaned_lines: list[str] = []

    for line in lines:
        register_move = _parse_register_move(line)
        if register_move is None:
            cleaned_lines.append(line)
            continue

        if register_move.dest == register_move.source:
            continue

        previous_move = _parse_register_move(cleaned_lines[-1]) if cleaned_lines else None
        if previous_move is not None:
            if previous_move == register_move:
                continue
            if previous_move.dest == register_move.dest:
                cleaned_lines.pop()

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines) + ("\n" if assembly_text.endswith("\n") else "")


def _parse_register_move(line: str) -> _RegisterMove | None:
    match = _MOV_REG_REG_RE.match(line)
    if match is None:
        return None

    dest = match.group("dest")
    source = match.group("source")
    if dest not in _REGISTER_NAMES or source not in _REGISTER_NAMES:
        return None
    return _RegisterMove(dest=dest, source=source)


__all__ = ["cleanup_x86_64_sysv_assembly"]
