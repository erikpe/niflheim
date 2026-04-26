from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import compiler.backend.targets as backend_targets
from compiler.backend.analysis.pipeline import run_backend_ir_pipeline
from compiler.backend.targets import (
    BackendEmitResult,
    BackendTarget,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
)
from tests.compiler.backend.ir.helpers import one_function_backend_program


class _DummyTarget:
    name = "dummy"

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
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
    assert backend_targets.__all__ == [
        "BackendEmitResult",
        "BackendTarget",
        "BackendTargetInput",
        "BackendTargetLoweringError",
        "BackendTargetOptions",
    ]


def test_backend_emit_result_preserves_text_and_diagnostics() -> None:
    result = BackendEmitResult(assembly_text="mov rax, 0\n", diagnostics=("note",))

    assert result.assembly_text == "mov rax, 0\n"
    assert result.diagnostics == ("note",)


def test_backend_target_input_preserves_pipeline_result_shape() -> None:
    pipeline_result = run_backend_ir_pipeline(one_function_backend_program())

    target_input = BackendTargetInput.from_pipeline_result(pipeline_result)

    assert target_input.program == pipeline_result.program
    assert target_input.analysis_by_callable_id == pipeline_result.analysis_by_callable_id


def test_backend_target_input_rejects_missing_callable_analysis() -> None:
    pipeline_result = run_backend_ir_pipeline(one_function_backend_program())

    with pytest.raises(ValueError, match="missing phase-3 analysis"):
        BackendTargetInput(program=pipeline_result.program, analysis_by_callable_id={})


def test_backend_target_protocol_is_runtime_checkable() -> None:
    target = _DummyTarget()
    target_input = BackendTargetInput.from_pipeline_result(run_backend_ir_pipeline(one_function_backend_program()))

    assert isinstance(target, BackendTarget)

    result = target.emit_assembly(target_input, options=BackendTargetOptions())

    assert result == BackendEmitResult(assembly_text="; dummy assembly\n", diagnostics=("dummy diagnostic",))


def test_backend_target_lowering_error_is_runtime_error() -> None:
    assert issubclass(BackendTargetLoweringError, RuntimeError)
