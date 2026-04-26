from __future__ import annotations

from dataclasses import replace

from compiler.backend.analysis import eliminate_unreachable_blocks, simplify_callable_cfg
from compiler.backend.ir import (
    BackendBlock,
    BackendBlockId,
    BackendBoolConst,
    BackendBranchTerminator,
    BackendConstInst,
    BackendConstOperand,
    BackendIntConst,
    BackendJumpTerminator,
    BackendRegOperand,
    BackendReturnTerminator,
)
from compiler.backend.ir.verify import verify_backend_program
from tests.compiler.backend.analysis.helpers import (
    lower_source_to_backend_callable_fixture,
    make_backend_program,
    replace_callable,
)
from tests.compiler.backend.ir.helpers import make_source_span, one_function_backend_program


def _block_by_name(callable_decl, debug_name: str):
    return next(block for block in callable_decl.blocks if block.debug_name == debug_name)


def _block_ids(callable_decl) -> tuple[int, ...]:
    return tuple(block.block_id.ordinal for block in callable_decl.blocks)


def test_eliminate_unreachable_blocks_removes_dead_blocks_without_renumbering_survivors() -> None:
    program = one_function_backend_program()
    main_callable = program.callables[0]
    entry_block = main_callable.blocks[0]
    dead_block = BackendBlock(
        block_id=BackendBlockId(owner_id=main_callable.callable_id, ordinal=7),
        debug_name="dead.unreachable",
        instructions=(),
        terminator=BackendJumpTerminator(span=entry_block.span, target_block_id=entry_block.block_id),
        span=entry_block.span,
    )
    callable_with_dead_block = replace(main_callable, blocks=(*main_callable.blocks, dead_block))

    cleaned_callable = eliminate_unreachable_blocks(callable_with_dead_block)
    cleaned_program = make_backend_program(cleaned_callable, entry_callable_id=program.entry_callable_id)

    verify_backend_program(cleaned_program)

    assert _block_ids(cleaned_callable) == (0,)
    assert cleaned_callable.blocks[0].instructions == entry_block.instructions
    assert cleaned_callable.blocks[0].terminator == entry_block.terminator


def test_simplify_callable_cfg_forwards_empty_jump_blocks_and_collapses_branch_to_jump() -> None:
    program = one_function_backend_program()
    main_callable = program.callables[0]
    span = make_source_span(path="fixtures/simplify_cfg.nif", start_offset=10, end_offset=20)
    ret_block = BackendBlock(
        block_id=BackendBlockId(owner_id=main_callable.callable_id, ordinal=3),
        debug_name="return",
        instructions=(
            BackendConstInst(
                inst_id=main_callable.blocks[0].instructions[0].inst_id,
                dest=main_callable.blocks[0].instructions[0].dest,
                constant=BackendIntConst(type_name="i64", value=7),
                span=span,
            ),
        ),
        terminator=BackendReturnTerminator(
            span=span,
            value=BackendRegOperand(reg_id=main_callable.blocks[0].instructions[0].dest),
        ),
        span=span,
    )
    true_edge = BackendBlock(
        block_id=BackendBlockId(owner_id=main_callable.callable_id, ordinal=1),
        debug_name="true.edge",
        instructions=(),
        terminator=BackendJumpTerminator(span=span, target_block_id=ret_block.block_id),
        span=span,
    )
    false_edge = BackendBlock(
        block_id=BackendBlockId(owner_id=main_callable.callable_id, ordinal=2),
        debug_name="false.edge",
        instructions=(),
        terminator=BackendJumpTerminator(span=span, target_block_id=ret_block.block_id),
        span=span,
    )
    entry_block = replace(
        main_callable.blocks[0],
        instructions=(),
        terminator=BackendBranchTerminator(
            span=span,
            condition=BackendConstOperand(constant=BackendBoolConst(value=True)),
            true_block_id=true_edge.block_id,
            false_block_id=false_edge.block_id,
        ),
    )
    branch_callable = replace(main_callable, blocks=(entry_block, true_edge, false_edge, ret_block))

    simplified_callable = simplify_callable_cfg(branch_callable)
    simplified_program = make_backend_program(simplified_callable, entry_callable_id=program.entry_callable_id)

    verify_backend_program(simplified_program)

    assert _block_ids(simplified_callable) == (0, 3)
    assert isinstance(simplified_callable.blocks[0].terminator, BackendJumpTerminator)
    assert simplified_callable.blocks[0].terminator.target_block_id == ret_block.block_id
    assert simplified_callable.blocks[1].instructions == ret_block.instructions


def test_simplify_callable_cfg_preserves_merge_copy_blocks_from_lowered_if_join(tmp_path) -> None:
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

    simplified_callable = simplify_callable_cfg(fixture.callable_decl)
    simplified_program = replace_callable(fixture.program, simplified_callable)

    verify_backend_program(simplified_program)

    assert tuple(block.debug_name for block in simplified_callable.blocks) == (
        "entry",
        "if.then",
        "if.else",
        "if.end",
        "if.then_to_end",
        "if.else_to_end",
    )
    assert _block_by_name(simplified_callable, "if.then_to_end").instructions
    assert _block_by_name(simplified_callable, "if.else_to_end").instructions


def test_simplify_callable_cfg_keeps_loop_structure_valid(tmp_path) -> None:
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

    simplified_callable = simplify_callable_cfg(fixture.callable_decl)
    simplified_program = replace_callable(fixture.program, simplified_callable)

    verify_backend_program(simplified_program)

    assert _block_by_name(simplified_callable, "while.cond").block_id == _block_by_name(
        fixture.callable_decl, "while.cond"
    ).block_id
    assert _block_by_name(simplified_callable, "while.body").block_id == _block_by_name(
        fixture.callable_decl, "while.body"
    ).block_id
    assert _block_by_name(simplified_callable, "while.exit").block_id == _block_by_name(
        fixture.callable_decl, "while.exit"
    ).block_id
    assert {block.debug_name for block in simplified_callable.blocks} >= {"entry", "while.cond", "while.body", "while.exit"}
    assert len(simplified_callable.blocks) <= len(fixture.callable_decl.blocks)