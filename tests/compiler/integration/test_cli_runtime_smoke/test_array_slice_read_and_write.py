from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_array_slice_read_and_write_preserve_runtime_behavior(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](4u);
            values[0] = 10;
            values[1] = 20;
            values[2] = 30;
            values[3] = 40;

            var part: i64[] = values[1:3];
            values[0:2] = part;

            if values[0] != 20 {
                return 1;
            }
            if values[1] != 30 {
                return 2;
            }
            if part[0] != 20 {
                return 3;
            }
            if part[1] != 30 {
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