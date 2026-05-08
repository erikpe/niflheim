from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _require_native_runtime_backend(require_native_runtime_backend: str) -> None:
    del require_native_runtime_backend