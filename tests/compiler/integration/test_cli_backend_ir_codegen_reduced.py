from __future__ import annotations

from pathlib import Path
import subprocess

import compiler.cli as cli

from tests.compiler.integration.helpers import build_executable, compile_and_run, compile_to_asm, install_std_modules, write


_EXPERIMENTAL_BACKEND_ARGS = ["--experimental-backend", "backend-ir-x86_64_sysv"]


def test_cli_experimental_backend_selector_emits_assembly_without_default_codegen(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_emit_asm(*args, **kwargs):
        raise AssertionError("default checked codegen should not run when the reduced backend selector is enabled")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=out_file,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert ".intel_syntax noprefix" in asm
    assert "main:" in asm
    assert "    mov rax, 0" in asm
    assert "    jmp .Lmain_epilogue" in asm


def test_cli_default_codegen_path_does_not_use_experimental_backend_without_selector(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_backend_target(*args, **kwargs):
        raise AssertionError("experimental backend target should not run on the default checked codegen path")

    monkeypatch.setattr(cli, "emit_x86_64_sysv_asm", _unexpected_backend_target)

    asm_path = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=out_file)

    assert asm_path.exists()


def test_cli_experimental_backend_selector_can_compile_and_run_rooted_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect() -> unit;

        class FirstMarker {}
        class MiddleMarker {}

        fn choose_last(left: Obj, right: Obj) -> Obj {
            rt_gc_collect();
            return right;
        }

        fn main() -> i64 {
            var i: i64 = 0;
            while i < 50 {
                var first: Obj = (Obj)FirstMarker();
                var middle: Obj = (Obj)MiddleMarker();
                var last: Obj = first;

                rt_gc_collect();
                last = first;
                rt_gc_collect();

                var kept: Obj = choose_last(middle, last);
                if !(kept is FirstMarker) {
                    return 10;
                }

                rt_gc_collect();
                if !(last is FirstMarker) {
                    return 11;
                }

                i = i + 1;
            }

            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 0, run.stderr


def test_cli_experimental_backend_selector_can_compile_and_run_reduced_scope_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn step(limit: i64) -> i64 {
            var total: i64 = 0;
            while total < limit {
                total = inc(total);
            }
            return total;
        }

        fn main() -> i64 {
            return step(4);
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 4


def test_cli_experimental_backend_selector_can_omit_runtime_trace_calls(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;
        }

        fn make() -> Box {
            return Box(0);
        }

        fn main() -> i64 {
            var box: Box = make();
            return box.value;
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        extra_args=[*list(_EXPERIMENTAL_BACKEND_ARGS), "--omit-runtime-trace"],
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert "rt_trace_push" not in asm
    assert "rt_trace_pop" not in asm
    assert "rt_trace_set_location" not in asm


def test_cli_experimental_backend_selector_runs_reference_array_iteration_across_gc(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        extern fn rt_gc_collect() -> unit;

        class LeftMarker {}
        class RightMarker {}

        fn main() -> i64 {
            var left: LeftMarker = LeftMarker();
            var right: RightMarker = RightMarker();
            var values: Obj[] = Obj[](2u);
            values[0] = left;
            values[1] = right;

            var sum: i64 = 0;
            for value in values {
                rt_gc_collect();
                if value is LeftMarker {
                    sum = sum + 4;
                } else if value is RightMarker {
                    sum = sum + 6;
                } else {
                    return 1;
                }
            }

            if sum == 10 {
                return 0;
            }
            return 2;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 0, run.stderr


def test_cli_experimental_backend_selector_runs_identity_comparisons_for_refs_and_null(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {}

        fn is_null(value: Obj) -> bool {
            return value == null;
        }

        fn main() -> i64 {
            var first: Box = Box();
            var alias: Box = first;
            var second: Box = Box();

            if !(first == alias) {
                return 1;
            }
            if first == second {
                return 2;
            }
            if is_null((Obj)first) {
                return 3;
            }
            if null != null {
                return 4;
            }
            if !is_null(null) {
                return 5;
            }

            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 0, run.stderr


def test_cli_experimental_backend_selector_runs_std_string_literal_len(tmp_path: Path, monkeypatch) -> None:
    install_std_modules(tmp_path, ["str", "lang", "object", "vec", "error"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.str;

        fn main() -> i64 {
            return (i64)"abc".len();
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 3, run.stderr


def test_cli_experimental_backend_selector_short_circuits_boolean_and_with_guarded_array_index(
    tmp_path: Path, monkeypatch
) -> None:
    install_std_modules(tmp_path, ["io", "str", "lang", "object", "vec", "error"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.io;
        import std.str;

        fn main() -> i64 {
            var args: Str[] = read_program_args();
            if args.len() > 2u && args[2].compare_to("len") == 0 {
                return 1;
            }
            if args[1].compare_to("alpha") != 0 {
                return 2;
            }
            return 0;
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )
    exe_path = build_executable(asm_path, exe_path=tmp_path / "out")
    run = subprocess.run([str(exe_path), "alpha"], check=False, capture_output=True, text=True)

    assert run.returncode == 0, run.stderr


def test_cli_experimental_backend_selector_runs_interface_typed_local_initializers(tmp_path: Path, monkeypatch) -> None:
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

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 254
