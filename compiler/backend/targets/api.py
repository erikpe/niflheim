"""Shared backend target interfaces for backend IR lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from compiler.backend.analysis.pipeline import BackendPipelineCallableAnalysis, BackendPipelineResult
from compiler.backend.ir import BackendCallableId, BackendProgram
from compiler.semantic.symbols import ConstructorId, FunctionId, MethodId

__all__ = [
    "BackendEmitResult",
    "BackendTarget",
    "BackendTargetInput",
    "BackendTargetLoweringError",
    "BackendTargetOptions",
]


class BackendTargetLoweringError(RuntimeError):
    """Raised when a concrete backend target cannot lower valid backend IR."""


@dataclass(frozen=True, slots=True)
class BackendTargetOptions:
    """Checked-path switches forwarded into a concrete backend target."""

    runtime_trace_enabled: bool = True
    emit_debug_comments: bool = False
    extra_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackendEmitResult:
    """Assembly text and non-fatal diagnostics produced by a backend target."""

    assembly_text: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackendTargetInput:
    """Explicit target input assembled from the phase-3 backend pipeline."""

    program: BackendProgram
    analysis_by_callable_id: Mapping[BackendCallableId, BackendPipelineCallableAnalysis]

    def __post_init__(self) -> None:
        missing_callable_names = tuple(
            _format_callable_id(callable_decl.callable_id)
            for callable_decl in self.program.callables
            if callable_decl.callable_id not in self.analysis_by_callable_id
        )
        if missing_callable_names:
            missing_rendered = ", ".join(missing_callable_names)
            raise ValueError(
                "Backend target input is missing phase-3 analysis for callables: "
                f"{missing_rendered}"
            )

    @classmethod
    def from_pipeline_result(cls, pipeline_result: BackendPipelineResult) -> "BackendTargetInput":
        return cls(
            program=pipeline_result.program,
            analysis_by_callable_id=pipeline_result.analysis_by_callable_id,
        )

    def analysis_for_callable(self, callable_id: BackendCallableId) -> BackendPipelineCallableAnalysis:
        return self.analysis_by_callable_id[callable_id]


@runtime_checkable
class BackendTarget(Protocol):
    """Protocol implemented by concrete target backends."""

    name: str

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
        ...


def _format_callable_id(callable_id: BackendCallableId) -> str:
    if isinstance(callable_id, FunctionId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.name}"
    if isinstance(callable_id, MethodId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
    if isinstance(callable_id, ConstructorId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
    raise TypeError(f"Unsupported backend callable ID '{callable_id!r}'")
