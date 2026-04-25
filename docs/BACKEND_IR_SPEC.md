# Backend IR Specification

Status: draft.

This document defines the concrete backend IR schema for the first backend IR transition.

It is the companion document to [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md).

The transition plan explains how the compiler moves to backend IR.

This document explains what backend IR v1 is.

Its purpose is to lock down:

- the exact backend IR node families
- the exact backend IR identifier model
- the exact serialization shape expected for JSON and text dumps
- the invariants the backend IR verifier must enforce
- the layering boundary between semantic IR, backend IR, and target lowering
- the extension points reserved for later SSA conversion and later target backends

## Status Note

Backend IR v1 is the first explicit backend IR for the repository.

It is intentionally:

- CFG-based from the start
- register-based from the start
- not SSA in v1
- target-neutral in v1
- rich enough to reach feature parity with the current checked backend path

It is not intended to be a final optimized compiler IR.

## Goals

- Provide one explicit, serializable backend input between linked semantic IR and target emission.
- Represent control flow as basic blocks and explicit terminators.
- Represent computation in register-based three-address-code style.
- Reuse existing canonical semantic symbol identities instead of reintroducing string-based resolution.
- Preserve enough type and source-location information to support correctness checks, safepoint analysis, and debuggable dumps.
- Support the current checked language/runtime surface with one backend: `x86-64 SysV`.
- Leave a clean path to later SSA construction and later backends such as `aarch64`.

## Non-Goals

- Do not require SSA in v1.
- Do not encode physical registers in v1.
- Do not encode stack slots or frame offsets in core backend IR.
- Do not encode architecture-specific calling-convention locations in core backend IR.
- Do not make backend IR responsible for semantic name resolution.
- Do not add optimization-only node kinds that are not needed for parity.

## Layering Boundary

The intended ownership boundary is:

- semantic IR owns language semantics, canonical semantic IDs, and high-level structured lowering
- backend IR owns CFG, virtual registers, target-neutral execution structure, and backend analyses
- target backends own ABI lowering, target-specific legality, frame layout, physical register use, and assembly emission

The backend IR is therefore:

- lower than semantic IR
- higher than target-specific machine lowering

## Reused Shared Identities And Types

Backend IR v1 intentionally reuses the semantic layer's canonical IDs instead of introducing duplicate global symbol IDs.

### Reused Canonical Global IDs

Backend IR v1 reuses:

- `FunctionId`
- `MethodId`
- `ConstructorId`
- `ClassId`
- `InterfaceId`
- `InterfaceMethodId`
- `LocalId` only as optional debug/origin metadata

These IDs are already canonical post-typecheck identities and remain the source of truth for global symbol ownership.

### Reused Type Shape

Backend IR v1 also reuses `SemanticTypeRef` directly as its type authority.

That means backend IR values and declarations still carry canonical typed information such as:

- primitive kinds
- class identity
- interface identity
- array element type
- callable parameter and return types

This is a deliberate v1 simplification.

Backend IR is a new execution/control-flow schema, not a second independent type system.

### Backend Function-Like Owner ID

```python
BackendCallableId = FunctionId | MethodId | ConstructorId
```

Every backend-local identifier is scoped to one `BackendCallableId`.

## Backend-Local Identifier Model

Backend IR v1 adds new local identifiers for registers, blocks, instructions, and data blobs.

### Local Backend IDs

```python
@dataclass(frozen=True)
class BackendRegId:
    owner_id: BackendCallableId
    ordinal: int


@dataclass(frozen=True)
class BackendBlockId:
    owner_id: BackendCallableId
    ordinal: int


@dataclass(frozen=True)
class BackendInstId:
    owner_id: BackendCallableId
    ordinal: int


@dataclass(frozen=True)
class BackendDataId:
    ordinal: int
```

Rules:

- register ordinals are unique within a single function-like owner
- block ordinals are unique within a single function-like owner
- instruction ordinals are unique within a single function-like owner
- data blob ordinals are unique within the backend program

These IDs must be deterministic for the same input program and lowering configuration.

## Exact Backend IR Node Set

Backend IR v1 has two major layers:

- program/global context
- function-local CFG IR

## Program And Global Context Nodes

