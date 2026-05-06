from __future__ import annotations

from tests.compiler.support.backend_matrix import backend_capability
from tests.compiler.support.backend_matrix import host_architecture
from tests.compiler.support.backend_matrix import native_runtime_backend_name
from tests.compiler.support.backend_matrix import native_runtime_skip_reason
from tests.compiler.support.backend_matrix import normalize_host_architecture
from tests.compiler.support.backend_matrix import registered_backend_capabilities


def test_normalize_host_architecture_collapses_common_aliases() -> None:
    assert normalize_host_architecture("AMD64") == "x86_64"
    assert normalize_host_architecture("arm64") == "aarch64"
    assert normalize_host_architecture("x86_64") == "x86_64"
    assert normalize_host_architecture("aarch64") == "aarch64"


def test_host_architecture_uses_platform_machine(monkeypatch) -> None:
    monkeypatch.setattr("tests.compiler.support.backend_matrix.platform.machine", lambda: "AMD64")

    assert host_architecture() == "x86_64"


def test_registered_backend_capabilities_expose_x86_64_sysv_as_emit_on_all_hosts() -> None:
    capabilities = registered_backend_capabilities()

    assert tuple(capability.name for capability in capabilities) == ("x86_64_sysv",)
    assert capabilities[0].emits_on_all_hosts is True


def test_x86_64_sysv_capability_is_native_runnable_only_on_x86_64_hosts() -> None:
    capability = backend_capability("x86_64_sysv")

    assert capability.is_native_runnable_on("x86_64") is True
    assert capability.is_native_runnable_on("amd64") is True
    assert capability.is_native_runnable_on("aarch64") is False
    assert capability.is_native_runnable_on("arm64") is False


def test_native_runtime_backend_name_resolves_x86_host_to_x86_64_sysv() -> None:
    assert native_runtime_backend_name("x86_64") == "x86_64_sysv"
    assert native_runtime_backend_name("amd64") == "x86_64_sysv"


def test_native_runtime_backend_name_is_missing_on_arm_hosts() -> None:
    assert native_runtime_backend_name("aarch64") is None
    assert native_runtime_backend_name("arm64") is None


def test_native_runtime_skip_reason_is_none_when_a_native_backend_exists() -> None:
    assert native_runtime_skip_reason("x86_64") is None


def test_native_runtime_skip_reason_is_deterministic_on_arm_hosts() -> None:
    assert native_runtime_skip_reason("aarch64") == (
        "runtime contract tests require a native backend; only x86_64_sysv is registered today"
    )