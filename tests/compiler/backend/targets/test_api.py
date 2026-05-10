from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import compiler.backend.targets as backend_targets
from compiler.backend.analysis.pipeline import run_backend_ir_pipeline
from compiler.backend.targets import (
    BackendEmitResult,
    BackendTargetRegistration,
    BackendTarget,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
    backend_target_registration,
    default_checked_backend_target_name,
    native_runtime_backend_name,
    registered_backend_target_names,
    registered_backend_targets,
    resolve_backend_target,
)
from compiler.backend.targets.aarch64 import AARCH64_TARGET
from compiler.backend.targets.x86_64_sysv import X86_64_SYSV_TARGET
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
        "BackendTargetRegistration",
        "backend_target_registration",
        "default_checked_backend_target_name",
        "native_runtime_backend_name",
        "registered_backend_target_names",
        "registered_backend_targets",
        "resolve_backend_target",
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
    assert target_input.program_context.symbols.callable(pipeline_result.program.entry_callable_id).emitted_label == "main"
    assert target_input.program_context.metadata.classes == ()


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


def test_registered_backend_targets_expose_the_checked_registry_surface() -> None:
    registrations = registered_backend_targets()

    assert registrations == (
        BackendTargetRegistration(
            name="x86_64_sysv",
            target=X86_64_SYSV_TARGET,
            emits_on_all_hosts=True,
            native_runtime_architectures=frozenset({"x86_64"}),
        ),
        BackendTargetRegistration(
            name="aarch64",
            target=AARCH64_TARGET,
            emits_on_all_hosts=True,
            native_runtime_architectures=frozenset(),
        ),
    )
    assert registered_backend_target_names() == ("x86_64_sysv", "aarch64")
    assert backend_target_registration("x86_64_sysv") == registrations[0]
    assert backend_target_registration("aarch64") == registrations[1]


def test_resolve_backend_target_defaults_to_the_checked_backend() -> None:
    assert default_checked_backend_target_name() == "x86_64_sysv"
    assert resolve_backend_target() is X86_64_SYSV_TARGET
    assert resolve_backend_target("x86_64_sysv") is X86_64_SYSV_TARGET
    assert resolve_backend_target("aarch64") is AARCH64_TARGET


def test_native_runtime_backend_name_uses_registry_capabilities() -> None:
    assert native_runtime_backend_name("x86_64") == "x86_64_sysv"
    assert native_runtime_backend_name("amd64") == "x86_64_sysv"
    assert native_runtime_backend_name("aarch64") is None
