from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from compiler.backend.analysis import analyze_callable_liveness
from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBlockId,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendInstruction,
    BackendInstId,
    BackendIntConst,
    BackendJumpTerminator,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.common.span import SourceSpan
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, SemanticBinaryOp
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.ir.helpers import make_source_span


def _manual_callable(
    *,
    name: str,
    registers: tuple[BackendRegister, ...],
    param_regs: tuple[BackendRegId, ...],
    blocks: tuple[BackendBlock, ...],
    return_type_name: str,
) -> BackendCallableDecl:
    callable_id = FunctionId(module_path=("tests", "backend", "analysis"), name=name)
    remapped_param_regs = tuple(BackendRegId(owner_id=callable_id, ordinal=reg_id.ordinal) for reg_id in param_regs)
    remapped_registers = tuple(
        replace(register, reg_id=BackendRegId(owner_id=callable_id, ordinal=register.reg_id.ordinal))
        for register in registers
    )
    reg_map = {register.reg_id.ordinal: register.reg_id for register in remapped_registers}

    def remap_operand(operand):
        if isinstance(operand, BackendRegOperand):
            return BackendRegOperand(reg_id=reg_map[operand.reg_id.ordinal])
        return operand

    remapped_blocks: list[BackendBlock] = []
    for block in blocks:
        block_id = BackendBlockId(owner_id=callable_id, ordinal=block.block_id.ordinal)
        remapped_instructions: list[BackendInstruction] = []
        for instruction in block.instructions:
            inst_id = BackendInstId(owner_id=callable_id, ordinal=instruction.inst_id.ordinal)
            if isinstance(instruction, BackendCopyInst):
                remapped_instructions.append(
                    BackendCopyInst(inst_id=inst_id, dest=reg_map[instruction.dest.ordinal], source=remap_operand(instruction.source), span=instruction.span)
                )
                continue
            if isinstance(instruction, BackendConstInst):
                remapped_instructions.append(
                    BackendConstInst(inst_id=inst_id, dest=reg_map[instruction.dest.ordinal], constant=instruction.constant, span=instruction.span)
                )
                continue
            if isinstance(instruction, BackendBinaryInst):
                remapped_instructions.append(
                    BackendBinaryInst(
                        inst_id=inst_id,
                        dest=reg_map[instruction.dest.ordinal],
                        op=instruction.op,
                        left=remap_operand(instruction.left),
                        right=remap_operand(instruction.right),
                        span=instruction.span,
                    )
                )
                continue
            raise TypeError(f"Unsupported manual test instruction type '{type(instruction).__name__}'")
        terminator = block.terminator
        if isinstance(terminator, BackendJumpTerminator):
            remapped_terminator = BackendJumpTerminator(
                span=terminator.span,
                target_block_id=BackendBlockId(owner_id=callable_id, ordinal=terminator.target_block_id.ordinal),
            )
        elif isinstance(terminator, BackendBranchTerminator):
            remapped_terminator = BackendBranchTerminator(
                span=terminator.span,
                condition=remap_operand(terminator.condition),
                true_block_id=BackendBlockId(owner_id=callable_id, ordinal=terminator.true_block_id.ordinal),
                false_block_id=BackendBlockId(owner_id=callable_id, ordinal=terminator.false_block_id.ordinal),
            )
        elif isinstance(terminator, BackendReturnTerminator):
            remapped_terminator = BackendReturnTerminator(
                span=terminator.span,
                value=None if terminator.value is None else remap_operand(terminator.value),
            )
        else:
            raise TypeError(f"Unsupported manual test terminator type '{type(terminator).__name__}'")
        remapped_blocks.append(
            BackendBlock(
                block_id=block_id,
                debug_name=block.debug_name,
                instructions=tuple(remapped_instructions),
                terminator=remapped_terminator,
                span=block.span,
            )
        )

    return BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(
            param_types=tuple(
                next(register.type_ref for register in remapped_registers if register.reg_id == param_reg_id)
                for param_reg_id in remapped_param_regs
            ),
            return_type=semantic_primitive_type_ref(return_type_name),
        ),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=remapped_registers,
        param_regs=remapped_param_regs,
        receiver_reg=None,
        entry_block_id=BackendBlockId(owner_id=callable_id, ordinal=blocks[0].block_id.ordinal),
        blocks=tuple(remapped_blocks),
        span=blocks[0].span,
    )


