from __future__ import annotations

import subprocess
from pathlib import Path

from tests.compiler.integration.helpers import assemble_host_executable, run_executable
from tests.compiler.support.runtime_harness import require_native_runtime_backend_name


def write_assembly_file(tmp_path: Path, assembly_text: str, *, asm_name: str = "backend_target_out.s") -> Path:
    asm_path = tmp_path / asm_name
    asm_path.write_text(assembly_text, encoding="utf-8")
    return asm_path


def run_assembly_text_natively(
    tmp_path: Path,
    assembly_text: str,
    *,
    asm_name: str = "backend_target_out.s",
    exe_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    require_native_runtime_backend_name()
    asm_path = write_assembly_file(tmp_path, assembly_text, asm_name=asm_name)
    exe_path = None if exe_name is None else tmp_path / exe_name
    built_executable_path = assemble_host_executable(asm_path, exe_path=exe_path)
    return run_executable(built_executable_path)