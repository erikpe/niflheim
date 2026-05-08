from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, write


def test_cli_runtime_smoke_runs_callable_value_local_from_function_ref(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn apply(f: fn(i64) -> i64, value: i64) -> i64 {
            return f(value);
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = inc;
            return apply(func, 41);
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 42, run.stderr


def test_cli_runtime_smoke_runs_static_method_refs_as_callable_values(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Math {
            static fn times_three(v: i64) -> i64 {
                return v * 3;
            }
        }

        fn main() -> i64 {
            var f: fn(i64) -> i64 = Math.times_three;
            return f(14);
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 42, run.stderr