### Backend Program

```python
@dataclass(frozen=True)
class BackendProgram:
    schema_version: str
    entry_callable_id: FunctionId
    data_blobs: tuple[BackendDataBlob, ...]
    interfaces: tuple[BackendInterfaceDecl, ...]
    classes: tuple[BackendClassDecl, ...]
    callables: tuple[BackendCallableDecl, ...]
```

Rules:

- `schema_version` must be exactly `"niflheim.backend-ir.v1"` for the initial format
- `entry_callable_id` must refer to a callable present in `callables`
- `callables` is the full backend input set for all functions, methods, and constructors, including extern declarations
- `interfaces` and `classes` carry the program-global nominal information needed by backend lowering and metadata preparation

### Data Blobs

```python
@dataclass(frozen=True)
class BackendDataBlob:
    data_id: BackendDataId
    debug_name: str
    alignment: int
    bytes_hex: str
    readonly: bool
```

Rules:

- `bytes_hex` is lower-case hexadecimal without separators
- `alignment` must be a positive power of two
- `readonly` is normally `True` in v1

V1 primarily uses data blobs for byte-string payloads and similar constant data.

### Interface Declarations

```python
@dataclass(frozen=True)
class BackendInterfaceDecl:
    interface_id: InterfaceId
    methods: tuple[InterfaceMethodId, ...]
```

### Field Declaration

```python
@dataclass(frozen=True)
class BackendFieldDecl:
    owner_class_id: ClassId
    name: str
    type_ref: SemanticTypeRef
    is_private: bool
    is_final: bool
```

### Class Declaration

```python
@dataclass(frozen=True)
class BackendClassDecl:
    class_id: ClassId
    superclass_id: ClassId | None
    implemented_interfaces: tuple[InterfaceId, ...]
    fields: tuple[BackendFieldDecl, ...]
    methods: tuple[MethodId, ...]
    constructors: tuple[ConstructorId, ...]
```

These class and interface declarations are target-neutral.

They intentionally do not include:

- field offsets
- vtable slot indices
- interface slot indices
- target symbols

Those are backend-program analyses or target-lowering products, not core IR schema.

## Callable And Function-Local Nodes

### Callable Kind

```python
BackendCallableKind = Literal["function", "method", "constructor"]
```

### Register Origin Kind

```python
BackendRegisterOriginKind = Literal[
    "receiver",
    "param",
    "local",
    "helper",
    "temp",
    "synthetic",
]
```

### Register Declaration

```python
@dataclass(frozen=True)
class BackendRegister:
    reg_id: BackendRegId
    type_ref: SemanticTypeRef
    debug_name: str
    origin_kind: BackendRegisterOriginKind
    semantic_local_id: LocalId | None
    span: SourceSpan | None
```

Rules:

- registers are declared once per function-like owner
- register declarations describe storage-like virtual registers, not SSA values
- the same register may be assigned multiple times in v1
- `semantic_local_id` is optional and used only for source/debug mapping

### Callable Signature

```python
@dataclass(frozen=True)
class BackendSignature:
    param_types: tuple[SemanticTypeRef, ...]
    return_type: SemanticTypeRef | None
```

Rules:

- `param_types` lists only explicit logical/source parameters and never includes the receiver
- `return_type` is `None` only for unit-returning functions or methods
- constructors must always use a non-`None` `return_type`

### Callable Declaration

```python
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
```

Rules:

- `param_regs` are ordered ABI/logical parameters in source order
- `receiver_reg` is set only for instance methods and constructors
- `receiver_reg`, when present, is not repeated inside `param_regs`
- `entry_block_id` is `None` only for extern declarations with no body
- non-extern bodies must have at least one block and a valid `entry_block_id`

### Receiver Convention

Backend IR v1 treats the receiver as a distinguished input rather than as part of
`param_regs` or `BackendSignature.param_types`.

Rules:

- for instance methods and constructors, `param_regs` and `signature.param_types` exclude the receiver
- receiver-carrying calls place the receiver operand in `args[0]`
- receiver-carrying calls are non-static direct method calls, constructor calls, virtual calls, interface calls, and any indirect call already lowered from such a shape
- for receiver-carrying calls, `args[1:]` are checked against `signature.param_types`; `args[0]` is checked against the receiver type

