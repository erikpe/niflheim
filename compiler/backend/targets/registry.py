"""Shared registry for checked backend targets."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from compiler.backend.targets.api import BackendTarget
from compiler.common.architectures import normalize_host_architecture

__all__ = [
    "BackendTargetRegistration",
    "backend_target_registration",
    "default_checked_backend_target_name",
    "native_runtime_backend_name",
    "registered_backend_target_names",
    "registered_backend_targets",
    "resolve_backend_target",
]


_DEFAULT_CHECKED_BACKEND_TARGET_NAME = "x86_64_sysv"


@dataclass(frozen=True, slots=True)
class BackendTargetRegistration:
    name: str
    target: BackendTarget
    emits_on_all_hosts: bool
    native_runtime_architectures: frozenset[str] = frozenset()

    def is_native_runnable_on(self, host_architecture: str) -> bool:
        return normalize_host_architecture(host_architecture) in self.native_runtime_architectures


@lru_cache(maxsize=1)
def _registered_backend_targets() -> tuple[BackendTargetRegistration, ...]:
    from compiler.backend.targets.x86_64_sysv import X86_64_SYSV_TARGET

    return (
        BackendTargetRegistration(
            name=X86_64_SYSV_TARGET.name,
            target=X86_64_SYSV_TARGET,
            emits_on_all_hosts=True,
            native_runtime_architectures=frozenset({"x86_64"}),
        ),
    )


@lru_cache(maxsize=1)
def _backend_target_registration_by_name() -> dict[str, BackendTargetRegistration]:
    return {registration.name: registration for registration in _registered_backend_targets()}


def registered_backend_targets() -> tuple[BackendTargetRegistration, ...]:
    return _registered_backend_targets()


def registered_backend_target_names() -> tuple[str, ...]:
    return tuple(registration.name for registration in _registered_backend_targets())


def backend_target_registration(name: str) -> BackendTargetRegistration:
    return _backend_target_registration_by_name()[name]


def default_checked_backend_target_name() -> str:
    return _DEFAULT_CHECKED_BACKEND_TARGET_NAME


def resolve_backend_target(name: str | None = None) -> BackendTarget:
    resolved_name = default_checked_backend_target_name() if name is None else name
    return backend_target_registration(resolved_name).target


def native_runtime_backend_name(host_arch: str | None = None) -> str | None:
    resolved_host_architecture = normalize_host_architecture(host_arch)
    for registration in _registered_backend_targets():
        if registration.is_native_runnable_on(resolved_host_architecture):
            return registration.name
    return None