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
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
    assert run.stdout == "23\n42\n255\ntrue\nfalse\n"


@pytest.mark.parametrize("call_target", ["panic", "error.panic"])
def test_cli_runtime_panic_call_exits_with_error(tmp_path: Path, monkeypatch, call_target: str) -> None:
    install_std_error_fixture(tmp_path)
    entry = tmp_path / "main.nif"
    write(entry, make_std_error_entry_with_call("Panic at the disco!", call_target))
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: Panic at the disco!" in run.stderr


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


def test_cli_runtime_out_of_range_double_to_integer_cast_panics(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var value: u8 = (u8)256.0;
            return (i64)value;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: numeric cast out of range (double -> u8)" in run.stderr


def test_cli_runtime_array_len_on_null_preserves_runtime_panic_behavior(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var values: i64[] = null;
            return (i64)values.len();
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: Array API called with null object" in run.stderr


def test_cli_runtime_for_in_on_null_array_preserves_runtime_panic_behavior(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var values: i64[] = null;
            for value in values {
                return value;
            }
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: Array API called with null object" in run.stderr


def test_cli_runtime_lexical_shadowing_preserves_outer_bindings(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var value: i64 = 10;

            if true {
                var value: i64 = 20;
                if value != 20 {
                    return 1;
                }
            }

            for value in i64[](1u) {
                if value != 0 {
                    return 2;
                }
            }

            if value != 10 {
                return 3;
            }
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
