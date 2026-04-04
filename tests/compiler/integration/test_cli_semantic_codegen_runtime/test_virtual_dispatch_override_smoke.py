from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_semantic_codegen_runtime_virtual_dispatch_override_smoke(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Base {
            fn value() -> i64 {
                return 1;
            }

            fn score() -> i64 {
                return __self.value() + 1;
            }
        }

        class Derived extends Base {
            override fn value() -> i64 {
                return 41;
            }
        }

        fn measure(value: Base) -> i64 {
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