# Semantic IR Specification

This document defines the semantic IR used by the compiler.

Its purpose is to lock down:

- the exact node set
- the invariants the IR must satisfy
- the layering boundaries between source semantic IR and lowered semantic IR
- the semantic forms that are intentionally not represented in this IR

This is a structured semantic IR, not a low-level backend IR.

## Status Note

This document describes the baseline semantic IR shape currently implemented and the invariants it was originally introduced to enforce.

It documents the stable current architecture. When implementation details moved during semantic cleanups, this document remains the source of truth for the current node families, identity rules, and lowering boundaries.

## Goals

- Eliminate ambiguous global/member/call resolution from later stages.
- Make reachability traverse explicit semantic edges instead of source syntax.
- Preserve enough source structure that diagnostics stay manageable.
- Avoid prematurely introducing CFG, SSA, or backend temporary forms.

## Non-Goals

- Do not define a low-level backend IR here.
- Do not introduce CFG nodes in this IR.
- Do not introduce SSA/value numbering in this IR.
- Do not force all future optimization needs into this design.

## Canonical Symbol Identity

All global symbol references in semantic IR must use canonical typed IDs.

```python
@dataclass(frozen=True)
class FunctionId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class ClassId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class MethodId:
    module_path: ModulePath
    class_name: str
    name: str


@dataclass(frozen=True)
class ConstructorId:
    module_path: ModulePath
    class_name: str


@dataclass(frozen=True)
class InterfaceId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class InterfaceMethodId:
    module_path: ModulePath
    interface_name: str
    name: str


LocalOwnerId = FunctionId | MethodId


@dataclass(frozen=True)
class LocalId:
    owner_id: LocalOwnerId
    ordinal: int
```

These IDs are the post-typecheck representation for global symbol identity. `LocalId` is the canonical local identity inside a single function-like owner; it is not derived from source names and stays stable across semantic lowering and optimization.

Local identity is wired into local declarations, local references, and local assignment targets through `LocalId`. Function-like owners also carry a `local_info_by_id` metadata table so later passes can recover readable local names, declared types, declaration spans, and binding kinds without depending on names or AST shape.

Semantic IR now carries canonical `SemanticTypeRef` values for semantic consumers. Some declaration metadata still preserves display-oriented `*_type_name` strings for diagnostics and compatibility helpers, but semantic analyses and downstream lowering should treat `SemanticTypeRef` as the type authority.

Lowered local declaration nodes now rely primarily on the owner-local `local_info_by_id` table for display names and declared local types. That metadata is still keyed by the declaration's `LocalId`, but it no longer needs to be copied onto every lowered `SemanticVarDecl` by default.

## Source Semantic IR And Lowered Semantic IR

The semantic pipeline intentionally uses two closely related structured IR layers.

- Source semantic IR in `compiler/semantic/ir.py` preserves source-level structured control flow and resolved semantic operations.
- Lowered semantic IR in `compiler/semantic/lowered_ir.py` keeps the same typed semantic surface, but moves compiler-introduced control-flow scaffolding and helper locals into explicit lowered nodes such as `LoweredSemanticIf`, `LoweredSemanticWhile`, and `LoweredSemanticForIn`.

This split keeps source-facing reasoning simple while giving later lowering and codegen phases a deterministic, explicit execution-oriented form.

## Exact Semantic IR Node Set

The semantic IR preserves module, class, function, method, block, `if`, and `while` structure, but replaces ambiguous expression and sugar forms with explicit semantic nodes.

### Program And Declaration Nodes

```python
@dataclass(frozen=True)
class SemanticProgram:
    entry_module: ModulePath
    modules: dict[ModulePath, SemanticModule]


@dataclass(frozen=True)
class SemanticModule:
    module_path: ModulePath
    file_path: Path
    classes: list[SemanticClass]
    functions: list[SemanticFunction]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticField:
    name: str
    type_name: str
    type_ref: SemanticTypeRef
    initializer: SemanticExpr | None
    is_private: bool
    is_final: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticClass:
    class_id: ClassId
    is_export: bool
    fields: list[SemanticField]
    methods: list[SemanticMethod]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticParam:
    name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class SemanticLocalInfo:
    local_id: LocalId
    owner_id: LocalOwnerId
    display_name: str
    type_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan
    binding_kind: Literal[
        "receiver",
        "param",
        "local",
        "for_in_element",
        "for_in_collection",
        "for_in_length",
        "for_in_index",
    ]


@dataclass(frozen=True)
class SemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_name: str
    return_type_ref: SemanticTypeRef
    body: SemanticBlock | None
    is_export: bool
    is_extern: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo]


@dataclass(frozen=True)
class SemanticMethod:
    method_id: MethodId
    params: list[SemanticParam]
    return_type_name: str
    return_type_ref: SemanticTypeRef
    body: SemanticBlock
    is_static: bool
    is_private: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo]
```

### Statement Nodes

