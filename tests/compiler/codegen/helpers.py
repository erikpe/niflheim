from __future__ import annotations

from collections.abc import Iterable

from compiler.codegen.generator import emit_asm
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, optimize_semantic_program


def emit_source_asm(
    tmp_path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root=None,
    disabled_passes: Iterable[str] = (),
    collection_fast_paths_enabled: bool = True,
    runtime_trace_enabled: bool = True,
) -> str:
    entry_path = tmp_path / source_path
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(source.strip() + "\n", encoding="utf-8")
    root = tmp_path if project_root is None else project_root
    program = resolve_program(entry_path, project_root=root)
    disabled_pass_names = set(disabled_passes)
    optimization_passes = tuple(
        optimization_pass
        for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES
        if optimization_pass.name not in disabled_pass_names
    )
    linked_program = link_semantic_program(
        optimize_semantic_program(lower_program(program), passes=optimization_passes)
    )
    return emit_asm(
        lower_linked_semantic_program(linked_program),
        collection_fast_paths_enabled=collection_fast_paths_enabled,
        runtime_trace_enabled=runtime_trace_enabled,
    )
