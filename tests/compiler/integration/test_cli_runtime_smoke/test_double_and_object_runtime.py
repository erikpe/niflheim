from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, write


def test_cli_runtime_smoke_runs_scalar_double_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn blend(a: double, b: double, c: double) -> double {
            return (a + b) * c;
        }

        fn main() -> i64 {
            var value: double = blend(1.5, 0.5, 2.0);
            if value >= 4.0 {
                return 0;
            }
            return 1;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr


def test_cli_runtime_smoke_runs_object_construction_and_field_access(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Pair {
            left: i64;
            right: i64;

            constructor(left: i64, right: i64) {
                __self.left = left;
                __self.right = right;
            }
        }

        fn main() -> i64 {
            var value: Pair = Pair(7, 9);
            return value.left + value.right;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 16, run.stderr