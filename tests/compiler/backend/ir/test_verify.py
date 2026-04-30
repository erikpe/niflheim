from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.backend.ir import (
    BackendBinaryInst,
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendBoolConst,
    BackendBranchTerminator,
    BackendCallInst,
    BackendClassDecl,
    BackendConstOperand,
    BackendConstInst,
    BackendCopyInst,
    BackendDirectCallTarget,
    BackendEffects,
    BackendFieldLoadInst,
    BackendInstId,
    BackendIntConst,
    BackendJumpTerminator,
    BackendNullConst,
    BackendNullCheckInst,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendRuntimeCallTarget,
    BackendSignature,
)
from compiler.backend.ir.verify import BackendIRVerificationError, verify_backend_program
from compiler.codegen.abi.runtime import ARRAY_LEN_RUNTIME_CALL
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_OBJ, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, SemanticBinaryOp
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import SemanticTypeRef, semantic_primitive_type_ref, semantic_type_ref_for_class_id
from tests.compiler.backend.ir.helpers import (
    FIXTURE_CLASS_ID,
    FIXTURE_CONSTRUCTOR_ID,
    FIXTURE_ENTRY_FUNCTION_ID,
    FIXTURE_HELPER_FUNCTION_ID,
    FIXTURE_METHOD_ID,
    callable_by_id,
    make_source_span,
    one_constructor_backend_program,
    one_function_backend_program,
    one_method_backend_program,
)


@pytest.mark.parametrize(
    "builder",
    [one_function_backend_program, one_method_backend_program, one_constructor_backend_program],
)
def test_verify_backend_program_accepts_representative_phase1_fixtures(builder) -> None:
    verify_backend_program(builder())


@pytest.mark.parametrize(
    ("builder", "mutator", "expected_message"),
    [
        (
            one_function_backend_program,
            lambda program: _replace_callable(
                program,
                FIXTURE_ENTRY_FUNCTION_ID,
                replace(
                    callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID),
                    registers=(
                        callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).registers[0],
                        replace(
                            callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).registers[0],
                            debug_name="dup0",
                        ),
                    ),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::main': duplicate register ID 'r0'",
        ),
        (
            one_function_backend_program,
            lambda program: _replace_callable(
                program,
                FIXTURE_ENTRY_FUNCTION_ID,
                replace(
                    callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID),
                    blocks=(
                        callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).blocks[0],
                        replace(
                            callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).blocks[0],
                            debug_name="dup",
                        ),
                    ),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::main': duplicate block ID 'b0'",
        ),
        (
            one_function_backend_program,
            lambda program: _replace_callable(
                program,
                FIXTURE_ENTRY_FUNCTION_ID,
                replace(
                    callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID),
                    blocks=(
                        replace(
                            callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).blocks[0],
                            instructions=(
                                callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).blocks[0].instructions[0],
                                replace(
                                    callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID).blocks[0].instructions[0],
                                    constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::main': duplicate instruction ID 'i0'",
        ),
    ],
)
def test_verify_backend_program_rejects_duplicate_register_block_and_instruction_ids(
    builder,
    mutator,
    expected_message: str,
) -> None:
    with pytest.raises(BackendIRVerificationError, match=expected_message):
        verify_backend_program(mutator(builder()))


