from __future__ import annotations

from pathlib import Path

from compiler.backend.analysis import analyze_callable_liveness, analyze_callable_safepoints
from compiler.backend.ir import (
    BackendCallInst,
    BackendDirectCallTarget,
    BackendFunctionAnalysisDump,
    BackendInterfaceCallTarget,
    BackendRegOperand,
    BackendRuntimeCallTarget,
    BackendVirtualCallTarget,
)
from compiler.backend.ir.text import dump_backend_program_text
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture


def _call_instructions(callable_decl) -> tuple[BackendCallInst, ...]:
    return tuple(
        instruction
        for block in callable_decl.blocks
        for instruction in block.instructions
        if isinstance(instruction, BackendCallInst)
    )


def _reg_ids(callable_decl, *debug_names: str):
    reg_by_name = {register.debug_name: register.reg_id for register in callable_decl.registers}
    return tuple(reg_by_name[debug_name] for debug_name in debug_names)


def _call_target_name(instruction: BackendCallInst) -> str:
    target = instruction.target
    if isinstance(target, BackendRuntimeCallTarget):
        return target.name
    if isinstance(target, BackendDirectCallTarget):
        return target.callable_id.name
    if isinstance(target, BackendVirtualCallTarget):
        return target.method_name
    if isinstance(target, BackendInterfaceCallTarget):
        return target.method_id.name
    raise TypeError(f"Unsupported backend call target '{type(target).__name__}'")


def test_analyze_callable_safepoints_tracks_straight_line_live_reference_regs(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(a: Obj, b: Obj, count: i64) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            rt_gc_collect();
            return keep;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    collect_call = _call_instructions(fixture.callable_decl)[0]

    assert safepoints.live_regs_for_instruction(collect_call.inst_id) == _reg_ids(fixture.callable_decl, "keep")
    assert safepoints.all_safepoint_live_reg_sets() == (_reg_ids(fixture.callable_decl, "keep"),)
    assert safepoints.gc_reference_regs_needing_slots() == frozenset(_reg_ids(fixture.callable_decl, "keep"))


def test_analyze_callable_safepoints_excludes_call_destinations_but_keeps_materialized_reference_continuations(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn inner(value: Obj) -> Obj {
            return value;
        }

        fn outer(left: Obj, right: Obj) -> Obj {
            return left;
        }

        fn f(a: Obj, b: Obj) -> Obj {
            return outer(inner(a), b);
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    call_by_name = {_call_target_name(instruction): instruction for instruction in _call_instructions(fixture.callable_decl)}

    assert safepoints.live_regs_for_instruction(call_by_name["inner"].inst_id) == _reg_ids(fixture.callable_decl, "b")
    assert safepoints.live_regs_for_instruction(call_by_name["outer"].inst_id) == ()


def test_analyze_callable_safepoints_merges_branch_successors(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(flag: bool, a: Obj, b: Obj) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            if flag {
                rt_gc_collect();
            }
            return keep;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    collect_call = _call_instructions(fixture.callable_decl)[0]

    assert safepoints.live_regs_for_instruction(collect_call.inst_id) == _reg_ids(fixture.callable_decl, "keep")


def test_analyze_callable_safepoints_keeps_loop_carried_references_live_inside_loops(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(flag: bool, keep: Obj) -> Obj {
            while flag {
                rt_gc_collect();
            }
            return keep;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    collect_call = _call_instructions(fixture.callable_decl)[0]

    assert safepoints.live_regs_for_instruction(collect_call.inst_id) == _reg_ids(fixture.callable_decl, "keep")


def test_analyze_callable_safepoints_tracks_gc_capable_collection_write_calls(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        interface Buffer {
            fn slice_set(begin: i64, end: i64, value: Buffer) -> unit;
        }

        fn f(buffer: Buffer, keep: Buffer) -> Buffer {
            buffer[0:1] = keep;
            return keep;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    slice_set_call = _call_instructions(fixture.callable_decl)[0]

    assert safepoints.live_regs_for_instruction(slice_set_call.inst_id) == _reg_ids(fixture.callable_decl, "keep")


def test_analyze_callable_safepoints_keeps_for_in_collection_regs_live_for_dispatch_calls(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        interface Iterable {
            fn iter_len() -> u64;
            fn iter_get(index: i64) -> Obj;
        }

        fn f(values: Iterable) -> unit {
            for value in values {
                var seen: Obj = value;
            }
            return;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(fixture.callable_decl)
    call_by_name = {_call_target_name(instruction): instruction for instruction in _call_instructions(fixture.callable_decl)}
    iter_len_call = call_by_name["iter_len"]
    iter_get_call = call_by_name["iter_get"]

    assert isinstance(iter_len_call.args[0], BackendRegOperand)
    assert isinstance(iter_get_call.args[0], BackendRegOperand)
    collection_reg = iter_len_call.args[0].reg_id

    assert iter_get_call.args[0].reg_id == collection_reg
    assert safepoints.live_regs_for_instruction(iter_len_call.inst_id) == (collection_reg,)
    assert safepoints.live_regs_for_instruction(iter_get_call.inst_id) == (collection_reg,)


def test_analyze_callable_safepoints_can_render_analysis_dump_sections(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(value: Obj) -> Obj {
            rt_gc_collect();
            return value;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    safepoints = analyze_callable_safepoints(
        fixture.callable_decl,
        liveness=analyze_callable_liveness(fixture.callable_decl),
    )
    rendered = dump_backend_program_text(
        fixture.program,
        analysis_by_callable={fixture.callable_decl.callable_id: safepoints.to_analysis_dump()},
    )

    assert isinstance(safepoints.to_analysis_dump(), BackendFunctionAnalysisDump)
    assert "safepoint_live_regs:" in rendered