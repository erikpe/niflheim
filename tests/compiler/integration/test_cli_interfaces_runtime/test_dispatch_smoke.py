from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


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