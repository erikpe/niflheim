from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def test_cli_runtime_smoke_deep_inheritance_class_casts_and_type_tests(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Base {
            head: i64;
        }

        class Mid extends Base {
            middle: i64;
        }

        class Derived extends Mid {
            tail: i64;
        }

        fn main() -> i64 {
            var value: Obj = Derived(10, 20, 30);

            if value is Base {
            } else {
                return 1;
            }

            if value is Mid {
            } else {
                return 2;
            }

            if value is Derived {
            } else {
                return 3;
            }

            var as_base: Base = (Base)value;
            var as_mid: Mid = (Mid)value;
            var as_derived: Derived = (Derived)value;

            if as_base.head != 10 {
                return 4;
            }
            if as_mid.middle != 20 {
                return 5;
            }
            if as_derived.tail != 30 {
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