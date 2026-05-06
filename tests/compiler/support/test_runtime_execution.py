from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.compiler.support import runtime_execution


def test_write_assembly_file_uses_requested_name(tmp_path: Path) -> None:
    asm_path = runtime_execution.write_assembly_file(tmp_path, "mov rax, 0\n", asm_name="custom_out.s")

    assert asm_path == tmp_path / "custom_out.s"
    assert asm_path.read_text(encoding="utf-8") == "mov rax, 0\n"


def test_run_assembly_text_natively_writes_then_assembles_then_runs(tmp_path: Path, monkeypatch) -> None:
    exe_path = tmp_path / "program"
    expected_result = SimpleNamespace(returncode=0, stdout="", stderr="")
    seen: list[tuple[object, ...]] = []

    monkeypatch.setattr(runtime_execution, "require_native_runtime_backend_name", lambda: "x86_64_sysv")
    monkeypatch.setattr(
        runtime_execution,
        "assemble_host_executable",
        lambda asm_path, *, exe_path=None: seen.append(("assemble", asm_path.name, exe_path)) or exe_path,
    )
    monkeypatch.setattr(
        runtime_execution,
        "run_executable",
        lambda exe_path: seen.append(("run", exe_path.name)) or expected_result,
    )

    result = runtime_execution.run_assembly_text_natively(
        tmp_path,
        "mov rax, 0\n",
        asm_name="native_out.s",
        exe_name="program",
    )

    assert result is expected_result
    assert (tmp_path / "native_out.s").read_text(encoding="utf-8") == "mov rax, 0\n"
    assert seen == [("assemble", "native_out.s", exe_path), ("run", "program")]