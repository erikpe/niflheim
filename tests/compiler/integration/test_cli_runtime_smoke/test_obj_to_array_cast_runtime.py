from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_smoke_supports_obj_to_array_cast(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var value: Obj = u64[](2u);
            var numbers: u64[] = (u64[])value;

            numbers[0] = 7u;
            numbers[1] = 9u;

            if numbers[0] != 7u {
                return 1;
            }
            if numbers[1] != 9u {
                return 2;
            }
            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0