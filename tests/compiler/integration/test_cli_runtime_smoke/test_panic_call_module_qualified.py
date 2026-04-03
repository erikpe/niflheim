from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write
from tests.compiler.integration.stdlib_fixtures import install_std_error_fixture, make_std_error_entry_with_call


def test_cli_runtime_panic_call_module_qualified(tmp_path: Path, monkeypatch) -> None:
    install_std_error_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(entry, make_std_error_entry_with_call("Panic at the disco!", "error.panic"))
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: Panic at the disco!" in run.stderr