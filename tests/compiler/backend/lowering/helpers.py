from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from compiler.backend.ir import BackendBlock, BackendCallableDecl, BackendInstruction, BackendProgram
from compiler.backend.lowering import lower_to_backend_ir
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, optimize_semantic_program
from compiler.typecheck.api import typecheck_program


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def write_project(root: Path, files: Mapping[str, str]) -> None:
    for relative_path, content in files.items():
        write(root / relative_path, content)


def lower_source_to_backend_program(
    tmp_path: Path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root: Path | None = None,
    disabled_passes: Iterable[str] = (),
    skip_optimize: bool = False,
) -> BackendProgram:
    entry_path = tmp_path / source_path
    write(entry_path, source)
    return lower_entry_path_to_backend_program(
        entry_path,
        project_root=tmp_path if project_root is None else project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )


def lower_project_to_backend_program(
    root: Path,
    files: Mapping[str, str],
    *,
    entry_relative_path: str = "main.nif",
    disabled_passes: Iterable[str] = (),
    skip_optimize: bool = False,
) -> BackendProgram:
    write_project(root, files)
    return lower_entry_path_to_backend_program(
        root / entry_relative_path,
        project_root=root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )


def lower_entry_path_to_backend_program(
    entry_path: Path,
    *,
    project_root: Path,
    disabled_passes: Iterable[str] = (),
    skip_optimize: bool = False,
) -> BackendProgram:
    program = resolve_program(entry_path, project_root=project_root)
    typecheck_program(program)
    lowered_program = lower_program(program)
    disabled_pass_names = set(disabled_passes)
    optimization_passes = () if skip_optimize else tuple(
        optimization_pass
        for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES
        if optimization_pass.name not in disabled_pass_names
    )
    linked_program = link_semantic_program(optimize_semantic_program(lowered_program, passes=optimization_passes))
    return lower_to_backend_ir(linked_program)


def callable_by_name(program: BackendProgram, name: str) -> BackendCallableDecl:
    for callable_decl in program.callables:
        callable_id = callable_decl.callable_id
        callable_name = getattr(callable_id, "name", None)
        if callable_name == name:
            return callable_decl
    raise KeyError(f"Missing backend callable named {name!r}")


def callable_by_suffix(program: BackendProgram, suffix: str) -> BackendCallableDecl:
    for callable_decl in program.callables:
        callable_id = callable_decl.callable_id
        pieces = [*callable_id.module_path]
        class_name = getattr(callable_id, "class_name", None)
        name = getattr(callable_id, "name", None)
        ordinal = getattr(callable_id, "ordinal", None)
        if class_name is not None:
            pieces.append(class_name)
        if name is not None:
            pieces.append(name)
        elif ordinal is not None:
            pieces.append(f"#{ordinal}")
        rendered = ".".join(pieces)
        if rendered.endswith(suffix):
            return callable_decl
    raise KeyError(f"Missing backend callable ending in {suffix!r}")


def block_by_ordinal(callable_decl: BackendCallableDecl, ordinal: int) -> BackendBlock:
    for block in callable_decl.blocks:
        if block.block_id.ordinal == ordinal:
            return block
    raise KeyError(f"Missing backend block b{ordinal}")


def instruction_by_ordinal(callable_decl: BackendCallableDecl, ordinal: int) -> BackendInstruction:
    for block in callable_decl.blocks:
        for instruction in block.instructions:
            if instruction.inst_id.ordinal == ordinal:
                return instruction
    raise KeyError(f"Missing backend instruction i{ordinal}")