### Constructor Callable Semantics

Backend IR v1 models exactly one logical constructor callable per `ConstructorId`.

It does not model separate wrapper and init-helper callables in the core IR schema.

Rules:

- a constructor callable is init-style: `receiver_reg` is present and live on entry and denotes the object being initialized
- `param_regs` for constructors list only declared constructor parameters and never the receiver
- `signature.return_type` for a constructor must equal the semantic type of `receiver_reg` and the class named by `callable_id`
- constructor bodies must return the initialized receiver explicitly in backend IR even if the source constructor syntax omits a return
- source-level object construction lowers to `alloc_object` followed by a direct constructor call using the receiver convention
- target backends may introduce wrapper or init-helper symbols below backend IR, but those are not backend IR callables

### Basic Block

```python
@dataclass(frozen=True)
class BackendBlock:
    block_id: BackendBlockId
    debug_name: str
    instructions: tuple[BackendInstruction, ...]
    terminator: BackendTerminator
    span: SourceSpan
```

Rules:

- every block must end with exactly one terminator
- non-terminator instructions live only in `instructions`
- blocks may be empty except for their terminator

## Operand And Constant Nodes

### Constants

```python
@dataclass(frozen=True)
class BackendIntConst:
    type_name: Literal["i64", "u64", "u8"]
    value: int


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


BackendConstant = (
    BackendIntConst
    | BackendBoolConst
    | BackendDoubleConst
    | BackendNullConst
    | BackendUnitConst
)
```

Rules:

- `BackendDoubleConst.value` is an in-memory IEEE-754 binary64 value
- canonical JSON never serializes double constants as bare JSON numbers; it serializes the raw binary64 bits instead

### Operands

```python
@dataclass(frozen=True)
class BackendRegOperand:
    reg_id: BackendRegId


@dataclass(frozen=True)
class BackendConstOperand:
    constant: BackendConstant


@dataclass(frozen=True)
class BackendDataOperand:
    data_id: BackendDataId


BackendOperand = BackendRegOperand | BackendConstOperand | BackendDataOperand
```

Rules:

- every non-terminator source operand is one of these three operand families in v1
- direct call targets are not operands; they are part of call-target nodes
- block references are not operands; they are part of terminator nodes

## Call Targets And Effects

### Effects

```python
@dataclass(frozen=True)
class BackendEffects:
    reads_memory: bool = False
    writes_memory: bool = False
    may_gc: bool = False
    may_trap: bool = False
    is_noreturn: bool = False
    needs_safepoint_hooks: bool = False
```

Rules:

- effect summaries are conservative
- if `may_gc` is `True`, the instruction is a safepoint for root-liveness purposes
- `needs_safepoint_hooks` is a target/runtime emission policy hint and may differ from `may_gc`
- `is_noreturn` instructions must appear only where control does not continue in the same block

### Direct Call Target

```python
@dataclass(frozen=True)
class BackendDirectCallTarget:
    callable_id: BackendCallableId
```

### Runtime Call Target

```python
@dataclass(frozen=True)
class BackendRuntimeCallTarget:
    name: str
    ref_arg_indices: tuple[int, ...]
```

This is the backend IR projection of the repository runtime-call metadata surface.

Rules:

- `name` must identify an entry in the repository runtime-call metadata registry
- `ref_arg_indices` is a serialized copy of the registry metadata so backend IR dumps remain self-contained
- backend lowering may not invent ad hoc runtime call names in v1

### Indirect Call Target

```python
@dataclass(frozen=True)
class BackendIndirectCallTarget:
    callee: BackendOperand
```

### Virtual Call Target

```python
@dataclass(frozen=True)
class BackendVirtualCallTarget:
    slot_owner_class_id: ClassId
    method_name: str
    selected_method_id: MethodId
```

### Interface Call Target

```python
@dataclass(frozen=True)
class BackendInterfaceCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
```

### Call Target Union

```python
BackendCallTarget = (
    BackendDirectCallTarget
    | BackendRuntimeCallTarget
    | BackendIndirectCallTarget
    | BackendVirtualCallTarget
    | BackendInterfaceCallTarget
)
```