@pytest.mark.parametrize(
    ("mutator", "expected_message"),
    [
        (
            lambda program: _replace_callable(
                program,
                FIXTURE_CONSTRUCTOR_ID,
                replace(callable_by_id(program, FIXTURE_CONSTRUCTOR_ID), receiver_reg=None),
            ),
            "Backend IR callable 'fixture.backend_ir::Box#0': constructors must declare a receiver_reg",
        ),
        (
            lambda program: _replace_callable(
                program,
                FIXTURE_CONSTRUCTOR_ID,
                replace(
                    callable_by_id(program, FIXTURE_CONSTRUCTOR_ID),
                    signature=BackendSignature(
                        param_types=callable_by_id(program, FIXTURE_CONSTRUCTOR_ID).signature.param_types,
                        return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
                    ),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::Box#0': constructor return type 'i64' must match constructed class 'Box'",
        ),
    ],
)
def test_verify_backend_program_rejects_constructor_receiver_and_return_mismatches(mutator, expected_message: str) -> None:
    with pytest.raises(BackendIRVerificationError, match=expected_message):
        verify_backend_program(mutator(one_constructor_backend_program()))


@pytest.mark.parametrize(
    ("program_builder", "expected_message"),
    [
        (
            lambda: _program_with_invalid_jump_target(),
            "Backend IR callable 'fixture.backend_ir::main' block 'b0': terminator references undeclared block 'b9'",
        ),
        (
            lambda: _program_with_non_bool_branch_condition(),
            "Backend IR callable 'fixture.backend_ir::main' block 'b0': branch condition type 'i64' must be bool",
        ),
    ],
)
def test_verify_backend_program_rejects_invalid_block_references_and_bad_branch_conditions(
    program_builder,
    expected_message: str,
) -> None:
    with pytest.raises(BackendIRVerificationError, match=expected_message):
        verify_backend_program(program_builder())


@pytest.mark.parametrize(
    ("mutator", "expected_message"),
    [
        (
            lambda program: _replace_entry_instruction(
                program,
                _runtime_call_instruction(
                    name="rt_missing_backend_helper",
                    ref_arg_indices=(0,),
                    effects=BackendEffects(reads_memory=True),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::main' block 'b0' instruction 'i1': runtime call 'rt_missing_backend_helper' is not present in the runtime metadata registry",
        ),
        (
            lambda program: _replace_entry_instruction(
                program,
                _runtime_call_instruction(
                    name=ARRAY_LEN_RUNTIME_CALL,
                    ref_arg_indices=(),
                    effects=BackendEffects(reads_memory=True),
                ),
            ),
            r"Backend IR callable 'fixture.backend_ir::main' block 'b0' instruction 'i1': runtime call 'rt_array_len' ref_arg_indices \(\) do not match runtime metadata \(0,\)",
        ),
        (
            lambda program: _replace_entry_instruction(
                program,
                _runtime_call_instruction(
                    name=ARRAY_LEN_RUNTIME_CALL,
                    ref_arg_indices=(0,),
                    effects=BackendEffects(reads_memory=True, may_gc=True),
                ),
            ),
            "Backend IR callable 'fixture.backend_ir::main' block 'b0' instruction 'i1': runtime call 'rt_array_len' effects.may_gc=True does not match runtime metadata False",
        ),
    ],
)
def test_verify_backend_program_rejects_runtime_call_metadata_mismatches(mutator, expected_message: str) -> None:
    with pytest.raises(BackendIRVerificationError, match=expected_message):
        verify_backend_program(mutator(_program_with_runtime_call_support()))


def test_verify_backend_program_rejects_field_references_to_missing_class_fields() -> None:
    program = _program_with_missing_field_load()

    with pytest.raises(
        BackendIRVerificationError,
        match="Backend IR callable 'fixture.backend_ir::Box.value' block 'b0' instruction 'i1': field 'missing' is not declared on class 'fixture.backend_ir::Box'",
    ):
        verify_backend_program(program)


def test_verify_backend_program_rejects_receiver_carrying_call_arity_mismatches() -> None:
    program = _program_with_bad_method_call_arity()

    with pytest.raises(
        BackendIRVerificationError,
        match="Backend IR callable 'fixture.backend_ir::main' block 'b0' instruction 'i1': call expects 2 arguments including receiver, got 1",
    ):
        verify_backend_program(program)


def test_verify_backend_program_accepts_loop_header_using_preheader_defined_invariant() -> None:
    verify_backend_program(_program_with_loop_header_invariant_use())


def test_verify_backend_program_accepts_identity_comparison_between_obj_and_null() -> None:
    verify_backend_program(_program_with_obj_null_identity_comparison())


def test_verify_backend_program_accepts_shift_with_u64_count_for_u8_value() -> None:
    verify_backend_program(_program_with_u8_shift_by_u64())


def _replace_callable(
    program: BackendProgram,
    target_callable_id,
    updated_callable,
) -> BackendProgram:
    return replace(
        program,
        callables=tuple(
            updated_callable if callable_decl.callable_id == target_callable_id else callable_decl
            for callable_decl in program.callables
        ),
    )


def _program_with_u8_shift_by_u64() -> BackendProgram:
    program = one_function_backend_program()
    callable_decl = callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID)
    value_reg = replace(
        callable_decl.registers[0],
        reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=0),
        type_ref=semantic_primitive_type_ref("u8"),
        debug_name="value0",
    )
    count_reg = replace(
        callable_decl.registers[0],
        reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
        type_ref=semantic_primitive_type_ref(TYPE_NAME_U64),
        debug_name="count1",
    )
    result_reg = replace(
        callable_decl.registers[0],
        reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=2),
        type_ref=semantic_primitive_type_ref("u8"),
        debug_name="result2",
    )
    span = make_source_span(path="fixtures/verify_shift_u8_u64.nif")
    updated_callable = replace(
        callable_decl,
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref("u8")),
        registers=(value_reg, count_reg, result_reg),
        blocks=(
            replace(
                callable_decl.blocks[0],
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=0),
                        dest=value_reg.reg_id,
                        constant=BackendIntConst(type_name="u8", value=1),
                        span=span,
                    ),
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
                        dest=count_reg.reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_U64, value=1),
                        span=span,
                    ),
                    BackendBinaryInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=2),
                        dest=result_reg.reg_id,
                        op=SemanticBinaryOp(kind=BinaryOpKind.SHIFT_LEFT, flavor=BinaryOpFlavor.INTEGER),
                        left=BackendRegOperand(reg_id=value_reg.reg_id),
                        right=BackendRegOperand(reg_id=count_reg.reg_id),
                        span=span,
                    ),
                ),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=result_reg.reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return _replace_callable(program, FIXTURE_ENTRY_FUNCTION_ID, updated_callable)


