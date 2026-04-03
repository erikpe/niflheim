from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_lexical_shadowing_preserves_outer_bindings(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            var value: i64 = 10;

            if true {
                var value: i64 = 20;
                if value != 20 {
                    return 1;
                }
            }

            for value in i64[](1u) {
                if value != 0 {
                    return 2;
                }
            }

            if value != 10 {
                return 3;
            }
            return 0;
        }
        """,
    )
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0