Rules:

- method-style calls place the receiver in `args[0]`
- constructor calls also place the receiver in `args[0]`
- runtime call targets must carry the reference argument indices needed by safepoint/root analyses

### Runtime Call Ownership

The repository runtime-call metadata registry is the authoritative source for
runtime-call identity plus the GC/safepoint fields already modeled there.

In phase 1, that authority may remain implemented in the current runtime metadata
module and move later without changing the backend IR contract.

Rules:

- backend lowering may emit `BackendRuntimeCallTarget` only for names present in the registry
- the verifier must cross-check `target.ref_arg_indices` against the registry entry for `target.name`
- for `BackendCallInst` with `BackendRuntimeCallTarget`, `effects.may_gc` and `effects.needs_safepoint_hooks` must match the registry entry
- `effects.reads_memory`, `effects.writes_memory`, `effects.may_trap`, and `effects.is_noreturn` may remain conservative IR annotations in v1 until the registry grows corresponding fields

## Exact Instruction Node Set

Every non-terminator instruction has the common shape:

```python
@dataclass(frozen=True)
class BackendInstructionBase:
    inst_id: BackendInstId
    span: SourceSpan
```

The exact v1 instruction families are below.

### Constant Materialization

```python
@dataclass(frozen=True)
class BackendConstInst(BackendInstructionBase):
    dest: BackendRegId
    constant: BackendConstant
```

### Copy

```python
@dataclass(frozen=True)
class BackendCopyInst(BackendInstructionBase):
    dest: BackendRegId
    source: BackendOperand
```

### Unary Operation

```python
@dataclass(frozen=True)
class BackendUnaryInst(BackendInstructionBase):
    dest: BackendRegId
    op: SemanticUnaryOp
    operand: BackendOperand
```

### Binary Operation

```python
@dataclass(frozen=True)
class BackendBinaryInst(BackendInstructionBase):
    dest: BackendRegId
    op: SemanticBinaryOp
    left: BackendOperand
    right: BackendOperand
```

### Cast

```python
@dataclass(frozen=True)
class BackendCastInst(BackendInstructionBase):
    dest: BackendRegId
    cast_kind: CastSemanticsKind
    operand: BackendOperand
    target_type_ref: SemanticTypeRef
    trap_on_failure: bool
```

Rules:

- `trap_on_failure` is `True` for checked casts and `False` for non-trapping conversions
- backend lowering must make the trap behavior explicit; it must not be implicit in text comments or target-only code paths

### Type Test

```python
@dataclass(frozen=True)
class BackendTypeTestInst(BackendInstructionBase):
    dest: BackendRegId
    test_kind: TypeTestSemanticsKind
    operand: BackendOperand
    target_type_ref: SemanticTypeRef
```

### Object Allocation

```python
@dataclass(frozen=True)
class BackendAllocObjectInst(BackendInstructionBase):
    dest: BackendRegId
    class_id: ClassId
    effects: BackendEffects
```

Rules:

- v1 object allocation remains a high-level backend op rather than an already-lowered runtime symbol call
- the `x86-64 SysV` backend lowers this op to the current runtime allocation protocol

### Field Load

```python
@dataclass(frozen=True)
class BackendFieldLoadInst(BackendInstructionBase):
    dest: BackendRegId
    object_ref: BackendOperand
    owner_class_id: ClassId
    field_name: str
```

### Field Store

```python
@dataclass(frozen=True)
class BackendFieldStoreInst(BackendInstructionBase):
    object_ref: BackendOperand
    owner_class_id: ClassId
    field_name: str
    value: BackendOperand
```

Rules:

- field loads/stores do not imply a null check
- required null checks must already be explicit in surrounding instructions

### Array Allocation

```python
@dataclass(frozen=True)
class BackendArrayAllocInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    length: BackendOperand
    effects: BackendEffects
```

### Array Length

```python
@dataclass(frozen=True)
class BackendArrayLengthInst(BackendInstructionBase):
    dest: BackendRegId
    array_ref: BackendOperand
```

### Array Load

```python
@dataclass(frozen=True)
class BackendArrayLoadInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    index: BackendOperand
```

### Array Store