def _program_with_invalid_jump_target() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_cfg_invalid_target.nif")
    reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    entry_block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    exit_block_id = BackendBlockId(owner_id=callable_id, ordinal=1)
    callable_decl = replace(
        callable_by_id(one_function_backend_program(), callable_id),
        registers=(
            BackendRegister(
                reg_id=reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="ret0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        entry_block_id=entry_block_id,
        blocks=(
            BackendBlock(
                block_id=entry_block_id,
                debug_name="entry",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(
                    span=span,
                    target_block_id=BackendBlockId(owner_id=callable_id, ordinal=9),
                ),
                span=span,
            ),
            BackendBlock(
                block_id=exit_block_id,
                debug_name="exit",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return replace(one_function_backend_program(), callables=(callable_decl,))


def _program_with_non_bool_branch_condition() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_cfg_branch_condition.nif")
    reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    entry_block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    true_block_id = BackendBlockId(owner_id=callable_id, ordinal=1)
    false_block_id = BackendBlockId(owner_id=callable_id, ordinal=2)
    callable_decl = replace(
        callable_by_id(one_function_backend_program(), callable_id),
        entry_block_id=entry_block_id,
        blocks=(
            BackendBlock(
                block_id=entry_block_id,
                debug_name="entry",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                        span=span,
                    ),
                ),
                terminator=BackendBranchTerminator(
                    span=span,
                    condition=BackendRegOperand(reg_id=reg_id),
                    true_block_id=true_block_id,
                    false_block_id=false_block_id,
                ),
                span=span,
            ),
            BackendBlock(
                block_id=true_block_id,
                debug_name="then",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=reg_id)),
                span=span,
            ),
            BackendBlock(
                block_id=false_block_id,
                debug_name="else",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return replace(one_function_backend_program(), callables=(callable_decl,))


def _program_with_runtime_call_support() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_runtime_call.nif")
    array_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    result_reg_id = BackendRegId(owner_id=callable_id, ordinal=1)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    updated_callable = replace(
        callable_by_id(one_function_backend_program(), callable_id),
        signature=BackendSignature(
            param_types=(semantic_type_ref_for_class_id(FIXTURE_CLASS_ID),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_U64),
        ),
        registers=(
            BackendRegister(
                reg_id=array_reg_id,
                type_ref=semantic_type_ref_for_class_id(FIXTURE_CLASS_ID),
                debug_name="values",
                origin_kind="param",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=result_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_U64),
                debug_name="len0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        param_regs=(array_reg_id,),
        receiver_reg=None,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(
                    _runtime_call_instruction(
                        name=ARRAY_LEN_RUNTIME_CALL,
                        ref_arg_indices=(0,),
                        effects=BackendEffects(reads_memory=True),
                    ),
                ),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=result_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return replace(one_function_backend_program(), callables=(updated_callable,))


def _replace_entry_instruction(program: BackendProgram, instruction: BackendCallInst) -> BackendProgram:
    callable_decl = callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID)
    updated_callable = replace(
        callable_decl,
        blocks=(
            replace(
                callable_decl.blocks[0],
                instructions=(instruction,),
            ),
        ),
    )
    return replace(program, callables=(updated_callable,))


def _runtime_call_instruction(*, name: str, ref_arg_indices: tuple[int, ...], effects: BackendEffects) -> BackendCallInst:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_runtime_call.nif", start_offset=8, end_offset=16)
    return BackendCallInst(
        inst_id=BackendInstId(owner_id=callable_id, ordinal=1),
        dest=BackendRegId(owner_id=callable_id, ordinal=1),
        target=BackendRuntimeCallTarget(name=name, ref_arg_indices=ref_arg_indices),
        args=(BackendRegOperand(reg_id=BackendRegId(owner_id=callable_id, ordinal=0)),),
        signature=BackendSignature(
            param_types=(semantic_type_ref_for_class_id(FIXTURE_CLASS_ID),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_U64),
        ),
        effects=effects,
        span=span,
    )


def _program_with_missing_field_load() -> BackendProgram:
    program = one_method_backend_program()
    method_callable = callable_by_id(program, FIXTURE_METHOD_ID)
    span = make_source_span(path="fixtures/verify_missing_field.nif", start_offset=12, end_offset=24)
    updated_method = replace(
        method_callable,
        blocks=(
            replace(
                method_callable.blocks[0],
                instructions=(
                    BackendNullCheckInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_METHOD_ID, ordinal=0),
                        value=BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_METHOD_ID, ordinal=0)),
                        span=span,
                    ),
                    BackendFieldLoadInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_METHOD_ID, ordinal=1),
                        dest=BackendRegId(owner_id=FIXTURE_METHOD_ID, ordinal=2),
                        object_ref=BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_METHOD_ID, ordinal=0)),
                        owner_class_id=FIXTURE_CLASS_ID,
                        field_name="missing",
                        span=span,
                    ),
                ),
            ),
        ),
    )
    return _replace_callable(program, FIXTURE_METHOD_ID, updated_method)


