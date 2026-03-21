from __future__ import annotations

from compiler.codegen.generator import emit_asm
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import optimize_semantic_program


def emit_source_asm(tmp_path, source: str, *, source_path: str = "main.nif", project_root=None) -> str:
    entry_path = tmp_path / source_path
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(source.strip() + "\n", encoding="utf-8")
    root = tmp_path if project_root is None else project_root
    program = resolve_program(entry_path, project_root=root)
    linked_program = link_semantic_program(optimize_semantic_program(lower_program(program)))
    return emit_asm(linked_program)
