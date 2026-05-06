from __future__ import annotations

import pytest

from tests.compiler.support.runtime_harness import require_native_runtime_backend_name


def test_require_native_runtime_backend_name_returns_x86_backend_on_x86_hosts() -> None:
    assert require_native_runtime_backend_name("x86_64") == "x86_64_sysv"


def test_require_native_runtime_backend_name_skips_with_the_shared_arm_reason() -> None:
    with pytest.raises(
        pytest.skip.Exception,
        match="runtime contract tests require a native backend; only x86_64_sysv is registered today",
    ):
        require_native_runtime_backend_name("aarch64")