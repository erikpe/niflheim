from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compiler.backend.analysis import BackendCallableCfg, index_callable_cfg
from compiler.backend.ir import BACKEND_IR_SCHEMA_VERSION, BackendCallableDecl, BackendProgram
from tests.compiler.backend.ir.helpers import callable_by_id as callable_by_id_for_fixture
from tests.compiler.backend.lowering.helpers import (
    callable_by_name,
    callable_by_suffix,
    lower_entry_path_to_backend_program,
    lower_project_to_backend_program,
    lower_source_to_backend_program,
)


@dataclass(frozen=True)
class LoweredBackendCallableFixture:
    program: BackendProgram
    callable_decl: BackendCallableDecl
    cfg: BackendCallableCfg


def lower_source_to_backend_callable_fixture(
    tmp_path: Path,
    source: str,
    *,
    callable_name: str,
    source_path: str = "main.nif",
    project_root: Path | None = None,
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
) -> LoweredBackendCallableFixture:
    program = lower_source_to_backend_program(
        tmp_path,
        source,
        source_path=source_path,
        project_root=project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )
    callable_decl = callable_by_name(program, callable_name)
    return LoweredBackendCallableFixture(program=program, callable_decl=callable_decl, cfg=index_callable_cfg(callable_decl))


def lower_project_to_backend_callable_fixture(
    root: Path,
    files: dict[str, str],
    *,
    callable_suffix: str,
    entry_relative_path: str = "main.nif",
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
) -> LoweredBackendCallableFixture:
    program = lower_project_to_backend_program(
        root,
        files,
        entry_relative_path=entry_relative_path,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )
    callable_decl = callable_by_suffix(program, callable_suffix)
    return LoweredBackendCallableFixture(program=program, callable_decl=callable_decl, cfg=index_callable_cfg(callable_decl))


def lower_entry_path_to_backend_callable_fixture(
    entry_path: Path,
    *,
    project_root: Path,
    callable_name: str,
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
) -> LoweredBackendCallableFixture:
    program = lower_entry_path_to_backend_program(
        entry_path,
        project_root=project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )
    callable_decl = callable_by_name(program, callable_name)
    return LoweredBackendCallableFixture(program=program, callable_decl=callable_decl, cfg=index_callable_cfg(callable_decl))


def cfg_by_name(program: BackendProgram, name: str) -> BackendCallableCfg:
    return index_callable_cfg(callable_by_name(program, name))


def callable_fixture_by_id(program: BackendProgram, callable_id: Any) -> BackendCallableDecl:
    return callable_by_id_for_fixture(program, callable_id)


def make_backend_program(
    *callables: BackendCallableDecl,
    entry_callable_id: Any,
) -> BackendProgram:
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=entry_callable_id,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=tuple(callables),
    )