```python
@dataclass(frozen=True)
class SemanticBlock:
    statements: list[SemanticStmt]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticVarDecl:
    local_id: LocalId
    initializer: SemanticExpr | None
    span: SourceSpan
    name: str | None = None
    type_name: str | None = None
    type_ref: SemanticTypeRef | None = None


For lowered semantic programs, `SemanticVarDecl.name`, `SemanticVarDecl.type_name`, and `SemanticVarDecl.type_ref` may be omitted when the same information is already present in the owning function or method's `local_info_by_id` table. New semantic consumers should prefer the owner-local metadata helpers over direct access to those optional declaration fields.

@dataclass(frozen=True)
class SemanticAssign:
    target: SemanticLValue
    value: SemanticExpr
    span: SourceSpan


@dataclass(frozen=True)
class SemanticExprStmt:
    expr: SemanticExpr
    span: SourceSpan


@dataclass(frozen=True)
class SemanticReturn:
    value: SemanticExpr | None
    span: SourceSpan


@dataclass(frozen=True)
class SemanticIf:
    condition: SemanticExpr
    then_block: SemanticBlock
    else_block: SemanticBlock | None
    span: SourceSpan


@dataclass(frozen=True)
class SemanticWhile:
    condition: SemanticExpr
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class SemanticBreak:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticContinue:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticForIn:
    element_name: str
    element_local_id: LocalId
    collection: SemanticExpr
    iter_len_dispatch: SemanticDispatch
    iter_get_dispatch: SemanticDispatch
    element_type_ref: SemanticTypeRef
    body: SemanticBlock
    span: SourceSpan
```

Source semantic `SemanticForIn` only records the user-visible loop element and the resolved iteration dispatch. The compiler-introduced helper locals for cached collection, length, and index live on `LoweredSemanticForIn` after executable-oriented lowering.

Those helper locals are tracked in the same `local_info_by_id` metadata table as user-declared locals, which keeps ownership and later stack/layout decisions explicit without inventing backend-only naming conventions.

Codegen and newer semantic utilities should prefer canonical `SemanticTypeRef` data where it is available.

Statement union:

```python
SemanticStmt = (
    SemanticBlock
    | SemanticVarDecl
    | SemanticAssign
    | SemanticExprStmt
    | SemanticReturn
    | SemanticIf
    | SemanticWhile
    | SemanticForIn
    | SemanticBreak
    | SemanticContinue
)
```

### LValue Nodes

The semantic IR should stop representing assignment targets as arbitrary expressions.

```python
@dataclass(frozen=True)
class LocalLValue:
    local_id: LocalId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class BoundMemberAccess:
    receiver: SemanticExpr
    receiver_type_ref: SemanticTypeRef


@dataclass(frozen=True)
class FieldLValue:
    access: BoundMemberAccess
    owner_class_id: ClassId
    field_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class IndexLValue:
    target: SemanticExpr
    index: SemanticExpr
    value_type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class SliceLValue:
    target: SemanticExpr
    begin: SemanticExpr
    end: SemanticExpr
    value_type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan
```

LValue union:

```python
SemanticLValue = LocalLValue | FieldLValue | IndexLValue | SliceLValue
```

### Expression Nodes

```python
@dataclass(frozen=True)
class LocalRefExpr:
    local_id: LocalId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class FunctionRefExpr:
    function_id: FunctionId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class ClassRefExpr:
    class_id: ClassId
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class MethodRefExpr:
    method_id: MethodId
    receiver: SemanticExpr | None
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class LiteralExprS:
    constant: SemanticConstant
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class NullExprS:
    span: SourceSpan
    type_ref: SemanticTypeRef = field(default_factory=semantic_null_type_ref)


@dataclass(frozen=True)
class UnaryExprS:
    op: SemanticUnaryOp
    operand: SemanticExpr
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExprS:
    op: SemanticBinaryOp
    left: SemanticExpr
    right: SemanticExpr
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class CastExprS:
    operand: SemanticExpr
    cast_kind: CastSemanticsKind
    target_type_ref: SemanticTypeRef
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class TypeTestExprS:
    operand: SemanticExpr
    test_kind: TypeTestSemanticsKind
    target_type_ref: SemanticTypeRef
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class FieldReadExpr:
    access: BoundMemberAccess
    owner_class_id: ClassId
    field_name: str
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class FunctionCallTarget:
    function_id: FunctionId


@dataclass(frozen=True)
class StaticMethodCallTarget:
    method_id: MethodId


@dataclass(frozen=True)
class InstanceMethodCallTarget:
    method_id: MethodId
    access: BoundMemberAccess


@dataclass(frozen=True)
class InterfaceMethodCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    access: BoundMemberAccess


@dataclass(frozen=True)
class ConstructorCallTarget:
    constructor_id: ConstructorId


@dataclass(frozen=True)
class CallableValueCallTarget:
    callee: SemanticExpr


SemanticCallTarget = (
    FunctionCallTarget
    | StaticMethodCallTarget
    | InstanceMethodCallTarget
    | InterfaceMethodCallTarget
    | ConstructorCallTarget
    | CallableValueCallTarget
)


@dataclass(frozen=True)
class CallExprS:
    target: SemanticCallTarget
    args: list[SemanticExpr]
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class ArrayLenExpr:
    target: SemanticExpr
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class IndexReadExpr:
    target: SemanticExpr
    index: SemanticExpr
    type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class SliceReadExpr:
    target: SemanticExpr
    begin: SemanticExpr
    end: SemanticExpr
    type_ref: SemanticTypeRef
    dispatch: SemanticDispatch
    span: SourceSpan


@dataclass(frozen=True)
class ArrayCtorExprS:
    element_type_ref: SemanticTypeRef
    length_expr: SemanticExpr
    type_ref: SemanticTypeRef
    span: SourceSpan


@dataclass(frozen=True)
class StringLiteralBytesExpr:
    literal_text: str
    type_ref: SemanticTypeRef
    span: SourceSpan
```

