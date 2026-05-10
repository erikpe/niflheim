from __future__ import annotations

import compiler.backend.targets as compiler_backend_targets
import compiler.common.architectures as compiler_architectures

__all__ = [
    "BackendCapability",
    "backend_capability",
    "host_architecture",
    "native_runtime_backend_name",
    "native_runtime_skip_reason",
    "normalize_host_architecture",
    "registered_backend_capabilities",
]


BackendCapability = compiler_backend_targets.BackendTargetRegistration


def normalize_host_architecture(machine: str | None = None) -> str:
    return compiler_architectures.normalize_host_architecture(machine)


def host_architecture() -> str:
    return compiler_architectures.host_architecture()


def registered_backend_capabilities() -> tuple[BackendCapability, ...]:
    return compiler_backend_targets.registered_backend_targets()


def backend_capability(name: str) -> BackendCapability:
    return compiler_backend_targets.backend_target_registration(name)


def native_runtime_backend_name(host_arch: str | None = None) -> str | None:
    return compiler_backend_targets.native_runtime_backend_name(host_arch)


def native_runtime_skip_reason(host_arch: str | None = None) -> str | None:
    resolved_host_architecture = normalize_host_architecture(host_arch)
    if native_runtime_backend_name(resolved_host_architecture) is not None:
        return None

    native_backend_names = tuple(
        capability.name
        for capability in registered_backend_capabilities()
        if capability.native_runtime_architectures
    )
    if len(native_backend_names) == 1:
        return f"runtime contract tests require a native backend; only {native_backend_names[0]} is registered today"

    rendered_names = ", ".join(native_backend_names) if native_backend_names else "none"
    return (
        "runtime contract tests require a native backend for host architecture "
        f"'{resolved_host_architecture}'; registered native runtime backends: {rendered_names}"
    )