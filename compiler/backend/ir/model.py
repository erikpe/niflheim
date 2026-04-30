"""Core backend IR model for phase-1 backend pipeline work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.span import SourceSpan
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.operations import CastSemanticsKind, SemanticBinaryOp, SemanticUnaryOp, TypeTestSemanticsKind
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    LocalId,
    MethodId,
)
from compiler.semantic.types import SemanticTypeRef


BACKEND_IR_SCHEMA_VERSION = "niflheim.backend-ir.v1"

BackendCallableId = FunctionId | MethodId | ConstructorId
BackendCallableKind = Literal["function", "method", "constructor"]
BackendRegisterOriginKind = Literal["receiver", "param", "local", "helper", "temp", "synthetic"]
BackendIntTypeName = Literal["i64", "u64", "u8"]
BackendTrapKind = Literal["bad_cast", "bounds", "null_deref", "panic", "unreachable"]

_BACKEND_INT_TYPE_NAMES = frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8})
_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_non_negative_ordinal(kind: str, ordinal: int) -> None:
    if ordinal < 0:
        raise ValueError(f"{kind} ordinal must be non-negative")


def _validate_ref_arg_indices(ref_arg_indices: tuple[int, ...]) -> None:
    if any(index < 0 for index in ref_arg_indices):
        raise ValueError("Backend runtime call reference argument indices must be non-negative")
    if tuple(sorted(ref_arg_indices)) != ref_arg_indices:
        raise ValueError("Backend runtime call reference argument indices must be sorted")
    if len(set(ref_arg_indices)) != len(ref_arg_indices):
        raise ValueError("Backend runtime call reference argument indices must be unique")


def _validate_alignment(alignment: int) -> None:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("Backend data blob alignment must be a positive power of two")


def _validate_bytes_hex(bytes_hex: str) -> None:
    if len(bytes_hex) % 2 != 0:
        raise ValueError("Backend data blob bytes_hex must contain an even number of hexadecimal digits")
    if any(ch not in _LOWER_HEX_DIGITS for ch in bytes_hex):
        raise ValueError("Backend data blob bytes_hex must use lower-case hexadecimal digits without separators")


@dataclass(frozen=True)
class BackendRegId:
    owner_id: BackendCallableId
    ordinal: int

    def __post_init__(self) -> None:
        _validate_non_negative_ordinal("BackendRegId", self.ordinal)


@dataclass(frozen=True)
class BackendBlockId:
    owner_id: BackendCallableId
    ordinal: int

    def __post_init__(self) -> None:
        _validate_non_negative_ordinal("BackendBlockId", self.ordinal)


@dataclass(frozen=True)
class BackendInstId:
    owner_id: BackendCallableId
    ordinal: int

    def __post_init__(self) -> None:
        _validate_non_negative_ordinal("BackendInstId", self.ordinal)


@dataclass(frozen=True)
class BackendDataId:
    ordinal: int

    def __post_init__(self) -> None:
        _validate_non_negative_ordinal("BackendDataId", self.ordinal)


@dataclass(frozen=True)
class BackendDataBlob:
    data_id: BackendDataId
    debug_name: str
    alignment: int
    bytes_hex: str
    readonly: bool

    def __post_init__(self) -> None:
        _validate_alignment(self.alignment)
        _validate_bytes_hex(self.bytes_hex)


@dataclass(frozen=True)
class BackendInterfaceDecl:
    interface_id: InterfaceId
    methods: tuple[InterfaceMethodId, ...]


@dataclass(frozen=True)
class BackendFieldDecl:
    owner_class_id: ClassId
    name: str
    type_ref: SemanticTypeRef
    is_private: bool
    is_final: bool


@dataclass(frozen=True)
class BackendClassDecl:
    class_id: ClassId
    superclass_id: ClassId | None
    implemented_interfaces: tuple[InterfaceId, ...]
    fields: tuple[BackendFieldDecl, ...]
    methods: tuple[MethodId, ...]
    constructors: tuple[ConstructorId, ...]


@dataclass(frozen=True)
class BackendRegister:
    reg_id: BackendRegId
    type_ref: SemanticTypeRef
    debug_name: str
    origin_kind: BackendRegisterOriginKind
    semantic_local_id: LocalId | None
    span: SourceSpan | None


@dataclass(frozen=True)
class BackendSignature:
    param_types: tuple[SemanticTypeRef, ...]
    return_type: SemanticTypeRef | None


@dataclass(frozen=True)
class BackendProgram:
    schema_version: str
    entry_callable_id: FunctionId
    data_blobs: tuple[BackendDataBlob, ...]
    interfaces: tuple[BackendInterfaceDecl, ...]
    classes: tuple[BackendClassDecl, ...]
    callables: tuple[BackendCallableDecl, ...]


@dataclass(frozen=True)
class BackendCallableDecl:
    callable_id: BackendCallableId
    kind: BackendCallableKind
    signature: BackendSignature
    is_export: bool
    is_extern: bool
    is_static: bool | None
    is_private: bool | None
    registers: tuple[BackendRegister, ...]
    param_regs: tuple[BackendRegId, ...]
    receiver_reg: BackendRegId | None
    entry_block_id: BackendBlockId | None
    blocks: tuple[BackendBlock, ...]
    span: SourceSpan


@dataclass(frozen=True)
class BackendBlock:
    block_id: BackendBlockId
    debug_name: str
    instructions: tuple[BackendInstruction, ...]
    terminator: BackendTerminator
    span: SourceSpan


@dataclass(frozen=True)
class BackendIntConst:
    type_name: BackendIntTypeName
    value: int

    def __post_init__(self) -> None:
        if self.type_name not in _BACKEND_INT_TYPE_NAMES:
            raise ValueError(f"Unsupported backend integer constant type '{self.type_name}'")


@dataclass(frozen=True)
class BackendBoolConst:
    value: bool


@dataclass(frozen=True)
class BackendDoubleConst:
    value: float


@dataclass(frozen=True)
class BackendNullConst:
    pass


@dataclass(frozen=True)
class BackendUnitConst:
    pass


BackendConstant = BackendIntConst | BackendBoolConst | BackendDoubleConst | BackendNullConst | BackendUnitConst


@dataclass(frozen=True)
class BackendRegOperand:
    reg_id: BackendRegId


@dataclass(frozen=True)
class BackendConstOperand:
    constant: BackendConstant


@dataclass(frozen=True)
class BackendDataOperand:
    data_id: BackendDataId


@dataclass(frozen=True)
class BackendCallableOperand:
    callable_id: BackendCallableId
    type_ref: SemanticTypeRef


BackendOperand = BackendRegOperand | BackendConstOperand | BackendDataOperand | BackendCallableOperand


@dataclass(frozen=True)
class BackendEffects:
    reads_memory: bool = False
    writes_memory: bool = False
    may_gc: bool = False
    may_trap: bool = False
    is_noreturn: bool = False
    needs_safepoint_hooks: bool = False


@dataclass(frozen=True)
class BackendDirectCallTarget:
    callable_id: BackendCallableId


@dataclass(frozen=True)
class BackendRuntimeCallTarget:
    name: str
    ref_arg_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        _validate_ref_arg_indices(self.ref_arg_indices)


@dataclass(frozen=True)
class BackendIndirectCallTarget:
    callee: BackendOperand


@dataclass(frozen=True)
class BackendVirtualCallTarget:
    slot_owner_class_id: ClassId
    method_name: str
    selected_method_id: MethodId


@dataclass(frozen=True)
class BackendInterfaceCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId


BackendCallTarget = (
    BackendDirectCallTarget
    | BackendRuntimeCallTarget
    | BackendIndirectCallTarget
    | BackendVirtualCallTarget
    | BackendInterfaceCallTarget
)


@dataclass(frozen=True)
class BackendInstructionBase:
    inst_id: BackendInstId
    span: SourceSpan


@dataclass(frozen=True)
class BackendConstInst(BackendInstructionBase):
    dest: BackendRegId
    constant: BackendConstant


@dataclass(frozen=True)
class BackendCopyInst(BackendInstructionBase):
    dest: BackendRegId
    source: BackendOperand


@dataclass(frozen=True)
class BackendUnaryInst(BackendInstructionBase):
    dest: BackendRegId
    op: SemanticUnaryOp
    operand: BackendOperand


@dataclass(frozen=True)
class BackendBinaryInst(BackendInstructionBase):
    dest: BackendRegId
    op: SemanticBinaryOp
    left: BackendOperand
    right: BackendOperand


@dataclass(frozen=True)
class BackendCastInst(BackendInstructionBase):
    dest: BackendRegId
    cast_kind: CastSemanticsKind
    operand: BackendOperand
    target_type_ref: SemanticTypeRef
    trap_on_failure: bool


@dataclass(frozen=True)
class BackendTypeTestInst(BackendInstructionBase):
    dest: BackendRegId
    test_kind: TypeTestSemanticsKind
    operand: BackendOperand
    target_type_ref: SemanticTypeRef


@dataclass(frozen=True)
class BackendAllocObjectInst(BackendInstructionBase):
    dest: BackendRegId
    class_id: ClassId
    effects: BackendEffects


@dataclass(frozen=True)
class BackendFieldLoadInst(BackendInstructionBase):
    dest: BackendRegId
    object_ref: BackendOperand
    owner_class_id: ClassId
    field_name: str


@dataclass(frozen=True)
class BackendFieldStoreInst(BackendInstructionBase):
    object_ref: BackendOperand
    owner_class_id: ClassId
    field_name: str
    value: BackendOperand


@dataclass(frozen=True)
class BackendArrayAllocInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    length: BackendOperand
    effects: BackendEffects


@dataclass(frozen=True)
class BackendArrayLengthInst(BackendInstructionBase):
    dest: BackendRegId
    array_ref: BackendOperand


@dataclass(frozen=True)
class BackendArrayLoadInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    index: BackendOperand


@dataclass(frozen=True)
class BackendArrayStoreInst(BackendInstructionBase):
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    index: BackendOperand
    value: BackendOperand


@dataclass(frozen=True)
class BackendArraySliceInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    begin: BackendOperand
    end: BackendOperand
    effects: BackendEffects


@dataclass(frozen=True)
class BackendArraySliceStoreInst(BackendInstructionBase):
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    begin: BackendOperand
    end: BackendOperand
    value: BackendOperand


@dataclass(frozen=True)
class BackendNullCheckInst(BackendInstructionBase):
    value: BackendOperand


@dataclass(frozen=True)
class BackendBoundsCheckInst(BackendInstructionBase):
    array_ref: BackendOperand
    index: BackendOperand


@dataclass(frozen=True)
class BackendCallInst(BackendInstructionBase):
    dest: BackendRegId | None
    target: BackendCallTarget
    args: tuple[BackendOperand, ...]
    signature: BackendSignature
    effects: BackendEffects


BackendInstruction = (
    BackendConstInst
    | BackendCopyInst
    | BackendUnaryInst
    | BackendBinaryInst
    | BackendCastInst
    | BackendTypeTestInst
    | BackendAllocObjectInst
    | BackendFieldLoadInst
    | BackendFieldStoreInst
    | BackendArrayAllocInst
    | BackendArrayLengthInst
    | BackendArrayLoadInst
    | BackendArrayStoreInst
    | BackendArraySliceInst
    | BackendArraySliceStoreInst
    | BackendNullCheckInst
    | BackendBoundsCheckInst
    | BackendCallInst
)


@dataclass(frozen=True)
class BackendJumpTerminator:
    span: SourceSpan
    target_block_id: BackendBlockId


@dataclass(frozen=True)
class BackendBranchTerminator:
    span: SourceSpan
    condition: BackendOperand
    true_block_id: BackendBlockId
    false_block_id: BackendBlockId


@dataclass(frozen=True)
class BackendReturnTerminator:
    span: SourceSpan
    value: BackendOperand | None


@dataclass(frozen=True)
class BackendTrapTerminator:
    span: SourceSpan
    trap_kind: BackendTrapKind
    message: str | None


BackendTerminator = (
    BackendJumpTerminator | BackendBranchTerminator | BackendReturnTerminator | BackendTrapTerminator
)


@dataclass(frozen=True)
class BackendFunctionAnalysisDump:
    predecessors: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    successors: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    live_in: dict[BackendBlockId, tuple[BackendRegId, ...]]
    live_out: dict[BackendBlockId, tuple[BackendRegId, ...]]
    safepoint_live_regs: dict[BackendInstId, tuple[BackendRegId, ...]]
    root_slot_by_reg: dict[BackendRegId, int]
    stack_home_by_reg: dict[BackendRegId, str]


__all__ = [
    "BACKEND_IR_SCHEMA_VERSION",
    "BackendAllocObjectInst",
    "BackendArrayAllocInst",
    "BackendArrayLengthInst",
    "BackendArrayLoadInst",
    "BackendArraySliceInst",
    "BackendArraySliceStoreInst",
    "BackendArrayStoreInst",
    "BackendBinaryInst",
    "BackendBlock",
    "BackendBlockId",
    "BackendBoolConst",
    "BackendBoundsCheckInst",
    "BackendBranchTerminator",
    "BackendCallInst",
    "BackendCallTarget",
    "BackendCallableDecl",
    "BackendCallableId",
    "BackendCallableKind",
    "BackendCastInst",
    "BackendClassDecl",
    "BackendConstInst",
    "BackendConstOperand",
    "BackendConstant",
    "BackendCopyInst",
    "BackendDataBlob",
    "BackendDataId",
    "BackendDataOperand",
    "BackendDirectCallTarget",
    "BackendDoubleConst",
    "BackendEffects",
    "BackendFieldDecl",
    "BackendFieldLoadInst",
    "BackendFieldStoreInst",
    "BackendCallableOperand",
    "BackendFunctionAnalysisDump",
    "BackendIndirectCallTarget",
    "BackendInstId",
    "BackendInstruction",
    "BackendInstructionBase",
    "BackendIntConst",
    "BackendIntTypeName",
    "BackendInterfaceCallTarget",
    "BackendInterfaceDecl",
    "BackendJumpTerminator",
    "BackendNullCheckInst",
    "BackendNullConst",
    "BackendOperand",
    "BackendProgram",
    "BackendRegId",
    "BackendRegOperand",
    "BackendRegister",
    "BackendRegisterOriginKind",
    "BackendReturnTerminator",
    "BackendRuntimeCallTarget",
    "BackendSignature",
    "BackendTerminator",
    "BackendTrapKind",
    "BackendTrapTerminator",
    "BackendTypeTestInst",
    "BackendUnaryInst",
    "BackendUnitConst",
    "BackendVirtualCallTarget",
]