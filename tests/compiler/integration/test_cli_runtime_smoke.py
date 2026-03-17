from __future__ import annotations

from pathlib import Path

import pytest

from tests.compiler.integration.helpers import compile_and_run, write
from tests.compiler.integration.stdlib_fixtures import (
    install_std_error_fixture,
    install_std_io_fixture,
    make_std_error_entry_with_call,
    make_std_io_entry,
)


@pytest.mark.parametrize(
    "call_lines",
    [
        """
        var x: i64 = 23;
        println_i64(x);
        println_u64((u64)42);
        println_u8((u8)255);
        println_bool(true);
        println_bool(false);
        """,
        """
        io.println_i64(23);
        io.println_u64((u64)42);
        io.println_u8((u8)255);
        io.println_bool(true);
        io.println_bool(false);
        """,
    ],
)
def test_cli_runtime_println_calls(tmp_path: Path, monkeypatch, call_lines: str) -> None:
    install_std_io_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(entry, make_std_io_entry(call_lines))
    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        exe_path=tmp_path / "program",
        extra_args=["--source-ast-codegen"],
    )

    assert run.returncode == 0
    assert run.stdout == "23\n42\n255\ntrue\nfalse\n"


@pytest.mark.parametrize("call_target", ["panic", "error.panic"])
def test_cli_runtime_panic_call_exits_with_error(tmp_path: Path, monkeypatch, call_target: str) -> None:
    install_std_error_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(entry, make_std_error_entry_with_call("Panic at the disco!", call_target))
    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        exe_path=tmp_path / "program",
        extra_args=["--source-ast-codegen"],
    )

    assert run.returncode != 0
    assert "panic: Panic at the disco!" in run.stderr
