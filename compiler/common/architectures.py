from __future__ import annotations

import platform
from typing import Final

__all__ = ["host_architecture", "normalize_host_architecture"]


_ARCHITECTURE_ALIASES: Final[dict[str, str]] = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "x64": "x86_64",
}


def normalize_host_architecture(machine: str | None = None) -> str:
    raw_machine = platform.machine() if machine is None else machine
    normalized = raw_machine.strip().lower().replace("-", "_")
    return _ARCHITECTURE_ALIASES.get(normalized, normalized)


def host_architecture() -> str:
    return normalize_host_architecture()