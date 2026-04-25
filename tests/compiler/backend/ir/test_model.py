from __future__ import annotations

import compiler.backend.ir as backend_ir

import pytest

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendCallableDecl,
    BackendDataBlob,
    BackendDataId,
    BackendInstId,
    BackendIntConst,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId
from compiler.semantic.types import semantic_primitive_type_ref, semantic_type_ref_for_class_id
from tests.compiler.backend.ir.helpers import (
    FIXTURE_CLASS_ID,
    FIXTURE_CONSTRUCTOR_ID,
    FIXTURE_ENTRY_FUNCTION_ID,
    FIXTURE_METHOD_ID,
    callable_by_id,
    make_source_span,
    one_constructor_backend_program,
    one_function_backend_program,
    one_method_backend_program,
    representative_direct_call_instruction,
    representative_runtime_call_instruction,
)


def test_one_function_backend_program_builds_representative_function() -> None:
    program = one_function_backend_program()

    assert program == one_function_backend_program()
    assert program.schema_version == BACKEND_IR_SCHEMA_VERSION
    assert program.entry_callable_id == FIXTURE_ENTRY_FUNCTION_ID
    assert program.classes == ()

    callable_decl = program.callables[0]
    block = callable_decl.blocks[0]

    assert callable_decl.kind == "function"
    assert callable_decl.signature == BackendSignature(
        param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)
    )
    assert callable_decl.param_regs == ()
    assert callable_decl.receiver_reg is None
    assert callable_decl.entry_block_id == BackendBlockId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=0)
    assert block.debug_name == "entry"
    assert isinstance(block.terminator, BackendReturnTerminator)


def test_one_method_backend_program_builds_representative_method() -> None:
    program = one_method_backend_program()
    method_callable = callable_by_id(program, FIXTURE_METHOD_ID)

    assert program.entry_callable_id == FIXTURE_ENTRY_FUNCTION_ID
    assert program.classes[0].class_id == FIXTURE_CLASS_ID
    assert program.classes[0].methods == (FIXTURE_METHOD_ID,)
    assert method_callable.kind == "method"
    assert method_callable.receiver_reg == BackendRegId(owner_id=FIXTURE_METHOD_ID, ordinal=0)
    assert method_callable.param_regs == (BackendRegId(owner_id=FIXTURE_METHOD_ID, ordinal=1),)
    assert method_callable.signature == BackendSignature(
        param_types=(semantic_primitive_type_ref(TYPE_NAME_I64),),
        return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
    )


def test_one_constructor_backend_program_builds_receiver_return_convention() -> None:
    program = one_constructor_backend_program()
    constructor_callable = callable_by_id(program, FIXTURE_CONSTRUCTOR_ID)
    constructor_block = constructor_callable.blocks[0]

    assert program.classes[0].constructors == (FIXTURE_CONSTRUCTOR_ID,)
    assert constructor_callable.kind == "constructor"
    assert constructor_callable.receiver_reg == BackendRegId(owner_id=FIXTURE_CONSTRUCTOR_ID, ordinal=0)
    assert constructor_callable.param_regs == (BackendRegId(owner_id=FIXTURE_CONSTRUCTOR_ID, ordinal=1),)
    assert constructor_callable.signature.return_type == semantic_type_ref_for_class_id(FIXTURE_CLASS_ID)
    assert constructor_block.terminator == BackendReturnTerminator(
        span=make_source_span(path="fixtures/constructor.nif", start_offset=64, end_offset=84, start_column=3),
        value=BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_CONSTRUCTOR_ID, ordinal=0)),
    )


def test_fixture_helpers_produce_stable_spans_and_call_instructions() -> None:
    span = make_source_span(path="fixtures/stable.nif", start_offset=5, end_offset=9, start_column=4)
    direct_call = representative_direct_call_instruction()
    runtime_call = representative_runtime_call_instruction()

    assert span == make_source_span(path="fixtures/stable.nif", start_offset=5, end_offset=9, start_column=4)
    assert direct_call.inst_id == BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1)
    assert runtime_call.inst_id == BackendInstId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=2)
    assert direct_call.target.callable_id == FunctionId(module_path=("fixture", "backend_ir"), name="helper")
    assert runtime_call.target.name == "rt_array_len"
    assert runtime_call.target.ref_arg_indices == (0,)


def test_model_keeps_cross_node_constructor_validation_for_verifier() -> None:
    constructor_id = ConstructorId(module_path=("fixture",), class_name="LooseCtor")
    class_id = ClassId(module_path=("fixture",), name="LooseCtor")
    receiver_type_ref = semantic_type_ref_for_class_id(class_id)
    receiver_reg_id = BackendRegId(owner_id=constructor_id, ordinal=0)
    span = make_source_span(path="fixtures/loose_ctor.nif")

    callable_decl = BackendCallableDecl(
        callable_id=constructor_id,
        kind="constructor",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=False,
        is_private=False,
        registers=(
            BackendRegister(
                reg_id=receiver_reg_id,
                type_ref=receiver_type_ref,
                debug_name="self",
                origin_kind="receiver",
                semantic_local_id=None,
                span=span,
            ),
        ),
        param_regs=(),
        receiver_reg=receiver_reg_id,
        entry_block_id=BackendBlockId(owner_id=constructor_id, ordinal=0),
        blocks=(
            BackendBlock(
                block_id=BackendBlockId(owner_id=constructor_id, ordinal=0),
                debug_name="entry",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=receiver_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )

    assert callable_decl.signature.return_type == semantic_primitive_type_ref(TYPE_NAME_I64)


def test_model_rejects_obviously_invalid_local_shapes() -> None:
    with pytest.raises(ValueError, match="BackendRegId ordinal must be non-negative"):
        BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=-1)

    with pytest.raises(ValueError, match="Backend data blob alignment must be a positive power of two"):
        BackendDataBlob(
            data_id=BackendDataId(ordinal=0),
            debug_name="bad",
            alignment=3,
            bytes_hex="00",
            readonly=True,
        )


def test_backend_ir_public_surface_is_curated() -> None:
    public_names = set(backend_ir.__all__)

    assert {"BACKEND_IR_SCHEMA_VERSION", "BackendProgram", "BackendCallInst", "BackendTrapTerminator"} <= public_names
    assert {"Literal", "dataclass", "_validate_alignment", "model"}.isdisjoint(public_names)