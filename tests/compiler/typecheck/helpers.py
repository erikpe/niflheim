from __future__ import annotations

from pathlib import Path

from compiler.lexer import lex
from compiler.parser import parse
from compiler.resolver import resolve_program
from compiler.typecheck.api import typecheck


def parse_and_typecheck(source: str) -> None:
    tokens = lex(source)
    module = parse(tokens)
    typecheck(module)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def resolve_program_from_main(project_root: Path, entrypoint: str = "main.nif"):
    return resolve_program(project_root / entrypoint, project_root=project_root)
