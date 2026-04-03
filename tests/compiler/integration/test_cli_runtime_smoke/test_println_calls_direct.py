from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write
from tests.compiler.integration.stdlib_fixtures import install_std_io_fixture, make_std_io_entry


def test_cli_runtime_println_calls_direct(tmp_path: Path, monkeypatch) -> None:
    install_std_io_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(
        entry,
        make_std_io_entry(
            """
            var x: i64 = 23;
            println_i64(x);
            println_u64((u64)42);
            println_u8((u8)255);
            println_bool(true);
            println_bool(false);
            """
        ),
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
    assert run.stdout == "23\n42\n255\ntrue\nfalse\n"