```python
@dataclass(frozen=True)
class BackendArrayStoreInst(BackendInstructionBase):
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    index: BackendOperand
    value: BackendOperand
```

### Array Slice

```python
@dataclass(frozen=True)
class BackendArraySliceInst(BackendInstructionBase):
    dest: BackendRegId
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    begin: BackendOperand
    end: BackendOperand
    effects: BackendEffects
```

### Array Slice Store

```python
@dataclass(frozen=True)
class BackendArraySliceStoreInst(BackendInstructionBase):
    array_runtime_kind: ArrayRuntimeKind
    array_ref: BackendOperand
    begin: BackendOperand
    end: BackendOperand
    value: BackendOperand
```

Rules:

- direct array ops are only for cases where backend lowering already knows the operation is a direct array fast path
- generic collection protocol operations remain calls
- direct array ops do not imply null or bounds checks; checks stay explicit

### Null Check

```python
@dataclass(frozen=True)
class BackendNullCheckInst(BackendInstructionBase):
    value: BackendOperand
```

### Bounds Check

```python
@dataclass(frozen=True)
class BackendBoundsCheckInst(BackendInstructionBase):
    array_ref: BackendOperand
    index: BackendOperand
```

Rules:

- these instructions produce no value
- they trap on failure and fall through on success
- they are the required explicit safety boundary for direct memory-style field/array ops in v1

### Call

```python
@dataclass(frozen=True)
class BackendCallInst(BackendInstructionBase):
    dest: BackendRegId | None
    target: BackendCallTarget
    args: tuple[BackendOperand, ...]
    signature: BackendSignature
    effects: BackendEffects
```

Rules:

- `dest` is `None` only for unit-returning calls
- direct, indirect, virtual, interface, and runtime calls all use this same instruction family
- the target variant and effect summary together must be enough for safepoint and call-lowering decisions

## Exact Terminator Node Set

### Jump Terminator

```python
@dataclass(frozen=True)
class BackendJumpTerminator:
    span: SourceSpan
    target_block_id: BackendBlockId
```

### Branch Terminator

```python
@dataclass(frozen=True)
class BackendBranchTerminator:
    span: SourceSpan
    condition: BackendOperand
    true_block_id: BackendBlockId
    false_block_id: BackendBlockId
```

Rules:

- `condition` must be boolean-typed
- `true_block_id` and `false_block_id` must differ

### Return Terminator

```python
@dataclass(frozen=True)
class BackendReturnTerminator:
    span: SourceSpan
    value: BackendOperand | None
```

Rules:

- `value` is `None` only for unit-returning callables

### Trap Terminator

```python
BackendTrapKind = Literal[
    "bad_cast",
    "bounds",
    "null_deref",
    "panic",
    "unreachable",
]


@dataclass(frozen=True)
class BackendTrapTerminator:
    span: SourceSpan
    trap_kind: BackendTrapKind
    message: str | None
```

The trap terminator exists for blocks that do not return to normal control flow.

### Terminator Union

```python
BackendTerminator = (
    BackendJumpTerminator
    | BackendBranchTerminator
    | BackendReturnTerminator
    | BackendTrapTerminator
)
```

## Core IR Union

```python
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
```

## Optional Serialized Analysis Sections

The canonical backend IR object above is the core program schema.

For debugging and tests, dumps may optionally include derived analysis sections.

These analysis sections must be optional and must never be required to deserialize or verify the core IR.

### Optional Function Analysis Dump

```python
@dataclass(frozen=True)
class BackendFunctionAnalysisDump:
    predecessors: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    successors: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    live_in: dict[BackendBlockId, tuple[BackendRegId, ...]]
    live_out: dict[BackendBlockId, tuple[BackendRegId, ...]]
    safepoint_live_regs: dict[BackendInstId, tuple[BackendRegId, ...]]
    root_slot_by_reg: dict[BackendRegId, int]
    stack_home_by_reg: dict[BackendRegId, str]
```

These sections are dump/debug artifacts, not core IR nodes.

## JSON Serialization Contract

The canonical JSON format must be deterministic.

### Top-Level JSON Shape

