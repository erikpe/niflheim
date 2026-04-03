from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write
from tests.compiler.integration.stdlib_fixtures import install_std_io_fixture, make_std_io_entry


def test_cli_runtime_primitive_casts_follow_defined_matrix(tmp_path: Path, monkeypatch) -> None:
    install_std_io_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(
        entry,
        make_std_io_entry(
            """
            println_bool((bool)0.0);
            println_bool((bool)-0.0);
            println_bool((bool)0.5);
            println_i64((i64)7.9);
            println_u8((u8)258);
            println_i64((i64)(u64)18446744073709551615u);
            """
        ),
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
    assert run.stdout == "false\nfalse\ntrue\n7\n2\n-1\n"