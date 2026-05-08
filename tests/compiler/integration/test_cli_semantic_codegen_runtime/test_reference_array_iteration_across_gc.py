from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, write


def test_cli_semantic_codegen_runs_reference_array_iteration_across_gc(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect() -> unit;

        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](2u);
            values[0] = Box(4);
            values[1] = Box(6);

            var sum: i64 = 0;
            for value in values {
                rt_gc_collect();
                sum = sum + value.value;
            }

            if sum == 10 {
                return 0;
            }
            return 1;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0


def test_cli_semantic_codegen_runs_obj_array_iteration_with_type_tests_across_gc(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect() -> unit;

        class LeftMarker {}
        class RightMarker {}

        fn main() -> i64 {
            var left: LeftMarker = LeftMarker();
            var right: RightMarker = RightMarker();
            var values: Obj[] = Obj[](2u);
            values[0] = left;
            values[1] = right;

            var sum: i64 = 0;
            for value in values {
                rt_gc_collect();
                if value is LeftMarker {
                    sum = sum + 4;
                } else if value is RightMarker {
                    sum = sum + 6;
                } else {
                    return 1;
                }
            }

            if sum == 10 {
                return 0;
            }
            return 2;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr