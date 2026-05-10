from __future__ import annotations

import re

from compiler.backend.targets import BackendTargetOptions
from compiler.backend.program.symbols import mangle_function_symbol
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def _function_with_epilogue_for_label(asm: str, label: str) -> str:
    start = asm.index(f"{label}:")
    end = asm.index("    ret", start) + len("    ret\n")
    return asm[start:end]


def _assert_root_frame_setup(text: str, *, root_count: int) -> None:
    pattern = (
        r"    bl rt_thread_state\n"
        r"    str x0, \[x29, #-\d+\]\n"
        r"    sub x1, x29, #\d+\n"
        r"    ldr x2, \[x0\]\n"
        r"    str x2, \[x1\]\n"
        + fr"    mov w2, #{root_count}\n"
        + r"    str w2, \[x1, #8\]\n"
        r"    mov w2, wzr\n"
        r"    str w2, \[x1, #12\]\n"
        r"    sub x2, x29, #\d+\n"
        r"    str x2, \[x1, #16\]\n"
        r"    str x1, \[x0\]\n"
    )
    assert re.search(pattern, text), text


def _assert_root_frame_pop(text: str) -> None:
    pattern = (
        r"    ldr x0, \[x29, #-\d+\]\n"
        r"    sub x1, x29, #\d+\n"
        r"    ldr x1, \[x1\]\n"
        r"    str x1, \[x0\]\n"
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
    assert keep_body.index("    bl rt_thread_state") < keep_body.index("    bl rt_trace_push")


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
        r"    ldr x10, \[x29, #-\d+\]\n"
        r"    str x10, \[x29, #-\d+\]\n",
        keep_body,
    )

    assert sync_match is not None, keep_body
    assert keep_body.find("    bl rt_gc_collect", sync_match.end()) != -1


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
        r"    ldr x10, \[x29, #-\d+\]\n"
        r"    str x10, \[x29, #-\d+\]\n"
        r"(?:    ldr x0, \[x29, #-\d+\]\n)?"
        + fr"    bl {re.escape(callee_label)}\n",
        caller_body,
    )

    assert sync_match is not None, caller_body


def test_emit_program_can_omit_runtime_trace_calls_while_keeping_root_frames(tmp_path) -> None:
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
        options=BackendTargetOptions(runtime_trace_enabled=False),
    )

    keep_body = _body_for_label(asm, mangle_function_symbol(("main",), "keep"))

    assert "    bl rt_thread_state" in keep_body
    assert "rt_trace_push" not in asm
    assert "rt_trace_pop" not in asm
    assert "rt_trace_set_location" not in asm