from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_semantic_codegen_runs_ref_array_write_with_temporary_value_across_target_gc(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect() -> unit;

        class Box {
            value: i64;
        }

        fn choose(values: Box[]) -> Box[] {
            rt_gc_collect();
            return values;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](2u);
            choose(values)[0] = Box(7);

            var keep: Box = Box(9);
            choose(values)[1] = keep;

            rt_gc_collect();

            if values[0] == null {
                return 1;
            }
            if values[0].value != 7 {
                return 2;
            }
            if values[1] == null {
                return 3;
            }
            if values[1].value != 9 {
                return 4;
            }
            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0