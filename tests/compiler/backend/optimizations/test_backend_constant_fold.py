from __future__ import annotations

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBinaryInst,
    BackendBlock,
    BackendBlockId,
    BackendBoolConst,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendCastInst,
    BackendConstInst,
    BackendConstOperand,
    BackendDoubleConst,
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
from compiler.backend.ir.verify import verify_backend_program
from compiler.backend.optimizations import constant_fold, optimize_backend_ir_program
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, CastSemanticsKind, SemanticBinaryOp
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import make_source_span


CALLABLE_ID = FunctionId(module_path=("tests", "backend", "optimizations"), name="fold_main")


def test_constant_fold_folds_integer_binary_with_block_local_constant() -> None:
    program = _program_with_instructions(
        (
            _const_i64(0, 0, 2),
            BackendBinaryInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                op=SemanticBinaryOp(kind=BinaryOpKind.ADD, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=_reg_id(0)),
                right=BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_I64, value=5)),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(1),
        register_ordinals=(0, 1),
    )

    optimized = constant_fold(program)
    verify_backend_program(optimized)

    folded = optimized.callables[0].blocks[0].instructions[1]
    assert isinstance(folded, BackendConstInst)
    assert folded.constant == BackendIntConst(type_name=TYPE_NAME_I64, value=7)


def test_constant_fold_propagates_bool_to_branch_condition_for_cfg_simplification() -> None:
    true_block_id = _block_id(1)
    false_block_id = _block_id(2)
    program = _program_with_instructions(
        (_const_bool(0, 0, True),),
        return_reg_id=_reg_id(1),
        registers=(
            _register(0, TYPE_NAME_BOOL),
            _register(1, TYPE_NAME_I64),
        ),
        terminator=BackendBranchTerminator(
            span=make_source_span(),
            condition=BackendRegOperand(reg_id=_reg_id(0)),
            true_block_id=true_block_id,
            false_block_id=false_block_id,
        ),
        extra_blocks=(
            _return_block(1, _const_i64(1, 1, 10)),
            _return_block(2, _const_i64(2, 1, 20)),
        ),
    )

    folded = constant_fold(program)
    verify_backend_program(folded)

    condition = folded.callables[0].blocks[0].terminator.condition
    assert condition == BackendConstOperand(constant=BackendBoolConst(value=True))

    fully_optimized = optimize_backend_ir_program(program)
    verify_backend_program(fully_optimized)
    main_callable = fully_optimized.callables[0]
    assert tuple(block.block_id.ordinal for block in main_callable.blocks) == (0, 1)
    assert isinstance(main_callable.blocks[0].terminator, BackendJumpTerminator)
    assert main_callable.blocks[0].terminator.target_block_id == true_block_id


def test_constant_fold_folds_safe_double_to_integer_cast() -> None:
    program = _program_with_instructions(
        (
            BackendConstInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                constant=BackendDoubleConst(value=7.9),
                span=make_source_span(),
            ),
            BackendCastInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                cast_kind=CastSemanticsKind.TO_INTEGER,
                operand=BackendRegOperand(reg_id=_reg_id(0)),
                target_type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                trap_on_failure=False,
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(1),
        registers=(
            _register(0, TYPE_NAME_DOUBLE),
            _register(1, TYPE_NAME_I64),
        ),
    )

    optimized = constant_fold(program)
    verify_backend_program(optimized)

    folded = optimized.callables[0].blocks[0].instructions[1]
    assert isinstance(folded, BackendConstInst)
    assert folded.constant == BackendIntConst(type_name=TYPE_NAME_I64, value=7)


