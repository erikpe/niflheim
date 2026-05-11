from __future__ import annotations

import pytest

from tests.compiler.support.runtime_harness import require_native_runtime_backend_name


def test_require_native_runtime_backend_name_returns_x86_backend_on_x86_hosts() -> None:
    assert require_native_runtime_backend_name("x86_64") == "x86_64_sysv"


def test_require_native_runtime_backend_name_returns_aarch64_backend_on_arm_hosts() -> None:
    assert require_native_runtime_backend_name("aarch64") == "aarch64"


def test_require_native_runtime_backend_name_skips_with_the_shared_unsupported_host_reason() -> None:
    with pytest.raises(
        pytest.skip.Exception,
        match=(
            "runtime contract tests require a native backend for host architecture "
            "'riscv64'; registered native runtime backends: x86_64_sysv, aarch64"
        ),
    ):
        require_native_runtime_backend_name("riscv64")