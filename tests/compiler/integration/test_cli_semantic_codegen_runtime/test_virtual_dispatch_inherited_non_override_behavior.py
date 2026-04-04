from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_semantic_codegen_runtime_inherited_non_overridden_methods_keep_base_behavior(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Base {
            fn stable() -> i64 {
                return 7;
            }

            fn value() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn value() -> i64 {
                return 42;
            }
        }

        fn read(value: Base) -> i64 {
            return value.stable();
        }

        fn main() -> i64 {
            if read(Derived()) == 7 {
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