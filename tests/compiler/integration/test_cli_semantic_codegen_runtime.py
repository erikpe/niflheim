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
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0


def test_cli_semantic_codegen_runs_primitive_array_iteration_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](3u);
            values[0] = 1;
            values[1] = 2;
            values[2] = 3;

            var sum: i64 = 0;
            for value in values {
                sum = sum + value;
            }

            if sum == 6 {
                return 0;
            }
            return 1;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0


def test_cli_semantic_codegen_runs_reference_array_iteration_across_gc(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](2u);
            values[0] = Box(4);
            values[1] = Box(6);

            var sum: i64 = 0;
            for value in values {
                rt_gc_collect(null);
                sum = sum + value.value;
            }

            if sum == 10 {
                return 0;
            }
            return 1;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0


def test_cli_semantic_codegen_runs_ref_array_write_with_temporary_value_across_target_gc(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        class Box {
            value: i64;
        }

        fn choose(values: Box[]) -> Box[] {
            rt_gc_collect(null);
            return values;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](2u);
            choose(values)[0] = Box(7);

            var keep: Box = Box(9);
            choose(values)[1] = keep;

            rt_gc_collect(null);

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


def test_cli_semantic_codegen_runs_ref_array_alias_and_null_writes_across_gc(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](2u);
            values[0] = Box(11);
            values[1] = values[0];
            rt_gc_collect(null);

            if values[1] == null {
                return 1;
            }
            if values[1].value != 11 {
                return 2;
            }

            values[0] = null;
            rt_gc_collect(null);
            if values[1] == null {
                return 3;
            }
            if values[1].value != 11 {
                return 4;
            }

            values[1] = null;
            rt_gc_collect(null);
            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
