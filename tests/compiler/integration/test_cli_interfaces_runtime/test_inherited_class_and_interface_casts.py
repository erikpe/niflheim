from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_interfaces_runtime_supports_inherited_class_and_interface_casts(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Metric {
            fn score() -> u64;
        }

        class Base implements Metric {
            fn score() -> u64 {
                return 41u;
            }
        }

        class Derived extends Base {
            extra: u64;
        }

        fn main() -> i64 {
            var value: Obj = Derived(1u);

            if value is Base {
            } else {
                return 1;
            }

            if value is Metric {
            } else {
                return 2;
            }

            var as_base: Base = (Base)value;
            var as_metric: Metric = (Metric)value;

            if as_base.score() != 41u {
                return 3;
            }
            if as_metric.score() != 41u {
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