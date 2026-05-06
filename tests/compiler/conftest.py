from __future__ import annotations

import pytest

from tests.compiler.support.backend_matrix import host_architecture as detect_host_architecture
from tests.compiler.support.backend_matrix import native_runtime_backend_name as resolve_native_runtime_backend_name
from tests.compiler.support.runtime_harness import require_native_runtime_backend_name


@pytest.fixture(scope="session")
def host_architecture() -> str:
    return detect_host_architecture()


@pytest.fixture(scope="session")
def native_runtime_backend_name(host_architecture: str) -> str | None:
    return resolve_native_runtime_backend_name(host_architecture)


@pytest.fixture
def require_native_runtime_backend(host_architecture: str) -> str:
    return require_native_runtime_backend_name(host_architecture)