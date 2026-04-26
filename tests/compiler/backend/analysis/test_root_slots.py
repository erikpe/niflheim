from __future__ import annotations

from pathlib import Path

from compiler.backend.analysis import analyze_callable_root_slots, analyze_callable_safepoints
from compiler.backend.ir import BackendFunctionAnalysisDump
from compiler.backend.ir.text import dump_backend_program_text
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture


def _reg_id_by_name(callable_decl, debug_name: str):
    return next(register.reg_id for register in callable_decl.registers if register.debug_name == debug_name)


def test_root_slot_plan_skips_regs_without_safepoints(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn f(a: Obj, b: Obj) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            dead = keep;
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

    plan = analyze_callable_root_slots(fixture.callable_decl)

    assert plan.slot_count == 0
    assert plan.reg_ids == frozenset()
    assert plan.for_reg(_reg_id_by_name(fixture.callable_decl, "keep")) is None
    assert plan.for_reg(_reg_id_by_name(fixture.callable_decl, "dead")) is None


def test_root_slot_plan_reuses_slot_for_disjoint_safepoints(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(a: Obj) -> Obj {
            var first: Obj = a;
            rt_gc_collect();
            var second: Obj = first;
            rt_gc_collect();
            return second;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    plan = analyze_callable_root_slots(fixture.callable_decl)
    first_reg_id = _reg_id_by_name(fixture.callable_decl, "first")
    second_reg_id = _reg_id_by_name(fixture.callable_decl, "second")

    assert plan.slot_count == 1
    assert plan.for_reg(first_reg_id) == 0
    assert plan.for_reg(second_reg_id) == 0
    assert plan.slot_reg_ids == ((first_reg_id, second_reg_id),)


def test_root_slot_plan_separates_overlapping_safepoint_regs(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn pair(left: Obj, right: Obj) -> Obj {
            return left;
        }

        fn f(a: Obj, b: Obj) -> Obj {
            var left: Obj = a;
            var right: Obj = b;
            rt_gc_collect();
            return pair(left, right);
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    plan = analyze_callable_root_slots(fixture.callable_decl)
    left_reg_id = _reg_id_by_name(fixture.callable_decl, "left")
    right_reg_id = _reg_id_by_name(fixture.callable_decl, "right")

    assert plan.slot_count == 2
    assert plan.for_reg(left_reg_id) != plan.for_reg(right_reg_id)
    assert set(plan.slot_reg_ids) == {(left_reg_id,), (right_reg_id,)}


def test_root_slot_plan_keeps_loop_carried_reference_in_stable_slot(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn f(flag: bool, keep: Obj) -> Obj {
            while flag {
                rt_gc_collect();
                break;
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

    plan = analyze_callable_root_slots(fixture.callable_decl)
    keep_reg_id = _reg_id_by_name(fixture.callable_decl, "keep")

    assert plan.slot_count == 1
    assert plan.for_reg(keep_reg_id) == 0
    assert plan.slot_reg_ids == ((keep_reg_id,),)


def test_root_slot_plan_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        extern fn rt_gc_collect() -> unit;

        fn pair(left: Obj, right: Obj) -> Obj {
            return left;
        }

        fn f(a: Obj, b: Obj, c: Obj) -> Obj {
            var left: Obj = a;
            var right: Obj = b;
            var third: Obj = c;
            rt_gc_collect();
            return pair(left, third);
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        disabled_passes=("copy_propagation", "dead_stmt_prune", "dead_store_elimination"),
        skip_optimize=True,
    )

    first_plan = analyze_callable_root_slots(fixture.callable_decl)
    second_plan = analyze_callable_root_slots(
        fixture.callable_decl,
        safepoints=analyze_callable_safepoints(fixture.callable_decl),
    )

    assert second_plan.root_slot_by_reg == first_plan.root_slot_by_reg
    assert second_plan.slot_reg_ids == first_plan.slot_reg_ids


def test_root_slot_plan_can_render_analysis_dump_sections(tmp_path: Path) -> None:
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

    plan = analyze_callable_root_slots(fixture.callable_decl)
    rendered = dump_backend_program_text(
        fixture.program,
        analysis_by_callable={fixture.callable_decl.callable_id: plan.to_analysis_dump()},
    )

    assert isinstance(plan.to_analysis_dump(), BackendFunctionAnalysisDump)
    assert "root_slot_by_reg:" in rendered