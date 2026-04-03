from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


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