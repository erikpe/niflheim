from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, write


def test_cli_runtime_smoke_runs_reduced_scope_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn step(limit: i64) -> i64 {
            var total: i64 = 0;
            while total < limit {
                total = inc(total);
            }
            return total;
        }

        fn main() -> i64 {
            return step(4);
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 4


def test_cli_runtime_smoke_runs_identity_comparisons_for_refs_and_null(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {}

        fn is_null(value: Obj) -> bool {
            return value == null;
        }

        fn main() -> i64 {
            var first: Box = Box();
            var alias: Box = first;
            var second: Box = Box();

            if !(first == alias) {
                return 1;
            }
            if first == second {
                return 2;
            }
            if is_null((Obj)first) {
                return 3;
            }
            if null != null {
                return 4;
            }
            if !is_null(null) {
                return 5;
            }

            return 0;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr


def test_cli_runtime_smoke_supports_shift_and_divide_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn sdiv(a: i64, b: i64) -> i64 {
            return a / b;
        }

        fn smod(a: i64, b: i64) -> i64 {
            return a % b;
        }

        fn main() -> i64 {
            var left: u64 = 3u << 4u;
            var right: u64 = 240u >> 4u;

            if (i64)left != 48 {
                return 1;
            }
            if (i64)right != 15 {
                return 2;
            }
            if sdiv(-7, 3) != -3 {
                return 3;
            }
            if smod(-7, 3) != 2 {
                return 4;
            }
            return 0;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr