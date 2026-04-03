from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


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