from __future__ import annotations

from compiler.backend.analysis import (
    build_predecessor_map,
    build_successor_map,
    index_callable_cfg,
    iter_callable_instructions,
    reachable_block_ids,
    reverse_postorder_block_ids,
)
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.ir.helpers import one_function_backend_program
from tests.compiler.backend.lowering.helpers import callable_by_name, lower_source_to_backend_program


def _block_ordinals_by_name(callable_decl) -> dict[str, int]:
    return {block.debug_name: block.block_id.ordinal for block in callable_decl.blocks}


def _block_id_by_name(callable_decl, debug_name: str):
    return next(block.block_id for block in callable_decl.blocks if block.debug_name == debug_name)


def _successor_names(callable_decl, successor_by_block) -> dict[str, tuple[str, ...]]:
    block_name_by_id = {block.block_id: block.debug_name for block in callable_decl.blocks}
    return {
        block_name_by_id[block_id]: tuple(block_name_by_id[successor_block_id] for successor_block_id in successors)
        for block_id, successors in successor_by_block.items()
    }


def _predecessor_names(callable_decl, predecessor_by_block) -> dict[str, tuple[str, ...]]:
    block_name_by_id = {block.block_id: block.debug_name for block in callable_decl.blocks}
    return {
        block_name_by_id[block_id]: tuple(block_name_by_id[predecessor_block_id] for predecessor_block_id in predecessors)
        for block_id, predecessors in predecessor_by_block.items()
    }


def test_cfg_index_builds_deterministic_successor_and_predecessor_maps_for_if_else(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn select(flag: bool) -> i64 {
            var total: i64 = 0;
            if flag {
                total = 1;
            } else {
                total = 2;
            }
            return total;
        }

        fn main() -> i64 {
            return select(true);
        }
        """,
        callable_name="select",
        skip_optimize=True,
    )

    cfg = fixture.cfg
    successor_names = _successor_names(fixture.callable_decl, cfg.successor_by_block)
    predecessor_names = _predecessor_names(fixture.callable_decl, cfg.predecessor_by_block)

    assert successor_names == {
        "entry": ("if.then", "if.else"),
        "if.then": ("if.then_to_end",),
        "if.else": ("if.else_to_end",),
        "if.end": (),
        "if.then_to_end": ("if.end",),
        "if.else_to_end": ("if.end",),
    }
    assert predecessor_names == {
        "entry": (),
        "if.then": ("entry",),
        "if.else": ("entry",),
        "if.end": ("if.then_to_end", "if.else_to_end"),
        "if.then_to_end": ("if.then",),
        "if.else_to_end": ("if.else",),
    }


def test_cfg_index_tracks_loop_reachability_and_reverse_postorder_deterministically(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn loop(limit: i64) -> i64 {
            var total: i64 = 0;
            while total < limit {
                total = total + 1;
                if total == 2 {
                    continue;
                }
                if total == 3 {
                    break;
                }
            }
            return total;
        }

        fn main() -> i64 {
            return loop(4);
        }
        """,
        callable_name="loop",
        skip_optimize=True,
    )

    cfg = fixture.cfg
    block_ordinals = _block_ordinals_by_name(fixture.callable_decl)
    all_block_ordinals = {block.block_id.ordinal for block in fixture.callable_decl.blocks}
    reachable_names = {
        block.debug_name
        for block in fixture.callable_decl.blocks
        if block.block_id in cfg.reachable_block_ids
    }
    reverse_postorder_names = tuple(
        next(block.debug_name for block in fixture.callable_decl.blocks if block.block_id == block_id)
        for block_id in cfg.reverse_postorder_block_ids
    )

    assert reachable_names == set(block_ordinals)
    assert cfg.predecessor_by_block[_block_id_by_name(fixture.callable_decl, "while.cond")] == (
        _block_id_by_name(fixture.callable_decl, "entry"),
        _block_id_by_name(fixture.callable_decl, "continue.edge"),
        _block_id_by_name(fixture.callable_decl, "while.continue"),
    )
    assert cfg.predecessor_by_block[_block_id_by_name(fixture.callable_decl, "while.exit")] == (
        _block_id_by_name(fixture.callable_decl, "while.cond"),
        _block_id_by_name(fixture.callable_decl, "break.edge"),
    )
    assert reverse_postorder_names[0] == "entry"
    assert len(cfg.reverse_postorder_block_ids) == len(set(cfg.reverse_postorder_block_ids))
    assert {block_id.ordinal for block_id in cfg.reverse_postorder_block_ids} == all_block_ordinals
    assert set(reverse_postorder_names) == set(block_ordinals)


def test_cfg_helpers_are_stable_across_repeated_lowering_runs(tmp_path) -> None:
    source = """
    fn flow(flag: bool, limit: i64) -> i64 {
        var total: i64 = 0;
        while total < limit {
            if flag {
                total = total + 1;
            } else {
                total = total + 2;
            }
        }
        return total;
    }

    fn main() -> i64 {
        return flow(true, 4);
    }
    """

    fixture_a = lower_source_to_backend_callable_fixture(
        tmp_path / "run_a",
        source,
        callable_name="flow",
        skip_optimize=True,
    )
    fixture_b = lower_source_to_backend_callable_fixture(
        tmp_path / "run_b",
        source,
        callable_name="flow",
        skip_optimize=True,
    )

    assert fixture_a.cfg.successor_by_block == fixture_b.cfg.successor_by_block
    assert fixture_a.cfg.predecessor_by_block == fixture_b.cfg.predecessor_by_block
    assert fixture_a.cfg.reverse_postorder_block_ids == fixture_b.cfg.reverse_postorder_block_ids
    assert [
        (type(instruction).__name__, instruction.inst_id.ordinal)
        for instruction in iter_callable_instructions(fixture_a.callable_decl)
    ] == [
        (type(instruction).__name__, instruction.inst_id.ordinal)
        for instruction in iter_callable_instructions(fixture_b.callable_decl)
    ]


def test_cfg_helpers_handle_extern_callables_and_minimal_concrete_callables(tmp_path) -> None:
    minimal_program = one_function_backend_program()
    minimal_callable = callable_by_name(minimal_program, "main")
    minimal_cfg = index_callable_cfg(minimal_callable)

    assert minimal_cfg.reachable_block_ids == frozenset({minimal_callable.entry_block_id})
    assert minimal_cfg.reverse_postorder_block_ids == (minimal_callable.entry_block_id,)
    assert iter_callable_instructions(minimal_callable) == minimal_callable.blocks[0].instructions

    extern_program = lower_source_to_backend_program(
        tmp_path / "extern_case",
        """
        extern fn rt_gc_collect() -> unit;

        fn main() -> i64 {
            rt_gc_collect();
            return 0;
        }
        """,
    )
    extern_callable = callable_by_name(extern_program, "rt_gc_collect")

    assert build_successor_map(extern_callable) == {}
    assert build_predecessor_map(extern_callable) == {}
    assert reachable_block_ids(extern_callable) == frozenset()
    assert reverse_postorder_block_ids(extern_callable) == ()