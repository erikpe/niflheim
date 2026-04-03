from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write, write_project


def test_cli_interfaces_runtime_dispatch_smoke(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Metric {
            fn score() -> u64;
        }

        class Counter implements Metric {
            value: u64;

            fn score() -> u64 {
                return __self.value + 1u;
            }
        }

        fn measure(value: Metric) -> u64 {
            return value.score();
        }

        fn main() -> i64 {
            if measure(Counter(41u)) == 42u {
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


def test_cli_interfaces_runtime_invalid_obj_to_interface_cast_panics(tmp_path: Path, monkeypatch) -> None:
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
            var metric: Metric = (Metric)value;
            return (i64)metric.score();
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode != 0
    assert "panic: bad cast (main::Plain -> main::Metric)" in run.stderr


def test_cli_interfaces_runtime_supports_multi_interface_fields_arrays_and_returns(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        interface Labeled {
            fn label() -> u64;
        }

        class Key implements Hashable, Labeled {
            value: u64;

            fn hash_code() -> u64 {
                return __self.value + 100u;
            }

            fn label() -> u64 {
                return __self.value;
            }
        }

        class Holder {
            primary: Hashable;
            values: Hashable[];
            labeler: Labeled;
        }

        fn echo(value: Hashable) -> Hashable {
            return value;
        }

        fn main() -> i64 {
            var values: Hashable[] = Hashable[](2u);
            values[0] = Key(5u);
            values[1] = Key(8u);

            var holder: Holder = Holder(Key(2u), values, Key(9u));
            var echoed: Hashable = echo(holder.primary);

            if echoed.hash_code() != 102u {
                return 1;
            }
            if holder.values[1].hash_code() != 108u {
                return 2;
            }
            if holder.labeler.label() != 9u {
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


def test_cli_interfaces_runtime_supports_imported_interfaces_across_modules(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "contracts.nif": """
            export interface Hashable {
                fn hash_code() -> u64;
            }
            """,
            "model.nif": """
            import contracts;

            export class Key implements Hashable {
                value: u64;

                fn hash_code() -> u64 {
                    return __self.value;
                }
            }

            export fn as_hashable(value: u64) -> contracts.Hashable {
                return Key(value);
            }
            """,
            "main.nif": """
            import contracts;
            import model;

            fn bounce(value: Hashable) -> contracts.Hashable {
                return value;
            }

            fn main() -> i64 {
                var values: Hashable[] = Hashable[](2u);
                values[0] = model.as_hashable(10u);
                values[1] = bounce(model.Key(32u));

                if values[0].hash_code() != 10u {
                    return 1;
                }
                if values[1].hash_code() != 32u {
                    return 2;
                }
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0

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