```json
{
  "schema_version": "niflheim.backend-ir.v1",
  "entry_callable_id": { "kind": "function", "module_path": ["main"], "name": "main" },
  "data_blobs": [],
  "interfaces": [],
  "classes": [],
  "callables": []
}
```

### Canonical Global ID JSON Shapes

Function ID:

```json
{ "kind": "function", "module_path": ["main"], "name": "main" }
```

Method ID:

```json
{ "kind": "method", "module_path": ["std", "vec"], "class_name": "Vec", "name": "push" }
```

Constructor ID:

```json
{ "kind": "constructor", "module_path": ["std", "box"], "class_name": "BoxI64", "ordinal": 0 }
```

Class ID:

```json
{ "kind": "class", "module_path": ["std", "box"], "name": "BoxI64" }
```

Interface ID:

```json
{ "kind": "interface", "module_path": ["std", "iter"], "name": "Iterable" }
```

### Function-Local ID JSON Shapes

Within a callable JSON object, local backend IDs are serialized as short strings:

- registers: `"r0"`, `"r1"`, ...
- blocks: `"b0"`, `"b1"`, ...
- instructions: `"i0"`, `"i1"`, ...

Program-global data blob IDs are serialized as short strings:

- data blobs: `"d0"`, `"d1"`, ...

These strings are only short encodings of the canonical ordinal IDs.

### Source Position JSON Shape

```json
{ "path": "samples/factorial.nif", "offset": 0, "line": 1, "column": 1 }
```

Rules:

- `path` uses `/` separators in canonical JSON
- canonical JSON uses a project-root-relative `path` when the source file lies under the active project root
- synthetic or non-filesystem paths such as `"<memory>"` are preserved verbatim
- `offset` is the existing zero-based `SourcePos.offset`
- `line` and `column` are the existing one-based `SourcePos` fields

### Source Span JSON Shape

```json
{
    "start": { "path": "samples/factorial.nif", "offset": 0, "line": 1, "column": 1 },
    "end": { "path": "samples/factorial.nif", "offset": 8, "line": 1, "column": 9 }
}
```

Rules:

- canonical JSON preserves the repository's in-memory `SourceSpan` values exactly; it does not renumber or reinterpret them
- for frontend-produced spans, this preserves the current start-at-token and end-after-token convention
- optional span fields use `null`; required span fields must never use `null`

### Register JSON Shape

```json
{
  "id": "r0",
  "type": { "kind": "primitive", "canonical_name": "i64", "display_name": "i64" },
  "debug_name": "n",
  "origin_kind": "param",
  "semantic_local_id": {
    "owner": { "kind": "function", "module_path": ["main"], "name": "main" },
    "ordinal": 0
  },
  "span": null
}
```

### Constant JSON Shapes

Integer constant:

```json
{ "kind": "i64", "value": 0 }
```

Boolean constant:

```json
{ "kind": "bool", "value": true }
```

Double constant:

```json
{ "kind": "double", "bits_hex": "3ff0000000000000" }
```

Null and unit constants:

```json
{ "kind": "null" }
{ "kind": "unit" }
```

Rules:

- integer constants serialize with JSON numeric `value` fields
- boolean constants serialize with JSON boolean `value` fields
- double constants serialize with exactly 16 lower-case hexadecimal digits in `bits_hex`, encoding the raw IEEE-754 binary64 bits
- canonical JSON never emits a double constant as a bare JSON number
- raw-bit encoding is required so dumps preserve signed zero, infinities, and NaN payloads exactly
- null and unit constants carry only their `kind` discriminator

### Block JSON Shape

This example uses fully expanded canonical span objects.

```json
{
    "id": "b0",
    "debug_name": "entry",
    "instructions": [
        {
            "id": "i0",
            "kind": "const",
            "dest": "r1",
            "constant": { "kind": "i64", "value": 0 },
            "span": {
                "start": { "path": "samples/factorial.nif", "offset": 0, "line": 1, "column": 1 },
                "end": { "path": "samples/factorial.nif", "offset": 8, "line": 1, "column": 9 }
            }
        }
    ],
    "terminator": {
        "kind": "return",
        "value": { "kind": "reg", "reg_id": "r1" },
        "span": {
            "start": { "path": "samples/factorial.nif", "offset": 9, "line": 1, "column": 10 },
            "end": { "path": "samples/factorial.nif", "offset": 17, "line": 1, "column": 18 }
        }
    },
    "span": {
        "start": { "path": "samples/factorial.nif", "offset": 0, "line": 1, "column": 1 },
        "end": { "path": "samples/factorial.nif", "offset": 17, "line": 1, "column": 18 }
    }
}
```

