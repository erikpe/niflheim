from __future__ import annotations

from compiler.backend.analysis import order_callable_blocks, ordered_block_ids_for_callable, run_backend_ir_pipeline
from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendConstInst,
    BackendInstId,
    BackendIntConst,
    BackendJumpTerminator,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.backend.ir.text import dump_backend_program_text
from compiler.backend.ir.verify import verify_backend_program
from compiler.common.span import SourceSpan
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_program
from tests.compiler.backend.ir.helpers import FIXTURE_ENTRY_FUNCTION_ID, make_source_span


def test_order_callable_blocks_reorders_scrambled_branch_callable_in_reverse_postorder() -> None:
    callable_decl = _scrambled_branch_callable()

    ordered_ids = ordered_block_ids_for_callable(callable_decl)
    ordered_callable = order_callable_blocks(callable_decl)

    assert [block.ordinal for block in ordered_ids] == [0, 2, 1, 3]
    assert [block.block_id.ordinal for block in ordered_callable.blocks] == [0, 2, 1, 3]


def test_dump_backend_program_text_preserves_callable_block_order() -> None:
    callable_decl = order_callable_blocks(_scrambled_branch_callable())
    program = BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=FIXTURE_ENTRY_FUNCTION_ID,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )

    rendered = dump_backend_program_text(program, preserve_block_order=True)
    entry_pos = rendered.index("  b0 entry:")
    else_pos = rendered.index("  b2 else:")
    then_pos = rendered.index("  b1 then:")
    join_pos = rendered.index("  b3 join:")

    assert entry_pos < else_pos < then_pos < join_pos


def test_run_backend_ir_pipeline_simplifies_and_populates_analysis(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn helper(value: i64) -> i64 {
            return value + 1;
        }

        fn example(flag: bool) -> i64 {
            var current: i64 = 1;
            if flag {
                current = helper(current);
            } else {
                current = helper(current + 1);
            }
            return current;
        }

        fn main() -> i64 {
            return example(true);
        }
        """
    )

    result = run_backend_ir_pipeline(program)
    example_callable = next(
        callable_decl for callable_decl in result.program.callables if callable_decl.callable_id.name == "example"
    )
    example_analysis = result.analysis_by_callable_id[example_callable.callable_id]

    verify_backend_program(result.program)
    assert tuple(block.block_id for block in example_callable.blocks) == example_analysis.ordered_block_ids
    assert example_analysis.analysis_dump.predecessors
    assert example_analysis.analysis_dump.successors
    assert example_analysis.analysis_dump.live_in
    assert example_analysis.stack_homes.home_count > 0


def _scrambled_branch_callable() -> BackendCallableDecl:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/block_order.nif")
    flag_reg = BackendRegId(owner_id=callable_id, ordinal=0)
    then_reg = BackendRegId(owner_id=callable_id, ordinal=1)
    block_entry = BackendBlockId(owner_id=callable_id, ordinal=0)
    block_then = BackendBlockId(owner_id=callable_id, ordinal=1)
    block_else = BackendBlockId(owner_id=callable_id, ordinal=2)
    block_join = BackendBlockId(owner_id=callable_id, ordinal=3)

    callable_decl = BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(
            param_types=(semantic_primitive_type_ref(TYPE_NAME_BOOL),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
        ),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=(
            _register(flag_reg, TYPE_NAME_BOOL, "flag", "param", span),
            _register(then_reg, TYPE_NAME_I64, "value", "temp", None),
        ),
        param_regs=(flag_reg,),
        receiver_reg=None,
        entry_block_id=block_entry,
        blocks=(
            _join_block(block_join, then_reg, span),
            _then_block(block_then, then_reg, 1, block_join, span),
            _entry_block(block_entry, flag_reg, block_then, block_else, span),
            _else_block(block_else, then_reg, 2, block_join, span),
        ),
        span=span,
    )
    verify_backend_program(
        BackendProgram(
            schema_version=BACKEND_IR_SCHEMA_VERSION,
            entry_callable_id=callable_id,
            data_blobs=(),
            interfaces=(),
            classes=(),
            callables=(callable_decl,),
        )
    )
    return callable_decl


def _register(reg_id: BackendRegId, type_name: str, debug_name: str, origin_kind: str, span: SourceSpan | None) -> BackendRegister:
    return BackendRegister(
        reg_id=reg_id,
        type_ref=semantic_primitive_type_ref(type_name),
        debug_name=debug_name,
        origin_kind=origin_kind,
        semantic_local_id=None,
        span=span,
    )


def _entry_block(
    block_id: BackendBlockId,
    flag_reg: BackendRegId,
    then_block_id: BackendBlockId,
    else_block_id: BackendBlockId,
    span: SourceSpan,
) -> BackendBlock:
    return BackendBlock(
        block_id=block_id,
        debug_name="entry",
        instructions=(),
        terminator=BackendBranchTerminator(
            span=span,
            condition=BackendRegOperand(reg_id=flag_reg),
            true_block_id=then_block_id,
            false_block_id=else_block_id,
        ),
        span=span,
    )


def _then_block(
    block_id: BackendBlockId,
    dest_reg: BackendRegId,
    value: int,
    join_block_id: BackendBlockId,
    span: SourceSpan,
) -> BackendBlock:
    return BackendBlock(
        block_id=block_id,
        debug_name="then",
        instructions=(
            _const_inst(dest_reg, 1, value, span),
        ),
        terminator=BackendJumpTerminator(span=span, target_block_id=join_block_id),
        span=span,
    )


def _else_block(
    block_id: BackendBlockId,
    dest_reg: BackendRegId,
    value: int,
    join_block_id: BackendBlockId,
    span: SourceSpan,
) -> BackendBlock:
    return BackendBlock(
        block_id=block_id,
        debug_name="else",
        instructions=(
            _const_inst(dest_reg, 2, value, span),
        ),
        terminator=BackendJumpTerminator(span=span, target_block_id=join_block_id),
        span=span,
    )


def _join_block(block_id: BackendBlockId, return_reg: BackendRegId, span: SourceSpan) -> BackendBlock:
    return BackendBlock(
        block_id=block_id,
        debug_name="join",
        instructions=(),
        terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=return_reg)),
        span=span,
    )


def _const_inst(dest_reg: BackendRegId, inst_ordinal: int, value: int, span: SourceSpan) -> BackendConstInst:
    return BackendConstInst(
        inst_id=BackendInstId(owner_id=dest_reg.owner_id, ordinal=inst_ordinal),
        dest=dest_reg,
        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=value),
        span=span,
    )