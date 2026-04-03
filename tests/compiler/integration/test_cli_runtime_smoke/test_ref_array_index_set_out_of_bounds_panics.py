from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_ref_array_index_set_out_of_bounds_preserves_runtime_panic_behavior(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var values: Box[] = Box[](1u);
            values[1] = Box(7);
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: rt_array_set_ref: index out of bounds" in run.stderr