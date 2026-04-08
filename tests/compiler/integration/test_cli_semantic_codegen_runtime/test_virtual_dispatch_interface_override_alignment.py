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


def test_cli_semantic_codegen_runtime_interface_dispatch_preserves_inherited_override_with_mixed_stack_args(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class RefBox {
            value: i64;
        }

        interface Mixer {
            fn mix(
                r0: RefBox,
                i0: i64,
                r1: RefBox,
                i1: i64,
                r2: RefBox,
                i2: i64,
                r3: RefBox,
                i3: i64,
                r4: RefBox
            ) -> i64;
        }

        class Base implements Mixer {
            fn mix(
                r0: RefBox,
                i0: i64,
                r1: RefBox,
                i1: i64,
                r2: RefBox,
                i2: i64,
                r3: RefBox,
                i3: i64,
                r4: RefBox
            ) -> i64 {
                return 0;
            }
        }

        class Derived extends Base {
            override fn mix(
                r0: RefBox,
                i0: i64,
                r1: RefBox,
                i1: i64,
                r2: RefBox,
                i2: i64,
                r3: RefBox,
                i3: i64,
                r4: RefBox
            ) -> i64 {
                return
                    r0.value +
                    (i0 * 10) +
                    (r1.value * 100) +
                    (i1 * 1000) +
                    (r2.value * 10000) +
                    (i2 * 100000) +
                    (r3.value * 1000000) +
                    (i3 * 10000000) +
                    (r4.value * 100000000);
            }
        }

        class Leaf extends Derived {
        }

        fn measure(
            value: Mixer,
            r0: RefBox,
            i0: i64,
            r1: RefBox,
            i1: i64,
            r2: RefBox,
            i2: i64,
            r3: RefBox,
            i3: i64,
            r4: RefBox
        ) -> i64 {
            return value.mix(r0, i0, r1, i1, r2, i2, r3, i3, r4);
        }

        fn main() -> i64 {
            var r0: RefBox = RefBox(1);
            var r1: RefBox = RefBox(2);
            var r2: RefBox = RefBox(3);
            var r3: RefBox = RefBox(4);
            var r4: RefBox = RefBox(5);

            if measure(Leaf(), r0, 6, r1, 7, r2, 8, r3, 9, r4) == 594837261 {
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