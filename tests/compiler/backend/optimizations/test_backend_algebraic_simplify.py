from __future__ import annotations

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBinaryInst,
    BackendBlock,
    BackendBlockId,
    BackendBoolConst,
    BackendCallableDecl,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendInstId,
    BackendIntConst,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
    BackendUnaryInst,
)
from compiler.backend.ir.verify import verify_backend_program
from compiler.backend.optimizations import algebraic_simplify, optimize_backend_ir_program
from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64
from compiler.semantic.operations import (
    BinaryOpFlavor,
    BinaryOpKind,
    SemanticBinaryOp,
    SemanticUnaryOp,
    UnaryOpFlavor,
    UnaryOpKind,
)
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import make_source_span


CALLABLE_ID = FunctionId(module_path=("tests", "backend", "optimizations"), name="algebraic_main")


def test_algebraic_simplify_rewrites_integer_identity_and_annihilator_operations() -> None:
    program = _program_with_instructions(
        (
            _binary_i64(0, 1, BinaryOpKind.ADD, _reg(0), _i64(0)),
            _binary_i64(1, 2, BinaryOpKind.MULTIPLY, _reg(0), _i64(1)),
            _binary_i64(2, 3, BinaryOpKind.MULTIPLY, _reg(0), _i64(0)),
            _binary_i64(3, 4, BinaryOpKind.DIVIDE, _reg(0), _i64(1)),
            _binary_i64(4, 5, BinaryOpKind.REMAINDER, _reg(0), _i64(1)),
            _binary_i64(5, 6, BinaryOpKind.POWER, _reg(0), _u64(0)),
            _binary_i64(6, 7, BinaryOpKind.BITWISE_AND, _reg(0), _i64(-1)),
            _binary_i64(7, 8, BinaryOpKind.BITWISE_AND, _reg(0), _i64(0)),
            _binary_i64(8, 9, BinaryOpKind.BITWISE_OR, _reg(0), _i64(0)),
            _binary_i64(9, 10, BinaryOpKind.BITWISE_OR, _reg(0), _i64(-1)),
            _binary_i64(10, 11, BinaryOpKind.BITWISE_XOR, _reg(0), _i64(0)),
            _binary_i64(11, 12, BinaryOpKind.BITWISE_XOR, _reg(0), _reg(0)),
            _binary_i64(12, 13, BinaryOpKind.SHIFT_LEFT, _reg(0), _u64(0)),
        ),
        return_reg_id=_reg_id(13),
        registers=tuple(_register(ordinal, TYPE_NAME_I64) for ordinal in range(14)),
        param_type_name=TYPE_NAME_I64,
    )

    optimized = algebraic_simplify(program)
    verify_backend_program(optimized)

    instructions = optimized.callables[0].blocks[0].instructions
    assert _copy_source(instructions[0]) == _reg(0)
    assert _copy_source(instructions[1]) == _reg(0)
    assert _const(instructions[2]) == BackendIntConst(type_name=TYPE_NAME_I64, value=0)
    assert _copy_source(instructions[3]) == _reg(0)
    assert _const(instructions[4]) == BackendIntConst(type_name=TYPE_NAME_I64, value=0)
    assert _const(instructions[5]) == BackendIntConst(type_name=TYPE_NAME_I64, value=1)
    assert _copy_source(instructions[6]) == _reg(0)
    assert _const(instructions[7]) == BackendIntConst(type_name=TYPE_NAME_I64, value=0)
    assert _copy_source(instructions[8]) == _reg(0)
    assert _const(instructions[9]) == BackendIntConst(type_name=TYPE_NAME_I64, value=-1)
    assert _copy_source(instructions[10]) == _reg(0)
    assert _const(instructions[11]) == BackendIntConst(type_name=TYPE_NAME_I64, value=0)
    assert _copy_source(instructions[12]) == _reg(0)


def test_algebraic_simplify_rewrites_bool_identities_and_double_not() -> None:
    program = _program_with_instructions(
        (
            _bool_binary(0, 1, BinaryOpKind.LOGICAL_AND, _reg(0), _bool(True)),
            _bool_binary(1, 2, BinaryOpKind.LOGICAL_AND, _reg(0), _bool(False)),
            _bool_binary(2, 3, BinaryOpKind.LOGICAL_OR, _reg(0), _bool(False)),
            _bool_binary(3, 4, BinaryOpKind.LOGICAL_OR, _reg(0), _bool(True)),
            _bool_binary(4, 5, BinaryOpKind.EQUAL, _reg(0), _bool(True), flavor=BinaryOpFlavor.BOOL_COMPARISON),
            _bool_binary(5, 6, BinaryOpKind.EQUAL, _reg(0), _bool(False), flavor=BinaryOpFlavor.BOOL_COMPARISON),
            _bool_binary(6, 7, BinaryOpKind.NOT_EQUAL, _reg(0), _bool(False), flavor=BinaryOpFlavor.BOOL_COMPARISON),
            _bool_binary(7, 8, BinaryOpKind.NOT_EQUAL, _reg(0), _bool(True), flavor=BinaryOpFlavor.BOOL_COMPARISON),
            _not(8, 9, _reg(0)),
            _not(9, 10, _reg(9)),
        ),
        return_reg_id=_reg_id(10),
        registers=tuple(_register(ordinal, TYPE_NAME_BOOL) for ordinal in range(11)),
        param_type_name=TYPE_NAME_BOOL,
        return_type_name=TYPE_NAME_BOOL,
    )

    optimized = algebraic_simplify(program)
    verify_backend_program(optimized)

    instructions = optimized.callables[0].blocks[0].instructions
    assert _copy_source(instructions[0]) == _reg(0)
    assert _const(instructions[1]) == BackendBoolConst(value=False)
    assert _copy_source(instructions[2]) == _reg(0)
    assert _const(instructions[3]) == BackendBoolConst(value=True)
    assert _copy_source(instructions[4]) == _reg(0)
    assert isinstance(instructions[5], BackendUnaryInst)
    assert instructions[5].op.kind is UnaryOpKind.LOGICAL_NOT
    assert _copy_source(instructions[6]) == _reg(0)
    assert isinstance(instructions[7], BackendUnaryInst)
    assert instructions[7].op.kind is UnaryOpKind.LOGICAL_NOT
    assert _copy_source(instructions[9]) == _reg(0)


