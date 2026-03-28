from __future__ import annotations

from pathlib import Path

from compiler.codegen.root_liveness import analyze_named_root_liveness
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.lowered_ir import LoweredSemanticForIn, LoweredSemanticIf, LoweredSemanticWhile
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, optimize_semantic_program
from compiler.semantic.ir import CallExprS, SemanticExprStmt, SemanticReturn


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


def test_root_liveness_tracks_straight_line_call_live_roots(tmp_path: Path) -> None:
    fn = _lower_function(
        tmp_path,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        fn f(a: Obj, b: Obj) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            rt_gc_collect(keep);
            return keep;
        }
        """,
        function_name="f",
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )
    liveness = analyze_named_root_liveness(fn)

    call_stmt = next(stmt for stmt in fn.body.statements if isinstance(stmt, SemanticExprStmt))
    assert isinstance(call_stmt.expr, CallExprS)

    assert liveness.for_expr(call_stmt.expr) == {_local_id_by_name(fn, "keep")}


def test_root_liveness_tracks_nested_call_continuations(tmp_path: Path) -> None:
    fn = _lower_function(
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
        """,
        function_name="f",
    )
    liveness = analyze_named_root_liveness(fn)

    return_stmt = next(stmt for stmt in fn.body.statements if isinstance(stmt, SemanticReturn))
    assert isinstance(return_stmt.value, CallExprS)
    outer_call = return_stmt.value
    inner_call = outer_call.args[0]
    assert isinstance(inner_call, CallExprS)

    assert liveness.for_expr(outer_call) == frozenset()
    assert liveness.for_expr(inner_call) == frozenset()


def test_root_liveness_merges_branch_successors(tmp_path: Path) -> None:
    fn = _lower_function(
        tmp_path,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        fn f(flag: bool, a: Obj, b: Obj) -> Obj {
            var keep: Obj = a;
            var dead: Obj = b;
            if flag {
                rt_gc_collect(keep);
            }
            return keep;
        }
        """,
        function_name="f",
        disabled_passes={"copy_propagation", "dead_stmt_prune", "dead_store_elimination"},
    )
    liveness = analyze_named_root_liveness(fn)

    if_stmt = next(stmt for stmt in fn.body.statements if isinstance(stmt, LoweredSemanticIf))
    call_stmt = next(stmt for stmt in if_stmt.then_block.statements if isinstance(stmt, SemanticExprStmt))
    assert isinstance(call_stmt.expr, CallExprS)

    assert liveness.for_expr(call_stmt.expr) == {_local_id_by_name(fn, "keep")}


def test_root_liveness_converges_for_loops(tmp_path: Path) -> None:
    fn = _lower_function(
        tmp_path,
        """
        extern fn rt_gc_collect(ts: Obj) -> unit;

        fn f(flag: bool, keep: Obj) -> Obj {
            while flag {
                rt_gc_collect(keep);
                break;
            }
            return keep;
        }
        """,
        function_name="f",
    )
    liveness = analyze_named_root_liveness(fn)

    while_stmt = next(stmt for stmt in fn.body.statements if isinstance(stmt, LoweredSemanticWhile))
    call_stmt = next(stmt for stmt in while_stmt.body.statements if isinstance(stmt, SemanticExprStmt))
    assert isinstance(call_stmt.expr, CallExprS)

    assert liveness.for_expr(call_stmt.expr) == {_local_id_by_name(fn, "keep")}


def test_root_liveness_tracks_lowered_for_in_dispatch_calls(tmp_path: Path) -> None:
    fn = _lower_function(
        tmp_path,
        """
        class Vec {
            fn iter_len() -> u64 {
                return 0u;
            }

            fn iter_get(index: i64) -> Obj {
                return null;
            }
        }

        fn f(values: Vec) -> unit {
            for value in values {
                if value == null {
                    continue;
                }
            }
            return;
        }
        """,
        function_name="f",
    )
    liveness = analyze_named_root_liveness(fn)

    for_in_stmt = next(stmt for stmt in fn.body.statements if isinstance(stmt, LoweredSemanticForIn))

    assert liveness.for_for_in_iter_len(for_in_stmt) == {for_in_stmt.collection_local_id}
    assert liveness.for_for_in_iter_get(for_in_stmt) == {for_in_stmt.collection_local_id}