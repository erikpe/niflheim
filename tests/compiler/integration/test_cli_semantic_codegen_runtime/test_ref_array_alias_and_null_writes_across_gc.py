from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


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