from __future__ import annotations

import re

from compiler.backend.program.symbols import mangle_function_symbol
from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def _function_with_epilogue_for_label(asm: str, label: str) -> str:
    start = asm.index(f"{label}:")
    end = asm.index("    ret", start) + len("    ret\n")
    return asm[start:end]


def _assert_root_frame_setup(text: str, *, root_count: int) -> None:
    pattern = (
        r"    call rt_thread_state\n"
        r"    mov qword ptr \[rbp - \d+\], rax\n"
        r"    lea rdi, \[rbp - \d+\]\n"
        r"    mov rcx, qword ptr \[rax\]\n"
        r"    mov qword ptr \[rdi\], rcx\n"
        + fr"    mov dword ptr \[rdi \+ 8\], {root_count}\n"
        + r"    mov dword ptr \[rdi \+ 12\], 0\n"
        r"    lea rcx, \[rbp - \d+\]\n"
        r"    mov qword ptr \[rdi \+ 16\], rcx\n"
        r"    mov qword ptr \[rax\], rdi\n"
    )
    assert re.search(pattern, text), text


def _assert_root_frame_pop(text: str) -> None:
    pattern = (
        r"    mov rdi, qword ptr \[rbp - \d+\]\n"
        r"    lea rcx, \[rbp - \d+\]\n"
        r"    mov rcx, qword ptr \[rcx\]\n"
        r"    mov qword ptr \[rdi\], rcx\n"
    )
    assert re.search(pattern, text), text


def test_emit_source_asm_emits_root_frame_setup_before_trace_push(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn keep(value: Obj) -> Obj {
            rt_gc_collect();
            return value;
        }

        fn main() -> i64 {
            keep(null);
            return 0;
        }
        """,
        skip_optimize=True,
    )

    keep_label = mangle_function_symbol(("main",), "keep")
    keep_body = _body_for_label(asm, keep_label)
    keep_function = _function_with_epilogue_for_label(asm, keep_label)

    _assert_root_frame_setup(keep_body, root_count=1)
    _assert_root_frame_pop(keep_function)
    assert keep_body.index("    call rt_thread_state") < keep_body.index("    call rt_trace_push")
    assert keep_body.index("    mov qword ptr [rax], rdi") < keep_body.index("    call rt_trace_push")


def test_emit_source_asm_syncs_live_reference_roots_before_gc_runtime_calls(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn keep(value: Obj) -> Obj {
            var saved: Obj = value;
            rt_gc_collect();
            return saved;
        }

        fn main() -> i64 {
            keep(null);
            return 0;
        }
        """,
        skip_optimize=True,
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
    )

    keep_body = _body_for_label(asm, mangle_function_symbol(("main",), "keep"))
    sync_match = re.search(
        r"    mov rax, qword ptr \[rbp - \d+\]\n"
        r"    mov qword ptr \[rbp - \d+\], rax\n",
        keep_body,
    )

    assert sync_match is not None, keep_body
    assert keep_body.find("    call rt_gc_collect", sync_match.end()) != -1


def test_emit_source_asm_syncs_live_reference_roots_before_ordinary_calls(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn ping(value: Obj) -> unit {
            rt_gc_collect();
            return;
        }

        fn caller(keep: Obj, arg: Obj) -> Obj {
            var saved: Obj = keep;
            ping(arg);
            return saved;
        }

        fn main() -> i64 {
            caller(null, null);
            return 0;
        }
        """,
        skip_optimize=True,
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
    )

    caller_label = mangle_function_symbol(("main",), "caller")
    caller_body = _body_for_label(asm, caller_label)
    callee_label = mangle_function_symbol(("main",), "ping")
    sync_match = re.search(
        r"    mov r10, qword ptr \[rbp - \d+\]\n"
        r"    mov qword ptr \[rbp - \d+\], r10\n"
        r"(?:    mov rdi, qword ptr \[rbp - \d+\]\n)?"
        + fr"    call {re.escape(callee_label)}\n",
        caller_body,
    )

    assert sync_match is not None, caller_body


def test_emit_source_asm_runs_root_slot_reuse_across_forced_gc(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
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
            while i < 200 {
                    var first: FirstMarker = FirstMarker();
                    var middle: MiddleMarker = MiddleMarker();
                    var last: Obj = (Obj)first;

                rt_gc_collect();
                    last = (Obj)first;
                rt_gc_collect();

                    var kept: Obj = choose_last((Obj)middle, last);
                if !(kept is FirstMarker) {
                    return 100 + i;
                }

                rt_gc_collect();
                if !(last is FirstMarker) {
                    return 1000 + i;
                }

                i = i + 1;
            }

            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 0, run.stderr


def test_emit_source_asm_runs_reference_array_iteration_across_gc(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
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
        skip_optimize=True,
    )

    assert run.returncode == 0, run.stderr