def test_constant_fold_preserves_out_of_range_shift_and_double_to_integer_cast() -> None:
    program = _program_with_instructions(
        (
            _const_i64(0, 0, 1),
            BackendBinaryInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                op=SemanticBinaryOp(kind=BinaryOpKind.SHIFT_LEFT, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=_reg_id(0)),
                right=BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_U64, value=64)),
                span=make_source_span(),
            ),
            BackendConstInst(
                inst_id=_inst_id(2),
                dest=_reg_id(2),
                constant=BackendDoubleConst(value=9223372036854775808.0),
                span=make_source_span(),
            ),
            BackendCastInst(
                inst_id=_inst_id(3),
                dest=_reg_id(3),
                cast_kind=CastSemanticsKind.TO_INTEGER,
                operand=BackendRegOperand(reg_id=_reg_id(2)),
                target_type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                trap_on_failure=False,
                span=make_source_span(),
            ),
            _const_i64(4, 4, 0),
        ),
        return_reg_id=_reg_id(4),
        registers=(
            _register(0, TYPE_NAME_I64),
            _register(1, TYPE_NAME_I64),
            _register(2, TYPE_NAME_DOUBLE),
            _register(3, TYPE_NAME_I64),
            _register(4, TYPE_NAME_I64),
        ),
    )

    optimized = constant_fold(program)
    verify_backend_program(optimized)

    instructions = optimized.callables[0].blocks[0].instructions
    assert isinstance(instructions[1], BackendBinaryInst)
    assert isinstance(instructions[3], BackendCastInst)


def _program_with_instructions(
    instructions,
    *,
    return_reg_id: BackendRegId,
    register_ordinals: tuple[int, ...] = (0, 1, 2, 3),
    registers: tuple[BackendRegister, ...] | None = None,
    terminator=None,
    extra_blocks: tuple[BackendBlock, ...] = (),
) -> BackendProgram:
    resolved_registers = (
        tuple(_register(ordinal, TYPE_NAME_I64) for ordinal in register_ordinals)
        if registers is None
        else registers
    )
    callable_decl = BackendCallableDecl(
        callable_id=CALLABLE_ID,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=resolved_registers,
        param_regs=(),
        receiver_reg=None,
        entry_block_id=_block_id(0),
        blocks=(
            BackendBlock(
                block_id=_block_id(0),
                debug_name="entry",
                instructions=tuple(instructions),
                terminator=terminator
                if terminator is not None
                else BackendReturnTerminator(span=make_source_span(), value=BackendRegOperand(reg_id=return_reg_id)),
                span=make_source_span(),
            ),
            *extra_blocks,
        ),
        span=make_source_span(),
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=CALLABLE_ID,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )


def _return_block(block_ordinal: int, const_inst: BackendConstInst) -> BackendBlock:
    return BackendBlock(
        block_id=_block_id(block_ordinal),
        debug_name=f"return.{block_ordinal}",
        instructions=(const_inst,),
        terminator=BackendReturnTerminator(span=make_source_span(), value=BackendRegOperand(reg_id=const_inst.dest)),
        span=make_source_span(),
    )


def _const_i64(inst_ordinal: int, reg_ordinal: int, value: int) -> BackendConstInst:
    return BackendConstInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(reg_ordinal),
        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=value),
        span=make_source_span(),
    )


def _const_bool(inst_ordinal: int, reg_ordinal: int, value: bool) -> BackendConstInst:
    return BackendConstInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(reg_ordinal),
        constant=BackendBoolConst(value=value),
        span=make_source_span(),
    )


def _register(ordinal: int, type_name: str) -> BackendRegister:
    return BackendRegister(
        reg_id=_reg_id(ordinal),
        type_ref=semantic_primitive_type_ref(type_name),
        debug_name=f"r{ordinal}",
        origin_kind="temp",
        semantic_local_id=None,
        span=None,
    )


def _reg_id(ordinal: int) -> BackendRegId:
    return BackendRegId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _block_id(ordinal: int) -> BackendBlockId:
    return BackendBlockId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _inst_id(ordinal: int) -> BackendInstId:
    return BackendInstId(owner_id=CALLABLE_ID, ordinal=ordinal)
