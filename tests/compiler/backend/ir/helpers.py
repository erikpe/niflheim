from __future__ import annotations

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendCallInst,
    BackendCallableDecl,
    BackendClassDecl,
    BackendConstInst,
    BackendDirectCallTarget,
    BackendEffects,
    BackendInstId,
    BackendIntConst,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendRuntimeCallTarget,
    BackendSignature,
)
from compiler.codegen.abi.runtime import ARRAY_LEN_RUNTIME_CALL
from compiler.common.span import SourcePos, SourceSpan
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, MethodId
from compiler.semantic.types import semantic_primitive_type_ref, semantic_type_ref_for_class_id


FIXTURE_MODULE_PATH = ("fixture", "backend_ir")
FIXTURE_CLASS_NAME = "Box"
FIXTURE_ENTRY_FUNCTION_ID = FunctionId(module_path=FIXTURE_MODULE_PATH, name="main")
FIXTURE_HELPER_FUNCTION_ID = FunctionId(module_path=FIXTURE_MODULE_PATH, name="helper")
FIXTURE_CLASS_ID = ClassId(module_path=FIXTURE_MODULE_PATH, name=FIXTURE_CLASS_NAME)
FIXTURE_METHOD_ID = MethodId(module_path=FIXTURE_MODULE_PATH, class_name=FIXTURE_CLASS_NAME, name="value")
FIXTURE_CONSTRUCTOR_ID = ConstructorId(module_path=FIXTURE_MODULE_PATH, class_name=FIXTURE_CLASS_NAME, ordinal=0)


def make_source_span(
    *,
    path: str = "fixtures/backend_ir.nif",
    start_offset: int = 0,
    end_offset: int = 1,
    line: int = 1,
    start_column: int = 1,
    end_column: int | None = None,
) -> SourceSpan:
    resolved_end_column = start_column + max(end_offset - start_offset, 1) if end_column is None else end_column
    return SourceSpan(
        start=SourcePos(path=path, offset=start_offset, line=line, column=start_column),
        end=SourcePos(path=path, offset=end_offset, line=line, column=resolved_end_column),
    )


def callable_by_id(program: BackendProgram, callable_id: FunctionId | MethodId | ConstructorId) -> BackendCallableDecl:
    for callable_decl in program.callables:
        if callable_decl.callable_id == callable_id:
            return callable_decl
    raise KeyError(f"Missing backend callable {callable_id}")


def representative_direct_call_instruction() -> BackendCallInst:
    owner_id = FIXTURE_ENTRY_FUNCTION_ID
    return BackendCallInst(
        inst_id=BackendInstId(owner_id=owner_id, ordinal=1),
        dest=BackendRegId(owner_id=owner_id, ordinal=1),
        target=BackendDirectCallTarget(callable_id=FIXTURE_HELPER_FUNCTION_ID),
        args=(BackendRegOperand(reg_id=BackendRegId(owner_id=owner_id, ordinal=0)),),
        signature=BackendSignature(
            param_types=(semantic_primitive_type_ref(TYPE_NAME_I64),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
        ),
        effects=BackendEffects(),
        span=make_source_span(start_offset=12, end_offset=20, start_column=13),
    )


def representative_runtime_call_instruction() -> BackendCallInst:
    owner_id = FIXTURE_ENTRY_FUNCTION_ID
    return BackendCallInst(
        inst_id=BackendInstId(owner_id=owner_id, ordinal=2),
        dest=BackendRegId(owner_id=owner_id, ordinal=2),
        target=BackendRuntimeCallTarget(name=ARRAY_LEN_RUNTIME_CALL, ref_arg_indices=(0,)),
        args=(BackendRegOperand(reg_id=BackendRegId(owner_id=owner_id, ordinal=3)),),
        signature=BackendSignature(
            param_types=(semantic_type_ref_for_class_id(FIXTURE_CLASS_ID),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_U64),
        ),
        effects=BackendEffects(reads_memory=True),
        span=make_source_span(start_offset=21, end_offset=31, start_column=22),
    )


def one_function_backend_program() -> BackendProgram:
    callable_id = FIXTURE_ENTRY_FUNCTION_ID
    temp_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    span = make_source_span(path="fixtures/function.nif")
    callable_decl = BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=(
            BackendRegister(
                reg_id=temp_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="ret0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        param_regs=(),
        receiver_reg=None,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=temp_reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
                        span=span,
                    ),
                ),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=temp_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=callable_id,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )


def one_method_backend_program() -> BackendProgram:
    entry_function = one_function_backend_program().callables[0]
    callable_id = FIXTURE_METHOD_ID
    receiver_type_ref = semantic_type_ref_for_class_id(FIXTURE_CLASS_ID)
    receiver_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    param_reg_id = BackendRegId(owner_id=callable_id, ordinal=1)
    temp_reg_id = BackendRegId(owner_id=callable_id, ordinal=2)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    span = make_source_span(path="fixtures/method.nif", start_offset=32, end_offset=48, start_column=5)
    method_callable = BackendCallableDecl(
        callable_id=callable_id,
        kind="method",
        signature=BackendSignature(
            param_types=(semantic_primitive_type_ref(TYPE_NAME_I64),),
            return_type=semantic_primitive_type_ref(TYPE_NAME_I64),
        ),
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
            BackendRegister(
                reg_id=param_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="value",
                origin_kind="param",
                semantic_local_id=None,
                span=span,
            ),
            BackendRegister(
                reg_id=temp_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="ret0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        param_regs=(param_reg_id,),
        receiver_reg=receiver_reg_id,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=temp_reg_id,
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=7),
                        span=span,
                    ),
                ),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=temp_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=FIXTURE_ENTRY_FUNCTION_ID,
        data_blobs=(),
        interfaces=(),
        classes=(
            BackendClassDecl(
                class_id=FIXTURE_CLASS_ID,
                superclass_id=None,
                implemented_interfaces=(),
                fields=(),
                methods=(FIXTURE_METHOD_ID,),
                constructors=(),
            ),
        ),
        callables=(entry_function, method_callable),
    )


def one_constructor_backend_program() -> BackendProgram:
    entry_function = one_function_backend_program().callables[0]
    callable_id = FIXTURE_CONSTRUCTOR_ID
    receiver_type_ref = semantic_type_ref_for_class_id(FIXTURE_CLASS_ID)
    receiver_reg_id = BackendRegId(owner_id=callable_id, ordinal=0)
    param_reg_id = BackendRegId(owner_id=callable_id, ordinal=1)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    span = make_source_span(path="fixtures/constructor.nif", start_offset=64, end_offset=84, start_column=3)
    constructor_callable = BackendCallableDecl(
        callable_id=callable_id,
        kind="constructor",
        signature=BackendSignature(
            param_types=(semantic_primitive_type_ref(TYPE_NAME_BOOL),),
            return_type=receiver_type_ref,
        ),
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
            BackendRegister(
                reg_id=param_reg_id,
                type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
                debug_name="flag",
                origin_kind="param",
                semantic_local_id=None,
                span=span,
            ),
        ),
        param_regs=(param_reg_id,),
        receiver_reg=receiver_reg_id,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=receiver_reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=FIXTURE_ENTRY_FUNCTION_ID,
        data_blobs=(),
        interfaces=(),
        classes=(
            BackendClassDecl(
                class_id=FIXTURE_CLASS_ID,
                superclass_id=None,
                implemented_interfaces=(),
                fields=(),
                methods=(),
                constructors=(FIXTURE_CONSTRUCTOR_ID,),
            ),
        ),
        callables=(entry_function, constructor_callable),
    )