### Instruction JSON Discriminator

Every instruction JSON object must carry:

- `id`
- `kind`
- instruction-specific fields
- `span`

The `kind` discriminator values in v1 are:

- `const`
- `copy`
- `unary`
- `binary`
- `cast`
- `type_test`
- `alloc_object`
- `field_load`
- `field_store`
- `array_alloc`
- `array_len`
- `array_load`
- `array_store`
- `array_slice`
- `array_slice_store`
- `null_check`
- `bounds_check`
- `call`

### Deterministic Ordering Rules

JSON serialization must preserve this order:

1. data blobs by ordinal
2. interfaces by canonical ID sort order
3. classes by canonical ID sort order
4. callables by canonical ID sort order
5. registers by ordinal
6. blocks by ordinal
7. instructions in block order

## Text Dump Contract

The text dump is for humans and snapshot-style tests.

It must also be deterministic.

Recommended v1 text shape:

```text
func main::main(r0: i64) -> i64 {
  regs:
    r0 param n: i64
    r1 temp tmp0: i64

  b0 entry:
    i0 r1 = const.i64 0
    ret r1
}
```

Method and constructor examples:

```text
method std.vec::Vec.push(receiver=r0: std.vec::Vec, r1: Obj) -> Unit { ... }
constructor std.box::BoxI64#0(receiver=r0: std.box::BoxI64, r1: i64) -> std.box::BoxI64 { ... }
```

Rules:

- text dumps use short local IDs only inside one callable body
- type names use canonical semantic display names
- blocks and instructions are printed in deterministic order
- optional analysis sections, when present, are clearly separated from the core IR text

## Verifier Invariants

The backend IR verifier must reject malformed IR before target lowering.

At minimum it must check all of the following.

### Program-Level Invariants

1. `schema_version` is supported.
2. `entry_callable_id` exists and names a function declaration, not a method or constructor.
3. class and interface IDs are unique.
4. callable IDs are unique.
5. data blob IDs are unique.

### Callable-Level Invariants

1. register IDs are unique.
2. block IDs are unique.
3. instruction IDs are unique.
4. `entry_block_id` is present for non-extern callables.
5. extern callables have no blocks.
6. non-extern callables have at least one block.
7. `param_regs` refer only to declared registers.
8. `receiver_reg`, when present, refers to a declared register with `origin_kind == "receiver"`.
9. `receiver_reg`, when present, does not appear inside `param_regs`.
10. constructor callables always have `receiver_reg` present.
11. constructor callables use a non-`None` `signature.return_type` matching both the constructed class type and the type of `receiver_reg`.

### CFG Invariants

1. every block has exactly one terminator.
2. every block reference in a terminator refers to a block in the same callable.
3. branch successors differ.
4. all non-entry blocks are reachable after CFG cleanup passes that claim to eliminate unreachable blocks.
5. no instruction follows a terminator.

### Typing Invariants

1. every declared register has a type.
2. every instruction destination refers to a declared register.
3. operand register uses refer to declared registers.
4. return operands match the callable return type.
5. branch conditions are boolean-typed.
6. array ops use operands compatible with their declared `ArrayRuntimeKind`.
7. field loads/stores refer to fields present in the owning class declaration.
8. call arguments match the call signature arity, using `args[1:]` for receiver-carrying calls and all of `args` otherwise.
9. for receiver-carrying calls, `args[0]` is present and is compatible with the callee receiver type.

### Def/Use And Mutation Invariants

1. a non-entry register use must be dominated by a definition in v1, unless it is a declared receiver/parameter register available on entry.
2. registers may be assigned multiple times in v1.
3. verifier utilities must still be able to enumerate defs and uses precisely for later SSA conversion.

### Safety Invariants

