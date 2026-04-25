from __future__ import annotations

from compiler.backend.ir import BackendBranchTerminator, BackendCopyInst, BackendJumpTerminator
from compiler.backend.ir.text import dump_backend_program_text
from compiler.backend.ir.verify import verify_backend_program
from tests.compiler.backend.lowering.helpers import block_by_ordinal, callable_by_name, lower_source_to_backend_program


def _block_names(callable_decl) -> list[str]:
    return [block.debug_name for block in sorted(callable_decl.blocks, key=lambda block: block.block_id.ordinal)]


def test_lower_to_backend_ir_lowers_if_else_to_explicit_branch_join_and_merge_copy_blocks(tmp_path) -> None:
    program = lower_source_to_backend_program(
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
        skip_optimize=True,
    )

    verify_backend_program(program)
    select_callable = callable_by_name(program, "select")

    assert _block_names(select_callable) == [
        "entry",
        "if.then",
        "if.else",
        "if.end",
        "if.then_to_end",
        "if.else_to_end",
    ]

    entry_block = block_by_ordinal(select_callable, 0)
    then_edge_block = block_by_ordinal(select_callable, 4)
    else_edge_block = block_by_ordinal(select_callable, 5)

    assert isinstance(entry_block.terminator, BackendBranchTerminator)
    assert entry_block.terminator.true_block_id.ordinal == 1
    assert entry_block.terminator.false_block_id.ordinal == 2

    assert [type(instruction) for instruction in then_edge_block.instructions] == [BackendCopyInst]
    assert [type(instruction) for instruction in else_edge_block.instructions] == [BackendCopyInst]
    assert isinstance(then_edge_block.terminator, BackendJumpTerminator)
    assert isinstance(else_edge_block.terminator, BackendJumpTerminator)
    assert then_edge_block.terminator.target_block_id.ordinal == 3
    assert else_edge_block.terminator.target_block_id.ordinal == 3


def test_lower_to_backend_ir_lowers_if_without_else_to_explicit_branch_then_and_join_blocks(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn choose(flag: bool) -> i64 {
            var total: i64 = 0;
            if flag {
                total = 7;
            }
            return total;
        }

        fn main() -> i64 {
            return choose(false);
        }
        """,
        skip_optimize=True,
    )

    choose_callable = callable_by_name(program, "choose")

    assert _block_names(choose_callable) == [
        "entry",
        "if.then",
        "if.end",
        "if.then_to_end",
    ]

    entry_block = block_by_ordinal(choose_callable, 0)
    then_edge_block = block_by_ordinal(choose_callable, 3)

    assert isinstance(entry_block.terminator, BackendBranchTerminator)
    assert entry_block.terminator.true_block_id.ordinal == 1
    assert entry_block.terminator.false_block_id.ordinal == 2
    assert [type(instruction) for instruction in then_edge_block.instructions] == [BackendCopyInst]
    assert isinstance(then_edge_block.terminator, BackendJumpTerminator)
    assert then_edge_block.terminator.target_block_id.ordinal == 2


def test_lower_to_backend_ir_lowers_while_break_and_continue_to_explicit_cfg_targets(tmp_path) -> None:
    program = lower_source_to_backend_program(
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
        skip_optimize=True,
    )

    verify_backend_program(program)
    loop_callable = callable_by_name(program, "loop")
    block_names = _block_names(loop_callable)

    assert block_names[0:4] == ["entry", "while.cond", "while.body", "while.exit"]
    assert "continue.edge" in block_names
    assert "break.edge" in block_names
    assert "while.continue" in block_names

    cond_block = block_by_ordinal(loop_callable, 1)
    exit_block = block_by_ordinal(loop_callable, 3)

    continue_edge = next(block for block in loop_callable.blocks if block.debug_name == "continue.edge")
    break_edge = next(block for block in loop_callable.blocks if block.debug_name == "break.edge")
    backedge_block = next(block for block in loop_callable.blocks if block.debug_name == "while.continue")

    assert isinstance(cond_block.terminator, BackendBranchTerminator)
    assert cond_block.terminator.true_block_id.ordinal == 2
    assert cond_block.terminator.false_block_id == exit_block.block_id

    assert [type(instruction) for instruction in continue_edge.instructions] == [BackendCopyInst]
    assert [type(instruction) for instruction in break_edge.instructions] == [BackendCopyInst]
    assert [type(instruction) for instruction in backedge_block.instructions] == [BackendCopyInst]

    assert isinstance(continue_edge.terminator, BackendJumpTerminator)
    assert continue_edge.terminator.target_block_id == cond_block.block_id
    assert isinstance(break_edge.terminator, BackendJumpTerminator)
    assert break_edge.terminator.target_block_id == exit_block.block_id
    assert isinstance(backedge_block.terminator, BackendJumpTerminator)
    assert backedge_block.terminator.target_block_id == cond_block.block_id


def test_lower_to_backend_ir_keeps_nested_control_flow_block_order_deterministic(tmp_path) -> None:
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

    program_a = lower_source_to_backend_program(tmp_path / "run_a", source, skip_optimize=True)
    program_b = lower_source_to_backend_program(tmp_path / "run_b", source, skip_optimize=True)

    flow_callable = callable_by_name(program_a, "flow")
    dump_a = dump_backend_program_text(program_a)
    dump_b = dump_backend_program_text(program_b)

    assert dump_a == dump_b
    assert [block.block_id.ordinal for block in flow_callable.blocks] == list(range(len(flow_callable.blocks)))
    assert _block_names(flow_callable) == [
        "entry",
        "while.cond",
        "while.body",
        "while.exit",
        "if.then",
        "if.else",
        "if.end",
        "if.then_to_end",
        "if.else_to_end",
    ]