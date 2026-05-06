from __future__ import annotations

from dataclasses import dataclass
import platform
from typing import Final

__all__ = [
    "BackendCapability",
    "backend_capability",
    "host_architecture",
    "native_runtime_backend_name",
    "native_runtime_skip_reason",
    "normalize_host_architecture",
    "registered_backend_capabilities",
]


@dataclass(frozen=True, slots=True)
class BackendCapability:
    name: str
    emits_on_all_hosts: bool
    native_runtime_architectures: frozenset[str] = frozenset()

    def is_native_runnable_on(self, host_architecture: str) -> bool:
        return normalize_host_architecture(host_architecture) in self.native_runtime_architectures


_ARCHITECTURE_ALIASES: Final[dict[str, str]] = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "x64": "x86_64",
}

_REGISTERED_BACKEND_CAPABILITIES: Final[tuple[BackendCapability, ...]] = (
    BackendCapability(
        name="x86_64_sysv",
        emits_on_all_hosts=True,
        native_runtime_architectures=frozenset({"x86_64"}),
    ),
)

_BACKEND_CAPABILITY_BY_NAME: Final[dict[str, BackendCapability]] = {
    capability.name: capability for capability in _REGISTERED_BACKEND_CAPABILITIES
}


def normalize_host_architecture(machine: str | None = None) -> str:
    raw_machine = platform.machine() if machine is None else machine
    normalized = raw_machine.strip().lower().replace("-", "_")
    return _ARCHITECTURE_ALIASES.get(normalized, normalized)


def host_architecture() -> str:
    return normalize_host_architecture()


def registered_backend_capabilities() -> tuple[BackendCapability, ...]:
    return _REGISTERED_BACKEND_CAPABILITIES


def backend_capability(name: str) -> BackendCapability:
    return _BACKEND_CAPABILITY_BY_NAME[name]


def native_runtime_backend_name(host_arch: str | None = None) -> str | None:
    resolved_host_architecture = normalize_host_architecture(host_arch)
    for capability in _REGISTERED_BACKEND_CAPABILITIES:
        if capability.is_native_runnable_on(resolved_host_architecture):
            return capability.name
    return None


def native_runtime_skip_reason(host_arch: str | None = None) -> str | None:
    resolved_host_architecture = normalize_host_architecture(host_arch)
    if native_runtime_backend_name(resolved_host_architecture) is not None:
        return None

    native_backend_names = tuple(
        capability.name
        for capability in _REGISTERED_BACKEND_CAPABILITIES
        if capability.native_runtime_architectures
    )
    if len(native_backend_names) == 1:
        return f"runtime contract tests require a native backend; only {native_backend_names[0]} is registered today"

    rendered_names = ", ".join(native_backend_names) if native_backend_names else "none"
    return (
        "runtime contract tests require a native backend for host architecture "
        f"'{resolved_host_architecture}'; registered native runtime backends: {rendered_names}"
    )