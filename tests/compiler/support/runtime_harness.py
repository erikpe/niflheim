from __future__ import annotations

import pytest

from tests.compiler.support.backend_matrix import native_runtime_backend_name, native_runtime_skip_reason

__all__ = ["require_native_runtime_backend_name"]


def require_native_runtime_backend_name(host_architecture: str | None = None) -> str:
    backend_name = native_runtime_backend_name(host_architecture)
    if backend_name is not None:
        return backend_name

    skip_reason = native_runtime_skip_reason(host_architecture)
    assert skip_reason is not None
    pytest.skip(skip_reason)