Expression union:

```python
SemanticExpr = (
    LocalRefExpr
    | FunctionRefExpr
    | ClassRefExpr
    | MethodRefExpr
    | LiteralExprS
    | NullExprS
    | UnaryExprS
    | BinaryExprS
    | CastExprS
    | TypeTestExprS
    | FieldReadExpr
    | CallExprS
    | ArrayLenExpr
    | IndexReadExpr
    | SliceReadExpr
    | ArrayCtorExprS
    | StringLiteralBytesExpr
)
```

## Required Invariants

The semantic IR must obey these rules.

### 1. No Ambiguous Global References

These source-level forms should not survive once lowered:

- unresolved imported function names
- unresolved imported class names
- unresolved field-chain module member references

They must become one of:

- `FunctionRefExpr`
- `ClassRefExpr`
- `MethodRefExpr`
- explicit call nodes using canonical IDs

### 2. No Generic `CallExpr`

There should be no semantic equivalent of the current source `CallExpr` where the callee is an arbitrary expression and later stages must guess what it means.

Every call must be one of:

- a `CallExprS` with a `FunctionCallTarget`
- a `CallExprS` with a `StaticMethodCallTarget`
- a `CallExprS` with an `InstanceMethodCallTarget`
- a `CallExprS` with an `InterfaceMethodCallTarget`
- a `CallExprS` with a `ConstructorCallTarget`
- a `CallExprS` with a `CallableValueCallTarget`

### 3. No Raw `FieldAccessExpr` For Methods

Field reads and method references/calls must be split.

- field load -> `FieldReadExpr`
- first-class method reference -> `MethodRefExpr`
- method invocation -> `CallExprS` with an explicit call target and, for receiver-based calls, a `BoundMemberAccess`

### 4. No Raw Index/Slice Syntax

Indexing and slicing must be represented as resolved semantic operations.

There should be no surviving source-form `IndexExpr` nodes in the semantic IR.

### 5. Every Expression Carries A Canonical Type

Every semantic expression carries a final resolved `SemanticTypeRef`.

This keeps later semantic passes and codegen off of ad hoc type-name reconstruction.

Display-oriented string fields may still exist on declarations and metadata helpers, but they are not the semantic source of truth.

### 6. Synthetic Dependencies Must Be Explicit

If codegen would otherwise invent a helper edge, semantic lowering must emit an explicit semantic node or explicit resolved call instead.

Important cases include:

- string literal construction
- string concatenation

Current practice prefers explicit resolved calls for helper-backed operations and uses dedicated semantic nodes such as `StringLiteralBytesExpr` only when the semantic surface itself needs to preserve a non-source helper dependency.

## Deliberate Omissions

The semantic IR intentionally omits these forms:

- CFG nodes
- SSA/value form
- backend runtime op nodes

### 1. No CFG Nodes

The IR is structured, not control-flow-graph based.

### 2. No SSA Or Temporary Value Form

Do not introduce SSA names, phi nodes, or backend temporaries yet.

### 3. No Separate Primitive Operation Nodes Unless Needed

Unary and binary primitive operations can remain as typed `UnaryExprS` and `BinaryExprS` for now.

### 4. No Dedicated Array Runtime Nodes Yet

Array constructor and array indexing can remain semantic expression nodes without committing to final runtime-call lowering.

## Mapping From Current Source AST

Lowering should roughly map as follows:

- `IdentifierExpr` -> `LocalRefExpr`, `FunctionRefExpr`, or `ClassRefExpr`
- `LiteralExpr` -> `LiteralExprS` or a dedicated helper node such as `StringLiteralBytesExpr` when the literal implies helper construction
- `FieldAccessExpr` -> `FieldReadExpr`, `MethodRefExpr`, or receiver-bearing call-target construction via `BoundMemberAccess`
- `CallExpr` -> one explicit resolved call node
- `IndexExpr` -> `IndexReadExpr`
- parser-lowered slice call forms -> `SliceReadExpr` or `SliceLValue`
- `ForInStmt` -> `SemanticForIn`

## Why This Node Set Is The Right Size

This node set is deliberately chosen to do three things and no more:

1. eliminate ambiguous call and member-resolution work from later stages
2. make reachability edges explicit
3. preserve enough source structure that diagnostics stay manageable

If a later pass still has to flatten field chains or infer whether a call is a constructor or method call, then the node set is still too weak.