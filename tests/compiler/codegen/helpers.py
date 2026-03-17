from __future__ import annotations

from compiler.codegen.generator import emit_semantic_asm
from compiler.resolver import resolve_program
from compiler.semantic_linker import build_semantic_codegen_program
from compiler.semantic_lowering import lower_program
from compiler.semantic_reachability import prune_unreachable_semantic


def emit_semantic_source_asm(tmp_path, source: str, *, source_path: str = "main.nif", project_root=None) -> str:
    entry_path = tmp_path / source_path
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(source.strip() + "\n", encoding="utf-8")
    root = tmp_path if project_root is None else project_root
    program = resolve_program(entry_path, project_root=root)
    semantic_program = build_semantic_codegen_program(prune_unreachable_semantic(lower_program(program)))
    return emit_semantic_asm(semantic_program)
