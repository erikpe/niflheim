from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_array_slice_invalid_range_preserves_runtime_panic_behavior(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](2u);
            var part: i64[] = values[1:3];
            if part == null {
                return 1;
            }
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: rt_array_slice_i64: invalid slice range" in run.stderr