from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

from compiler.cli import main


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def write_project(root: Path, files: Mapping[str, str]) -> None:
    for relative_path, content in files.items():
        write(root / relative_path, content)


def install_std_modules(
    project_root: Path, module_names: list[str], *, overrides: Mapping[str, str] | None = None
) -> None:
    overrides = {} if overrides is None else dict(overrides)
    std_root = project_root / "std"
    std_root.mkdir(parents=True, exist_ok=True)
    repository_std_root = repo_root() / "std"

    for module_name in module_names:
        relative_path = f"std/{module_name}.nif"
        if relative_path in overrides:
            continue
        source_path = repository_std_root / f"{module_name}.nif"
        write(project_root / relative_path, source_path.read_text(encoding="utf-8"))

    for relative_path, content in overrides.items():
        write(project_root / relative_path, content)


def run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", argv)
    return main()


def compile_to_asm(
    monkeypatch: pytest.MonkeyPatch,
    entry_path: Path,
    *,
    project_root: Path | None = None,
    out_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    asm_path = entry_path.with_suffix(".s") if out_path is None else out_path
    argv = ["nifc", str(entry_path)]
    if project_root is not None:
        argv.extend(["--project-root", str(project_root)])
    if extra_args:
        argv.extend(extra_args)
    argv.extend(["-o", str(asm_path)])

    rc = run_cli(monkeypatch, argv)
    assert rc == 0
    assert asm_path.exists()
    return asm_path


def require_cc() -> str:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("cc not available")
    return cc


def build_executable(asm_path: Path, *, exe_path: Path | None = None) -> Path:
    cc = require_cc()
    repository_root = repo_root()
    runtime_include = repository_root / "runtime" / "include"
    runtime_sources = [
        repository_root / "runtime" / "src" / "runtime.c",
        repository_root / "runtime" / "src" / "gc.c",
        repository_root / "runtime" / "src" / "gc_trace.c",
        repository_root / "runtime" / "src" / "gc_tracked_set.c",
        repository_root / "runtime" / "src" / "io.c",
        repository_root / "runtime" / "src" / "array.c",
        repository_root / "runtime" / "src" / "panic.c",
    ]
    output_path = asm_path.with_suffix("") if exe_path is None else exe_path

    subprocess.run(
        [
            cc,
            "-std=c11",
            "-I",
            str(runtime_include),
            *(str(source_path) for source_path in runtime_sources),
            str(asm_path),
            "-o",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return output_path


def run_executable(exe_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(exe_path)], check=False, capture_output=True, text=True)


def compile_and_run(
    monkeypatch: pytest.MonkeyPatch,
    entry_path: Path,
    *,
    project_root: Path | None = None,
    out_path: Path | None = None,
    exe_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    asm_path = compile_to_asm(
        monkeypatch, entry_path, project_root=project_root, out_path=out_path, extra_args=extra_args
    )
    built_exe_path = build_executable(asm_path, exe_path=exe_path)
    return run_executable(built_exe_path)
