from __future__ import annotations

from dataclasses import replace

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBinaryInst,
    BackendBlock,
    BackendBlockId,
    BackendCallInst,
    BackendCallableDecl,
    BackendCastInst,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendDirectCallTarget,
    BackendDoubleConst,
    BackendEffects,
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
from compiler.backend.optimizations import dead_pure_definition_elimination, optimize_backend_ir_program
from compiler.common.type_names import TYPE_NAME_DOUBLE, TYPE_NAME_I64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, CastSemanticsKind, SemanticBinaryOp
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import make_source_span


CALLABLE_ID = FunctionId(module_path=("tests", "backend", "optimizations"), name="main")
HELPER_ID = FunctionId(module_path=("tests", "backend", "optimizations"), name="helper")


def test_dead_pure_definition_elimination_removes_cascading_dead_defs_and_registers() -> None:
    program = _program_with_instructions(
        (
            BackendConstInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=10),
                span=make_source_span(),
            ),
            BackendCopyInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                source=BackendRegOperand(reg_id=_reg_id(0)),
                span=make_source_span(),
            ),
            BackendBinaryInst(
                inst_id=_inst_id(2),
                dest=_reg_id(2),
                op=SemanticBinaryOp(kind=BinaryOpKind.ADD, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=_reg_id(1)),
                right=BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1)),
                span=make_source_span(),
            ),
            BackendConstInst(
                inst_id=_inst_id(3),
                dest=_reg_id(3),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(3),
    )

    optimized = dead_pure_definition_elimination(program)
    verify_backend_program(optimized)

    callable_decl = optimized.callables[0]
    assert tuple(instruction.inst_id.ordinal for instruction in callable_decl.blocks[0].instructions) == (3,)
    assert tuple(register.reg_id.ordinal for register in callable_decl.registers) == (3,)


def test_dead_pure_definition_elimination_preserves_calls_even_when_dest_is_dead() -> None:
    program = _program_with_instructions(
        (
            BackendCallInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                target=BackendDirectCallTarget(callable_id=HELPER_ID),
                args=(),
                signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
                effects=BackendEffects(),
                span=make_source_span(),
            ),
            BackendConstInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(1),
        register_ordinals=(0, 1),
    )

    optimized = dead_pure_definition_elimination(program)
    verify_backend_program(optimized)

    callable_decl = optimized.callables[0]
    assert tuple(instruction.inst_id.ordinal for instruction in callable_decl.blocks[0].instructions) == (0, 1)
    assert tuple(register.reg_id.ordinal for register in callable_decl.registers) == (0, 1)


def test_dead_pure_definition_elimination_preserves_dead_shift_because_it_can_trap() -> None:
    program = _program_with_instructions(
        (
            BackendConstInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                span=make_source_span(),
            ),
            BackendBinaryInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                op=SemanticBinaryOp(kind=BinaryOpKind.SHIFT_LEFT, flavor=BinaryOpFlavor.INTEGER),
                left=BackendRegOperand(reg_id=_reg_id(0)),
                right=BackendConstOperand(constant=BackendIntConst(type_name="u64", value=64)),
                span=make_source_span(),
            ),
            BackendConstInst(
                inst_id=_inst_id(2),
                dest=_reg_id(2),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(2),
        register_ordinals=(0, 1, 2),
    )

    optimized = dead_pure_definition_elimination(program)
    verify_backend_program(optimized)

    callable_decl = optimized.callables[0]
    assert tuple(instruction.inst_id.ordinal for instruction in callable_decl.blocks[0].instructions) == (0, 1, 2)
    assert tuple(register.reg_id.ordinal for register in callable_decl.registers) == (0, 1, 2)


def test_dead_pure_definition_elimination_preserves_dead_double_to_integer_cast_because_it_can_trap() -> None:
    program = _program_with_instructions(
        (
            BackendConstInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                constant=BackendDoubleConst(value=9223372036854775808.0),
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
            BackendConstInst(
                inst_id=_inst_id(2),
                dest=_reg_id(2),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(2),
        register_type_names={0: TYPE_NAME_DOUBLE, 1: TYPE_NAME_I64, 2: TYPE_NAME_I64},
    )

    optimized = dead_pure_definition_elimination(program)
    verify_backend_program(optimized)

    callable_decl = optimized.callables[0]
    assert tuple(instruction.inst_id.ordinal for instruction in callable_decl.blocks[0].instructions) == (0, 1, 2)
    assert tuple(register.reg_id.ordinal for register in callable_decl.registers) == (0, 1, 2)


def test_optimize_backend_ir_program_reports_pass_statistics(capsys) -> None:
    from compiler.common.logging import configure_logging, resolve_log_settings

    configure_logging(resolve_log_settings("debug", verbose=2, quiet=0))
    program = _program_with_instructions(
        (
            BackendConstInst(
                inst_id=_inst_id(0),
                dest=_reg_id(0),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                span=make_source_span(),
            ),
            BackendConstInst(
                inst_id=_inst_id(1),
                dest=_reg_id(1),
                constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                span=make_source_span(),
            ),
        ),
        return_reg_id=_reg_id(1),
        register_ordinals=(0, 1),
    )

    optimize_backend_ir_program(program)
    captured = capsys.readouterr()

    assert (
        "nifc: debug: Backend optimization pass dead_pure_definition_elimination removed 1 instructions, "
        "1 registers across 1 callables"
    ) in captured.err
    assert "nifc: debug: Backend optimization pass dead_pure_definition_elimination completed in" in captured.err
    assert "nifc: debug: Backend optimization pass trivial_copy_elimination removed " in captured.err
    assert "nifc: debug: Backend optimization pass trivial_copy_elimination completed in" in captured.err
    assert "nifc: debug: Backend optimization pass constant_fold folded " in captured.err
    assert "nifc: debug: Backend optimization pass constant_fold completed in" in captured.err
    assert "nifc: debug: Backend optimization pass simplify_cfg removed " in captured.err
    assert "nifc: debug: Backend optimization pass simplify_cfg completed in" in captured.err


def _program_with_instructions(
    instructions,
    *,
    return_reg_id: BackendRegId,
    register_ordinals: tuple[int, ...] = (0, 1, 2, 3),
    register_type_names: dict[int, str] | None = None,
) -> BackendProgram:
    span = make_source_span()
    resolved_register_type_names = {} if register_type_names is None else register_type_names
    registers = tuple(
        BackendRegister(
            reg_id=_reg_id(ordinal),
            type_ref=semantic_primitive_type_ref(resolved_register_type_names.get(ordinal, TYPE_NAME_I64)),
            debug_name=f"r{ordinal}",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        )
        for ordinal in register_ordinals
    )
    callable_decl = BackendCallableDecl(
        callable_id=CALLABLE_ID,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=registers,
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
    helper_decl = replace(
        callable_decl,
        callable_id=HELPER_ID,
        is_extern=True,
        registers=(),
        entry_block_id=None,
        blocks=(),
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=CALLABLE_ID,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl, helper_decl),
    )


def _reg_id(ordinal: int) -> BackendRegId:
    return BackendRegId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _block_id(ordinal: int) -> BackendBlockId:
    return BackendBlockId(owner_id=CALLABLE_ID, ordinal=ordinal)


def _inst_id(ordinal: int) -> BackendInstId:
    return BackendInstId(owner_id=CALLABLE_ID, ordinal=ordinal)
