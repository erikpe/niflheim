from __future__ import annotations

from compiler.common.architectures import host_architecture, normalize_host_architecture


def test_normalize_host_architecture_collapses_common_aliases() -> None:
    assert normalize_host_architecture("AMD64") == "x86_64"
    assert normalize_host_architecture("arm64") == "aarch64"
    assert normalize_host_architecture("x86_64") == "x86_64"
    assert normalize_host_architecture("aarch64") == "aarch64"


def test_host_architecture_uses_platform_machine(monkeypatch) -> None:
    monkeypatch.setattr("compiler.common.architectures.platform.machine", lambda: "AMD64")

    assert host_architecture() == "x86_64"