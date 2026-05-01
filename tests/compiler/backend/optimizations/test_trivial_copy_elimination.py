from __future__ import annotations

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBinaryInst,
    BackendBlock,
    BackendBlockId,
    BackendCallableDecl,
    BackendConstInst,
    BackendCopyInst,
    BackendInstId,
    BackendIntConst,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.backend.ir.verify import verify_backend_program
from compiler.backend.optimizations import trivial_copy_elimination
from compiler.common.type_names import TYPE_NAME_I64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, SemanticBinaryOp
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import make_source_span


CALLABLE_ID = FunctionId(module_path=("tests", "backend", "optimizations"), name="copy_main")


def test_trivial_copy_elimination_removes_self_copy() -> None:
    program = _program_with_instructions(
        (
            _const(0, 0, 7),
            BackendCopyInst(inst_id=_inst_id(1), dest=_reg_id(0), source=BackendRegOperand(reg_id=_reg_id(0)), span=make_source_span()),
        ),
        return_reg_id=_reg_id(0),
        register_ordinals=(0,),
    )

    optimized = trivial_copy_elimination(program)
    verify_backend_program(optimized)

    instructions = optimized.callables[0].blocks[0].instructions
    assert tuple(instruction.inst_id.ordinal for instruction in instructions) == (0,)


def test_trivial_copy_elimination_propagates_block_local_copy_operands_and_removes_dead_copies() -> None:
    program = _program_with_instructions(
        (
            _const(0, 0, 7),
            BackendCopyInst(inst_id=_inst_id(1), dest=_reg_id(1), source=BackendRegOperand(reg_id=_reg_id(0)), span=make_source_span()),
            BackendCopyInst(inst_id=_inst_id(2), dest=_reg_id(2), source=BackendRegOperand(reg_id=_reg_id(1)), span=make_source_span()),
            BackendBinaryInst(
                inst_id=_inst_id(3),
                dest=_reg_id(3),
                op=SemanticBinaryOp(kind=BinaryOpKind.ADD, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=_reg_id(2)),
                right=BackendRegOperand(reg_id=_reg_id(0)),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(3),
    )

    optimized = trivial_copy_elimination(program)
    verify_backend_program(optimized)

    instructions = optimized.callables[0].blocks[0].instructions
    assert tuple(instruction.inst_id.ordinal for instruction in instructions) == (0, 3)
    assert isinstance(instructions[1], BackendBinaryInst)
    assert instructions[1].left == BackendRegOperand(reg_id=_reg_id(0))


def test_trivial_copy_elimination_rewrites_return_operand_and_removes_copy() -> None:
    program = _program_with_instructions(
        (
            _const(0, 0, 9),
            BackendCopyInst(inst_id=_inst_id(1), dest=_reg_id(1), source=BackendRegOperand(reg_id=_reg_id(0)), span=make_source_span()),
        ),
        return_reg_id=_reg_id(1),
        register_ordinals=(0, 1),
    )

    optimized = trivial_copy_elimination(program)
    verify_backend_program(optimized)

    block = optimized.callables[0].blocks[0]
    assert tuple(instruction.inst_id.ordinal for instruction in block.instructions) == (0,)
    assert block.terminator.value == BackendRegOperand(reg_id=_reg_id(0))


def _program_with_instructions(
    instructions,
    *,
    return_reg_id: BackendRegId,
    register_ordinals: tuple[int, ...] = (0, 1, 2, 3),
) -> BackendProgram:
    span = make_source_span()
    callable_decl = BackendCallableDecl(
        callable_id=CALLABLE_ID,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=tuple(
            BackendRegister(
                reg_id=_reg_id(ordinal),
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name=f"r{ordinal}",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            )
            for ordinal in register_ordinals
        ),
        param_regs=(),
        receiver_reg=None,
        entry_block_id=_block_id(0),
        blocks=(
            BackendBlock(
                block_id=_block_id(0),
                debug_name="entry",
                instructions=tuple(instructions),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=return_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=CALLABLE_ID,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )


def _const(inst_ordinal: int, reg_ordinal: int, value: int) -> BackendConstInst:
    return BackendConstInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(reg_ordinal),
        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=value),
        span=make_source_span(),
    )


def _reg_id(ordinal: int) -> BackendRegId:
    return BackendRegId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _block_id(ordinal: int) -> BackendBlockId:
    return BackendBlockId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _inst_id(ordinal: int) -> BackendInstId:
    return BackendInstId(owner_id=CALLABLE_ID, ordinal=ordinal)
