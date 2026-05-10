from __future__ import annotations

from pathlib import Path

from compiler.backend.ir import BackendProgram
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import emit_x86_64_sysv_asm
from tests.compiler.backend.lowering.helpers import lower_source_to_backend_program
from tests.compiler.backend.targets.support import make_target_input


def emit_program(program: BackendProgram, *, options: BackendTargetOptions | None = None) -> str:
    resolved_options = BackendTargetOptions() if options is None else options
    return emit_x86_64_sysv_asm(make_target_input(program), options=resolved_options).assembly_text


def emit_source_asm(
    tmp_path: Path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root: Path | None = None,
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
    options: BackendTargetOptions | None = None,
) -> str:
    program = lower_source_to_backend_program(
        tmp_path,
        source,
        source_path=source_path,
        project_root=project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )
    return emit_program(program, options=options)


__all__ = [
    "emit_program",
    "emit_source_asm",
]