def _make_register(ordinal: int, type_name: str, debug_name: str, origin_kind: str = "temp") -> BackendRegister:
    return BackendRegister(
        reg_id=BackendRegId(owner_id=FunctionId(module_path=("placeholder",), name="placeholder"), ordinal=ordinal),
        type_ref=semantic_primitive_type_ref(type_name),
        debug_name=debug_name,
        origin_kind=origin_kind,
        semantic_local_id=None,
        span=None,
    )


def _make_block(block_ordinal: int, debug_name: str, instructions: tuple[BackendInstruction, ...], terminator, span: SourceSpan) -> BackendBlock:
    return BackendBlock(
        block_id=BackendBlockId(owner_id=FunctionId(module_path=("placeholder",), name="placeholder"), ordinal=block_ordinal),
        debug_name=debug_name,
        instructions=instructions,
        terminator=terminator,
        span=span,
    )


def _make_inst_id(ordinal: int) -> BackendInstId:
    return BackendInstId(owner_id=FunctionId(module_path=("placeholder",), name="placeholder"), ordinal=ordinal)


def _reg_ids(*registers: BackendRegId) -> tuple[BackendRegId, ...]:
    return tuple(registers)


def test_analyze_callable_liveness_tracks_straight_line_live_sets_and_dead_temps() -> None:
    span = make_source_span(path="fixtures/liveness_straight_line.nif")
    input_reg = _make_register(0, "i64", "input", origin_kind="param")
    base_reg = _make_register(1, "i64", "base")
    sum_reg = _make_register(2, "i64", "sum")
    dead_reg = _make_register(3, "i64", "dead")
    block = _make_block(
        0,
        "entry",
        (
            BackendCopyInst(inst_id=_make_inst_id(0), dest=base_reg.reg_id, source=BackendRegOperand(reg_id=input_reg.reg_id), span=span),
            BackendBinaryInst(
                inst_id=_make_inst_id(1),
                dest=sum_reg.reg_id,
                op=SemanticBinaryOp(kind=BinaryOpKind.ADD, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=base_reg.reg_id),
                right=BackendConstOperand(constant=BackendIntConst(type_name="i64", value=1)),
                span=span,
            ),
            BackendConstInst(inst_id=_make_inst_id(2), dest=dead_reg.reg_id, constant=BackendIntConst(type_name="i64", value=9), span=span),
        ),
        BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=sum_reg.reg_id)),
        span,
    )
    callable_decl = _manual_callable(
        name="straight_line",
        registers=(input_reg, base_reg, sum_reg, dead_reg),
        param_regs=(input_reg.reg_id,),
        blocks=(block,),
        return_type_name="i64",
    )

    liveness = analyze_callable_liveness(callable_decl)
    entry_block_id = callable_decl.blocks[0].block_id

    assert liveness.block_live_in(entry_block_id) == _reg_ids(callable_decl.param_regs[0])
    assert liveness.block_live_out(entry_block_id) == ()
    assert liveness.instruction_live_after(callable_decl.blocks[0].instructions[0].inst_id) == _reg_ids(callable_decl.blocks[0].instructions[0].dest)
    assert liveness.instruction_live_before(callable_decl.blocks[0].instructions[0].inst_id) == _reg_ids(callable_decl.param_regs[0])
    assert liveness.instruction_live_after(callable_decl.blocks[0].instructions[2].inst_id) == _reg_ids(callable_decl.blocks[0].instructions[1].dest)
    assert liveness.instruction_live_before(callable_decl.blocks[0].instructions[2].inst_id) == _reg_ids(callable_decl.blocks[0].instructions[1].dest)


