"""Shared backend target interfaces for phase-1 backend IR work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


__all__ = ["BackendEmitResult", "BackendTarget", "BackendTargetOptions"]


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


@runtime_checkable
class BackendTarget(Protocol):
    """Protocol implemented by concrete target backends."""

    name: str

    def emit_assembly(self, verified_program: object, *, options: BackendTargetOptions) -> BackendEmitResult:
        ...