def _program_with_bad_method_call_arity() -> BackendProgram:
    program = one_method_backend_program()
    entry_callable = callable_by_id(program, FIXTURE_ENTRY_FUNCTION_ID)
    span = make_source_span(path="fixtures/verify_bad_method_call_arity.nif", start_offset=12, end_offset=30)
    updated_entry = replace(
        entry_callable,
        registers=(
            entry_callable.registers[0],
            BackendRegister(
                reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="call0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        blocks=(
            replace(
                entry_callable.blocks[0],
                instructions=(
                    entry_callable.blocks[0].instructions[0],
                    BackendCallInst(
                        inst_id=BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
                        dest=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
                        target=BackendDirectCallTarget(callable_id=FIXTURE_METHOD_ID),
                        args=(BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=0)),),
                        signature=BackendSignature(
                            param_types=(semantic_primitive_type_ref(TYPE_NAME_I64),),
                            return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
                        ),
                        effects=BackendEffects(),
                        span=span,
                    ),
                ),
                terminator=BackendReturnTerminator(
                    span=span,
                    value=BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1)),
                ),
            ),
        ),
    )
    return _replace_callable(program, FIXTURE_ENTRY_FUNCTION_ID, updated_entry)


def _program_with_loop_header_invariant_use() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_loop_header_invariant.nif")
    limit_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    index_reg_id = BackendRegId(owner_id=callable_id, ordinal=1)
    cond_reg_id = BackendRegId(owner_id=callable_id, ordinal=2)
    next_index_reg_id = BackendRegId(owner_id=callable_id, ordinal=3)
    entry_block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    preheader_block_id = BackendBlockId(owner_id=callable_id, ordinal=1)
    cond_block_id = BackendBlockId(owner_id=callable_id, ordinal=2)
    body_block_id = BackendBlockId(owner_id=callable_id, ordinal=3)
    continue_block_id = BackendBlockId(owner_id=callable_id, ordinal=4)
    exit_block_id = BackendBlockId(owner_id=callable_id, ordinal=5)
    updated_callable = replace(
        callable_by_id(one_function_backend_program(), callable_id),
        registers=(
            BackendRegister(
                reg_id=limit_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="limit",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=index_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="index",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=cond_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
                debug_name="cond",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=next_index_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="next_index",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        param_regs=(),
        receiver_reg=None,
        entry_block_id=entry_block_id,
        blocks=(
            BackendBlock(
                block_id=entry_block_id,
                debug_name="entry",
                instructions=(),
                terminator=BackendJumpTerminator(span=span, target_block_id=preheader_block_id),
                span=span,
            ),
            BackendBlock(
                block_id=preheader_block_id,
                debug_name="loop.preheader",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=limit_reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=4),
                        span=span,
                    ),
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=1),
                        dest=index_reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(span=span, target_block_id=cond_block_id),
                span=span,
            ),
            BackendBlock(
                block_id=cond_block_id,
                debug_name="loop.cond",
                instructions=(
                    BackendBinaryInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=2),
                        dest=cond_reg_id,
                        op=SemanticBinaryOp(kind=BinaryOpKind.LESS_THAN, flavor=BinaryOpFlavor.INTEGER_COMPARISON),
                        left=BackendRegOperand(reg_id=index_reg_id),
                        right=BackendRegOperand(reg_id=limit_reg_id),
                        span=span,
                    ),
                ),
                terminator=BackendBranchTerminator(
                    span=span,
                    condition=BackendRegOperand(reg_id=cond_reg_id),
                    true_block_id=body_block_id,
                    false_block_id=exit_block_id,
                ),
                span=span,
            ),
            BackendBlock(
                block_id=body_block_id,
                debug_name="loop.body",
                instructions=(
                    BackendBinaryInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=3),
                        dest=next_index_reg_id,
                        op=SemanticBinaryOp(kind=BinaryOpKind.ADD, flavor=BinaryOpFlavor.INTEGER),
                        left=BackendRegOperand(reg_id=index_reg_id),
                        right=BackendConstOperand(constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1)),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(span=span, target_block_id=continue_block_id),
                span=span,
            ),
            BackendBlock(
                block_id=continue_block_id,
                debug_name="loop.continue",
                instructions=(
                    BackendCopyInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=4),
                        dest=index_reg_id,
                        source=BackendRegOperand(reg_id=next_index_reg_id),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(span=span, target_block_id=cond_block_id),
                span=span,
            ),
            BackendBlock(
                block_id=exit_block_id,
                debug_name="loop.exit",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=index_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return replace(one_function_backend_program(), callables=(updated_callable,))


def _program_with_obj_null_identity_comparison() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    span = make_source_span(path="fixtures/verify_obj_null_identity.nif")
    obj_type_ref = SemanticTypeRef(kind="reference", canonical_name=TYPE_NAME_OBJ, display_name=TYPE_NAME_OBJ)
    object_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    result_reg_id = BackendRegId(owner_id=callable_id, ordinal=1)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    updated_callable = replace(
        callable_by_id(one_function_backend_program(), callable_id),
        signature=BackendSignature(
            param_types=(obj_type_ref,),
            return_type=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        ),
        registers=(
            BackendRegister(
                reg_id=object_reg_id,
                type_ref=obj_type_ref,
                debug_name="value",
                origin_kind="param",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=result_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
                debug_name="is_null",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        param_regs=(object_reg_id,),
        receiver_reg=None,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(
                    BackendBinaryInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=result_reg_id,
                        op=SemanticBinaryOp(kind=BinaryOpKind.EQUAL, flavor=BinaryOpFlavor.IDENTITY_COMPARISON),
                        left=BackendRegOperand(reg_id=object_reg_id),
                        right=BackendConstOperand(constant=BackendNullConst()),
                        span=span,
                    ),
                ),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=result_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return replace(one_function_backend_program(), callables=(updated_callable,))