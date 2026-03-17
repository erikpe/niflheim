from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_semantic_codegen_runs_nontrivial_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var values: i64[] = i64[](4u);
            values[0] = 10;
            values[1] = 20;

            var sum: i64 = 0;
            for value in values {
                sum = sum + value;
            }

            var box: Box = Box(sum);
            if box.value == 30 {
                return 0;
            }
            return 1;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        exe_path=tmp_path / "program",
    )

    assert run.returncode == 0