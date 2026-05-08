from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, write


def test_cli_interfaces_runtime_runs_interface_typed_local_initializers(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Comparable {
            fn compare_to(other: Obj) -> i64;
        }

        class Box implements Comparable {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }

            fn compare_to(other: Obj) -> i64 {
                return __self.value - ((Box)other).value;
            }
        }

        fn main() -> i64 {
            var left: Box = Box(7);
            var right: Box = Box(9);
            var comparable: Comparable = left;
            return comparable.compare_to((Obj)right);
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 254


def test_cli_interfaces_runtime_runs_null_reference_and_interface_locals(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        fn main() -> i64 {
            var obj: Obj = null;
            var hashable: Hashable = (Hashable)null;

            if obj != hashable {
                return 1;
            }
            if hashable != null {
                return 2;
            }
            return 0;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr


def test_cli_interfaces_runtime_runs_constructor_results_stored_in_interface_and_obj_locals(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        interface Metric {
            fn score() -> i64;
        }

        class Counter implements Metric {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }

            fn score() -> i64 {
                return __self.value;
            }
        }

        fn main() -> i64 {
            var metric: Metric = Counter(7);
            var obj: Obj = Counter(9);
            return metric.score() + ((Counter)obj).score();
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 16, run.stderr