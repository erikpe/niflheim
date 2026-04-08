from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_interfaces_runtime_type_test_returns_false_for_non_implementer(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Metric {
            fn score() -> u64;
        }

        class Plain {
            value: u64;
        }

        fn main() -> i64 {
            var value: Obj = Plain(41u);

            if value is Metric {
                return 1;
            }
            if null is Metric {
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