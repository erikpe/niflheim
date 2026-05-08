from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.compiler.integration import helpers


def test_assemble_host_executable_invokes_cc_with_runtime_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asm_path = tmp_path / "program.s"
    seen: dict[str, object] = {}

    def _fake_subprocess_run(command, *, check, capture_output, text):
        seen["command"] = command
        seen["check"] = check
        seen["capture_output"] = capture_output
        seen["text"] = text
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helpers, "require_native_runtime_backend_name", lambda: "x86_64_sysv")
    monkeypatch.setattr(helpers, "require_cc", lambda: "/usr/bin/cc")
    monkeypatch.setattr(helpers.subprocess, "run", _fake_subprocess_run)

    output_path = helpers.assemble_host_executable(asm_path)

    command = seen["command"]
    assert output_path == asm_path.with_suffix("")
    assert command[0] == "/usr/bin/cc"
    assert command[-2:] == ["-o", str(output_path)]
    assert str(asm_path) in command
    assert any(arg.endswith("runtime/src/runtime.c") for arg in command)
    assert seen["check"] is True
    assert seen["capture_output"] is True
    assert seen["text"] is True


def test_compile_native_and_run_chains_emit_assemble_and_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tmp_path / "main.nif"
    asm_path = tmp_path / "out.s"
    exe_path = tmp_path / "program"
    expected_result = SimpleNamespace(returncode=0, stdout="", stderr="")
    seen: list[tuple[str, object]] = []

    monkeypatch.setattr(helpers, "compile_to_asm", lambda *args, **kwargs: asm_path)
    monkeypatch.setattr(
        helpers,
        "assemble_host_executable",
        lambda asm_path, *, exe_path=None: seen.append(("assemble", exe_path)) or exe_path,
    )
    monkeypatch.setattr(helpers, "run_executable", lambda exe_path: seen.append(("run", exe_path)) or expected_result)
    monkeypatch.setattr(helpers, "require_native_runtime_backend_name", lambda: "x86_64_sysv")

    result = helpers.compile_native_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=asm_path,
        exe_path=exe_path,
    )

    assert result is expected_result
    assert seen == [("assemble", exe_path), ("run", exe_path)]