def test_backend_pipeline_propagates_algebraic_simplify_copies() -> None:
    program = _program_with_instructions(
        (_binary_i64(0, 1, BinaryOpKind.ADD, _reg(0), _i64(0)),),
        return_reg_id=_reg_id(1),
        registers=(_register(0, TYPE_NAME_I64), _register(1, TYPE_NAME_I64)),
        param_type_name=TYPE_NAME_I64,
    )

    optimized = optimize_backend_ir_program(program)
    verify_backend_program(optimized)

    block = optimized.callables[0].blocks[0]
    assert block.instructions == ()
    assert block.terminator.value == BackendRegOperand(reg_id=_reg_id(0))


def test_algebraic_simplify_logs_exact_summary_count(capsys) -> None:
    program = _program_with_instructions(
        (
            _binary_i64(0, 1, BinaryOpKind.ADD, _reg(0), _i64(0)),
            _binary_i64(1, 2, BinaryOpKind.MULTIPLY, _reg(0), _i64(1)),
        ),
        return_reg_id=_reg_id(2),
        registers=(_register(0, TYPE_NAME_I64), _register(1, TYPE_NAME_I64), _register(2, TYPE_NAME_I64)),
        param_type_name=TYPE_NAME_I64,
    )
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    algebraic_simplify(program)
    captured = capsys.readouterr()

    assert captured.err.strip() == (
        "nifc: debug: Backend optimization pass algebraic_simplify simplified 2 instructions across 1 callables"
    )


def _program_with_instructions(
    instructions,
    *,
    return_reg_id: BackendRegId,
    registers: tuple[BackendRegister, ...],
    param_type_name: str,
    return_type_name: str = TYPE_NAME_I64,
) -> BackendProgram:
    callable_decl = BackendCallableDecl(
        callable_id=CALLABLE_ID,
        kind="function",
        signature=BackendSignature(
            param_types=(semantic_primitive_type_ref(param_type_name),),
            return_type=semantic_primitive_type_ref(return_type_name),
        ),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=registers,
        param_regs=(_reg_id(0),),
        receiver_reg=None,
        entry_block_id=_block_id(0),
        blocks=(
            BackendBlock(
                block_id=_block_id(0),
                debug_name="entry",
                instructions=tuple(instructions),
                terminator=BackendReturnTerminator(
                    span=make_source_span(),
                    value=BackendRegOperand(reg_id=return_reg_id),
                ),
                span=make_source_span(),
            ),
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


def _binary_i64(inst_ordinal: int, dest_ordinal: int, kind: BinaryOpKind, left, right) -> BackendBinaryInst:
    return BackendBinaryInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(dest_ordinal),
        op=SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.INTEGER),
        left=left,
        right=right,
        span=make_source_span(),
    )


def _bool_binary(
    inst_ordinal: int,
    dest_ordinal: int,
    kind: BinaryOpKind,
    left,
    right,
    *,
    flavor: BinaryOpFlavor = BinaryOpFlavor.BOOL_LOGICAL,
) -> BackendBinaryInst:
    return BackendBinaryInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(dest_ordinal),
        op=SemanticBinaryOp(kind=kind, flavor=flavor),
        left=left,
        right=right,
        span=make_source_span(),
    )


def _not(inst_ordinal: int, dest_ordinal: int, operand) -> BackendUnaryInst:
    return BackendUnaryInst(
        inst_id=_inst_id(inst_ordinal),
        dest=_reg_id(dest_ordinal),
        op=SemanticUnaryOp(kind=UnaryOpKind.LOGICAL_NOT, flavor=UnaryOpFlavor.BOOL),
        operand=operand,
        span=make_source_span(),
    )


def _copy_source(instruction) -> BackendRegOperand | BackendConstOperand:
    assert isinstance(instruction, BackendCopyInst)
    return instruction.source


def _const(instruction):
    assert isinstance(instruction, BackendConstInst)
    return instruction.constant


def _i64(value: int) -> BackendConstOperand:
    return BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_I64, value=value))


def _u64(value: int) -> BackendConstOperand:
    return BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_U64, value=value))


def _bool(value: bool) -> BackendConstOperand:
    return BackendConstOperand(constant=BackendBoolConst(value=value))


def _reg(ordinal: int) -> BackendRegOperand:
    return BackendRegOperand(reg_id=_reg_id(ordinal))


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
