from __future__ import annotations

from pathlib import Path

from compiler.codegen.root_liveness import analyze_named_root_liveness
from compiler.codegen.root_slot_plan import build_named_root_slot_plan
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, optimize_semantic_program


def _lower_function(
    tmp_path: Path,
    source: str,
    *,
    function_name: str,
    disabled_passes: set[str] | None = None,
):
    source_path = tmp_path / "main.nif"
    source_path.write_text(source.strip() + "\n", encoding="utf-8")
    program = resolve_program(source_path, project_root=tmp_path)
    disabled_passes = set() if disabled_passes is None else set(disabled_passes)
    disabled_passes.add("unreachable_prune")
    optimization_passes = tuple(
        optimization_pass
        for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES
        if optimization_pass.name not in disabled_passes
    )
    lowered = lower_linked_semantic_program(
        link_semantic_program(optimize_semantic_program(lower_program(program), passes=optimization_passes))
    )
    return next(
        fn for fn in lowered.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == function_name
    )


def _local_id_by_name(fn, display_name: str):
    return next(local_info.local_id for local_info in fn.local_info_by_id.values() if local_info.display_name == display_name)


def test_root_slot_plan_skips_locals_without_safepoints(tmp_path: Path) -> None:
    fn = _lower_function(
        tmp_path,
        """
        fn f(a: Obj, b: Obj) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            dead = keep;
            return keep;
        }
        """,
        function_name="f",
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )

    plan = build_named_root_slot_plan(analyze_named_root_liveness(fn))

    assert plan.slot_count == 0
    assert plan.local_ids == frozenset()
    assert plan.for_local(_local_id_by_name(fn, "keep")) is None
    assert plan.for_local(_local_id_by_name(fn, "dead")) is None


def test_root_slot_plan_reuses_slot_for_disjoint_safepoints(tmp_path: Path) -> None:
    fn = _lower_function(
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
        """,
        function_name="f",
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )

    plan = build_named_root_slot_plan(analyze_named_root_liveness(fn))
    first_local_id = _local_id_by_name(fn, "first")
    second_local_id = _local_id_by_name(fn, "second")

    assert plan.slot_count == 1
    assert plan.for_local(first_local_id) == 0
    assert plan.for_local(second_local_id) == 0
    assert plan.slot_local_ids == ((first_local_id, second_local_id),)


def test_root_slot_plan_separates_overlapping_safepoint_locals(tmp_path: Path) -> None:
    fn = _lower_function(
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
        """,
        function_name="f",
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )

    plan = build_named_root_slot_plan(analyze_named_root_liveness(fn))
    left_local_id = _local_id_by_name(fn, "left")
    right_local_id = _local_id_by_name(fn, "right")

    assert plan.slot_count == 2
    assert plan.for_local(left_local_id) != plan.for_local(right_local_id)
    assert set(plan.slot_local_ids) == {(left_local_id,), (right_local_id,)}


def test_root_slot_plan_keeps_loop_carried_reference_in_stable_slot(tmp_path: Path) -> None:
    fn = _lower_function(
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
        """,
        function_name="f",
    )

    plan = build_named_root_slot_plan(analyze_named_root_liveness(fn))
    keep_local_id = _local_id_by_name(fn, "keep")

    assert plan.slot_count == 1
    assert plan.for_local(keep_local_id) == 0
    assert plan.slot_local_ids == ((keep_local_id,),)