from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_semantic_codegen_runtime_interface_dispatch_uses_override_implementation(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Metric {
            fn score() -> i64;
        }

        class Base implements Metric {
            fn score() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn score() -> i64 {
                return 42;
            }
        }

        fn measure(value: Metric) -> i64 {
            return value.score();
        }

        fn main() -> i64 {
            if measure(Derived()) == 42 {
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