def test_analyze_callable_liveness_unions_branch_successor_requirements() -> None:
    span = make_source_span(path="fixtures/liveness_branch.nif")
    cond_reg = _make_register(0, "bool", "cond", origin_kind="param")
    left_reg = _make_register(1, "i64", "left", origin_kind="param")
    right_reg = _make_register(2, "i64", "right", origin_kind="param")
    entry_block = _make_block(
        0,
        "entry",
        (),
        BackendBranchTerminator(
            span=span,
            condition=BackendRegOperand(reg_id=cond_reg.reg_id),
            true_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=1),
            false_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=2),
        ),
        span,
    )
    true_block = _make_block(
        1,
        "left",
        (),
        BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=left_reg.reg_id)),
        span,
    )
    false_block = _make_block(
        2,
        "right",
        (),
        BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=right_reg.reg_id)),
        span,
    )
    callable_decl = _manual_callable(
        name="branch_union",
        registers=(cond_reg, left_reg, right_reg),
        param_regs=(cond_reg.reg_id, left_reg.reg_id, right_reg.reg_id),
        blocks=(entry_block, true_block, false_block),
        return_type_name="i64",
    )

    liveness = analyze_callable_liveness(callable_decl)
    entry_block_id = callable_decl.blocks[0].block_id
    true_block_id = callable_decl.blocks[1].block_id
    false_block_id = callable_decl.blocks[2].block_id

    assert liveness.block_live_out(entry_block_id) == _reg_ids(callable_decl.param_regs[1], callable_decl.param_regs[2])
    assert liveness.block_live_in(entry_block_id) == _reg_ids(*callable_decl.param_regs)
    assert liveness.block_live_in(true_block_id) == _reg_ids(callable_decl.param_regs[1])
    assert liveness.block_live_in(false_block_id) == _reg_ids(callable_decl.param_regs[2])


def test_analyze_callable_liveness_converges_for_loop_carried_registers() -> None:
    span = make_source_span(path="fixtures/liveness_loop.nif")
    cond_reg = _make_register(0, "bool", "cond", origin_kind="param")
    keep_reg = _make_register(1, "i64", "keep", origin_kind="param")
    entry_block = _make_block(
        0,
        "entry",
        (),
        BackendJumpTerminator(span=span, target_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=1)),
        span,
    )
    cond_block = _make_block(
        1,
        "loop.cond",
        (),
        BackendBranchTerminator(
            span=span,
            condition=BackendRegOperand(reg_id=cond_reg.reg_id),
            true_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=2),
            false_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=3),
        ),
        span,
    )
    body_block = _make_block(
        2,
        "loop.body",
        (),
        BackendJumpTerminator(span=span, target_block_id=BackendBlockId(owner_id=cond_reg.reg_id.owner_id, ordinal=1)),
        span,
    )
    exit_block = _make_block(
        3,
        "loop.exit",
        (),
        BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=keep_reg.reg_id)),
        span,
    )
    callable_decl = _manual_callable(
        name="loop_convergence",
        registers=(cond_reg, keep_reg),
        param_regs=(cond_reg.reg_id, keep_reg.reg_id),
        blocks=(entry_block, cond_block, body_block, exit_block),
        return_type_name="i64",
    )

    liveness = analyze_callable_liveness(callable_decl)
    entry_block_id, cond_block_id, body_block_id, exit_block_id = (block.block_id for block in callable_decl.blocks)

    assert liveness.block_live_in(exit_block_id) == _reg_ids(callable_decl.param_regs[1])
    assert liveness.block_live_in(cond_block_id) == _reg_ids(*callable_decl.param_regs)
    assert liveness.block_live_out(cond_block_id) == _reg_ids(*callable_decl.param_regs)
    assert liveness.block_live_in(body_block_id) == _reg_ids(*callable_decl.param_regs)
    assert liveness.block_live_in(entry_block_id) == _reg_ids(*callable_decl.param_regs)


def test_analyze_callable_liveness_tracks_join_copy_blocks_from_lowered_if(tmp_path: Path) -> None:
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

    liveness = analyze_callable_liveness(fixture.callable_decl)
    then_to_end_block = next(block for block in fixture.callable_decl.blocks if block.debug_name == "if.then_to_end")
    copy_inst = then_to_end_block.instructions[0]
    assert isinstance(copy_inst, BackendCopyInst)
    assert isinstance(copy_inst.source, BackendRegOperand)

    assert liveness.block_live_in(then_to_end_block.block_id) == _reg_ids(copy_inst.source.reg_id)
    assert liveness.block_live_out(then_to_end_block.block_id) == _reg_ids(copy_inst.dest)
    assert liveness.instruction_live_before(copy_inst.inst_id) == _reg_ids(copy_inst.source.reg_id)
    assert liveness.instruction_live_after(copy_inst.inst_id) == _reg_ids(copy_inst.dest)