1. direct field and direct array ops must not rely on implicit null checks.
2. direct array element/slice ops must not rely on implicit bounds checks.
3. any instruction with `effects.may_gc == True` is a safepoint candidate.
4. runtime call target names must resolve in the repository runtime-call metadata registry.
5. runtime call targets must carry sorted, unique reference argument indices matching the registry entry.
6. runtime call `effects.may_gc` and `effects.needs_safepoint_hooks` must match the registry entry.

## Lowering Rules From Semantic IR

The semantic-to-backend lowering boundary should obey these rules.

1. Structured `if`, `while`, and lowered `for in` become explicit CFG blocks and branches.
2. Semantic locals become declared backend registers with stable ordinals and origin metadata.
3. Semantic helper locals also become backend registers.
4. Direct array fast paths become direct array instructions.
5. Generic collection protocol operations become calls.
6. Required null and bounds checks become explicit backend instructions, not hidden target-emitter behavior.
7. Remaining virtual/interface dispatch stays explicit through call-target variants.
8. Constructor bodies lower as one init-style callable with an explicit receiver on entry and an explicit return of that receiver.
9. Source-level object construction lowers to `alloc_object` plus a direct constructor call, not to a target-specific wrapper symbol.
10. Runtime-backed operations that remain calls must resolve through the runtime-call metadata registry rather than ad hoc runtime call strings.

## Future SSA Compatibility

Backend IR v1 is intentionally non-SSA, but it must not block later SSA work.

The schema is reserved for later extension in these ways:

- `BackendRegId` already gives stable symbolic storage names
- CFG and instruction IDs are explicit and deterministic
- def/use information is mechanically recoverable
- merge points remain explicit in CFG even though v1 uses copies instead of phi nodes or block params

The expected SSA migration path is:

1. construct dominators and dominance frontiers from the existing CFG
2. add SSA values plus phi nodes or block parameters in a later IR revision or later lowered analysis form
3. optionally retain v1 mutable-register dumps as a pre-SSA inspection format

Nothing in v1 depends on physical registers or target stack locations, so SSA conversion remains target-neutral.

## Future Multi-Target Compatibility

Backend IR v1 is intentionally suitable for future backends beyond `x86-64 SysV`.

That is why it does not encode:

- physical register names
- stack offsets
- frame-pointer conventions
- concrete instruction mnemonics
- SysV-specific argument locations

Future target backends such as `aarch64` should consume the same core backend IR and the same program-global context.

What should differ per target is:

- ABI lowering
- legality rules
- physical register policy
- frame layout
- emission syntax and sections

## Minimal Worked Example

The following illustrates the intended shape for a tiny function:

```python
BackendCallableDecl(
    callable_id=FunctionId(module_path=("main",), name="main"),
    kind="function",
    signature=BackendSignature(
        param_types=(),
        return_type=semantic_primitive_type_ref("i64"),
    ),
    is_export=False,
    is_extern=False,
    is_static=None,
    is_private=None,
    registers=(
        BackendRegister(
            reg_id=BackendRegId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0),
            type_ref=semantic_primitive_type_ref("i64"),
            debug_name="ret0",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
    ),
    param_regs=(),
    receiver_reg=None,
    entry_block_id=BackendBlockId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0),
    blocks=(
        BackendBlock(
            block_id=BackendBlockId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0),
            debug_name="entry",
            instructions=(
                BackendConstInst(
                    inst_id=BackendInstId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0),
                    dest=BackendRegId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0),
                    constant=BackendIntConst(type_name="i64", value=0),
                    span=..., 
                ),
            ),
            terminator=BackendReturnTerminator(
                value=BackendRegOperand(
                    reg_id=BackendRegId(owner_id=FunctionId(module_path=("main",), name="main"), ordinal=0)
                ),
                span=..., 
            ),
            span=..., 
        ),
    ),
    span=..., 
)
```

This example is intentionally simple, but it shows the core v1 contract:

- explicit registers
- explicit block
- explicit instruction ID
- explicit terminator
- no assembly syntax
- no target stack layout

## Summary

Backend IR v1 is:

- CFG-based
- register-based
- non-SSA
- serializable
- target-neutral
- strong enough for current correctness-focused backend work

It is the first explicit backend execution IR for the repository, and it becomes the concrete schema that the transition plan migrates toward.