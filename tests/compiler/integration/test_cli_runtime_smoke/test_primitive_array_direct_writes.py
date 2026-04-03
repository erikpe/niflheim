from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_primitive_array_direct_writes_preserve_behavior(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var ints: i64[] = i64[](2u);
            ints[0] = 7;
            ints.index_set(1, 9);

            var bytes: u8[] = u8[](2u);
            bytes[0] = (u8)255;
            bytes.index_set(1, (u8)13);

            var values: double[] = double[](2u);
            values[0] = 1.5;
            values.index_set(1, 2.5);

            if ints[0] != 7 {
                return 1;
            }
            if ints[1] != 9 {
                return 2;
            }
            if bytes[0] != (u8)255 {
                return 3;
            }
            if bytes[1] != (u8)13 {
                return 4;
            }
            if (i64)values[0] != 1 {
                return 5;
            }
            if (i64)values[1] != 2 {
                return 6;
            }
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0