from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import compiler.backend.targets as backend_targets
from compiler.backend.targets import BackendEmitResult, BackendTarget, BackendTargetOptions


class _DummyTarget:
    name = "dummy"

    def emit_assembly(self, verified_program: object, *, options: BackendTargetOptions) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; dummy assembly\n", diagnostics=("dummy diagnostic",))


def test_backend_target_options_defaults_are_stable() -> None:
    options = BackendTargetOptions()

    assert options.runtime_trace_enabled is True
    assert options.emit_debug_comments is False
    assert options.extra_flags == ()


def test_backend_target_options_are_frozen() -> None:
    options = BackendTargetOptions()

    with pytest.raises(FrozenInstanceError):
        options.runtime_trace_enabled = False


def test_backend_target_api_surface_is_explicit() -> None:
    assert backend_targets.__all__ == ["BackendEmitResult", "BackendTarget", "BackendTargetOptions"]


def test_backend_emit_result_preserves_text_and_diagnostics() -> None:
    result = BackendEmitResult(assembly_text="mov rax, 0\n", diagnostics=("note",))

    assert result.assembly_text == "mov rax, 0\n"
    assert result.diagnostics == ("note",)


def test_backend_target_protocol_is_runtime_checkable() -> None:
    target = _DummyTarget()

    assert isinstance(target, BackendTarget)

    result = target.emit_assembly(object(), options=BackendTargetOptions())

    assert result == BackendEmitResult(assembly_text="; dummy assembly\n", diagnostics=("dummy diagnostic",))
