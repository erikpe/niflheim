# Semantic IR Specification

This document defines the initial semantic IR for the semantic-pipeline refactor.

Its purpose is to lock down:

- the exact node set
- the invariants the IR must satisfy
- which nodes are mandatory in early passes
- which nodes may begin as thin wrappers
- which nodes are deliberately deferred

This is a structured semantic IR, not a low-level backend IR.

## Status Note

This document describes the baseline semantic IR shape currently implemented and the invariants it was originally introduced to enforce.

It is not the complete long-term semantic-graph roadmap. Planned follow-up changes around local identity, canonical type representation, and explicit compiler-owned temporaries are tracked in [SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md](SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md).

When the two documents differ, interpret this document as describing the current baseline and the roadmap document as describing the intended migration path.

## Goals

- Eliminate ambiguous global/member/call resolution from later stages.
- Make reachability traverse explicit semantic edges instead of source syntax.
- Preserve enough source structure that diagnostics and migration stay manageable.
- Avoid prematurely introducing CFG, SSA, or backend temporary forms.

## Non-Goals

- Do not define a low-level backend IR here.
- Do not introduce CFG nodes in the first semantic IR.
- Do not introduce SSA/value numbering in the first semantic IR.
- Do not force all future optimization needs into the initial design.

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
class SyntheticId:
    kind: str
    owner: str
    name: str
```

These IDs should be the only post-typecheck representation for global symbol identity.

Local identity is now wired into local declarations, local references, and local assignment targets through `LocalId`. Function-like owners also carry a `local_info_by_id` metadata table so later passes can recover readable local names, declared types, declaration spans, and binding kinds without depending on identity internals alone. The remaining migration steps are tracked in [SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md](SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md).

## Exact Semantic IR Node Set

The first semantic IR preserves module, class, function, method, block, `if`, and `while` structure, but replaces ambiguous expression and sugar forms with explicit semantic nodes.

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
    span: SourceSpan


@dataclass(frozen=True)
class SemanticLocalInfo:
    local_id: LocalId
    owner_id: LocalOwnerId
    display_name: str
    type_name: str
    span: SourceSpan
    binding_kind: Literal["receiver", "param", "local", "for_in_element"]


@dataclass(frozen=True)
class SemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_name: str
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
    name: str
    type_name: str
    initializer: SemanticExpr | None
    span: SourceSpan


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
    collection: SemanticExpr
    iter_len_method: MethodId | None
    iter_get_method: MethodId | None
    element_type_name: str
    body: SemanticBlock
    span: SourceSpan
```

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
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldLValue:
    receiver: SemanticExpr
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IndexLValue:
    target: SemanticExpr
    index: SemanticExpr
    value_type_name: str
    set_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceLValue:
    target: SemanticExpr
    begin: SemanticExpr
    end: SemanticExpr
    value_type_name: str
    set_method: MethodId | None
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
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionRefExpr:
    function_id: FunctionId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ClassRefExpr:
    class_id: ClassId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class MethodRefExpr:
    method_id: MethodId
    receiver: SemanticExpr | None
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class LiteralExprS:
    value: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class NullExprS:
    span: SourceSpan


@dataclass(frozen=True)
class UnaryExprS:
    operator: str
    operand: SemanticExpr
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExprS:
    operator: str
    left: SemanticExpr
    right: SemanticExpr
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CastExprS:
    operand: SemanticExpr
    target_type_name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldReadExpr:
    receiver: SemanticExpr
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionCallExpr:
    function_id: FunctionId
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class StaticMethodCallExpr:
    method_id: MethodId
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class InstanceMethodCallExpr:
    method_id: MethodId
    receiver: SemanticExpr
    receiver_type_name: str
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ConstructorCallExpr:
    constructor_id: ConstructorId
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CallableValueCallExpr:
    callee: SemanticExpr
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IndexReadExpr:
    target: SemanticExpr
    index: SemanticExpr
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceReadExpr:
    target: SemanticExpr
    begin: SemanticExpr
    end: SemanticExpr
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class ArrayCtorExprS:
    element_type_name: str
    length_expr: SemanticExpr
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SyntheticExpr:
    synthetic_id: SyntheticId
    args: list[SemanticExpr]
    type_name: str
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
    | FieldReadExpr
    | FunctionCallExpr
    | StaticMethodCallExpr
    | InstanceMethodCallExpr
    | ConstructorCallExpr
    | IndexReadExpr
    | SliceReadExpr
    | ArrayCtorExprS
    | SyntheticExpr
)
```

## Required Invariants

The semantic IR should obey these rules from day one.

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

- function call
- static method call
- instance method call
- constructor call
- callable-value call
- synthetic helper call

### 3. No Raw `FieldAccessExpr` For Methods

Field reads and method references/calls must be split.

- field load -> `FieldReadExpr`
- first-class method reference -> `MethodRefExpr`
- method invocation -> explicit resolved call node

### 4. No Raw Index/Slice Syntax

Indexing and slicing must be represented as resolved semantic operations.

There should be no surviving source-form `IndexExpr` nodes in the semantic IR.

### 5. Every Expression Carries A Type Name

Every semantic expression except `NullExprS` should carry a final resolved `type_name` string.

This is intentionally simple for the first IR version and avoids forcing later passes to reach back into typecheck internals.

This is a baseline simplification, not a commitment that string-based type identity is the final semantic representation. See [SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md](SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md) for the planned migration path.

### 6. Synthetic Dependencies Must Be Explicit

If codegen would otherwise invent a helper edge, semantic lowering must emit an explicit semantic node or explicit resolved call instead.

Initial mandatory cases:

- string literal construction
- string concatenation

## Pass Classification

The node set should not be implemented all at once. Nodes are divided into three categories for the early refactor:

- mandatory: must exist as explicit semantic nodes in that pass
- wrappers: may start as thin typed wrappers over current AST forms in that pass
- deferred: may remain outside the active lowering surface until a later pass

### Pass 2: IR Skeleton Classification

Pass 2 should introduce the full declaration/statement container surface and the minimum expression surface needed to construct semantic modules and preserve typed structure.

Mandatory in pass 2:

- `SemanticProgram`
- `SemanticModule`
- `SemanticField`
- `SemanticClass`
- `SemanticParam`
- `SemanticFunction`
- `SemanticMethod`
- `SemanticBlock`
- `SemanticVarDecl`
- `SemanticAssign`
- `SemanticExprStmt`
- `SemanticReturn`
- `SemanticIf`
- `SemanticWhile`
- `SemanticBreak`
- `SemanticContinue`
- `LocalLValue`
- `FieldLValue`
- `LocalRefExpr`
- `FunctionRefExpr`
- `ClassRefExpr`
- `LiteralExprS`
- `NullExprS`
- `UnaryExprS`
- `BinaryExprS`
- `CastExprS`
- `FieldReadExpr`
- `ArrayCtorExprS`

Wrappers in pass 2:

- `LiteralExprS`
- `UnaryExprS`
- `BinaryExprS`
- `CastExprS`
- `ArrayCtorExprS`
- `FieldReadExpr`

Deferred in pass 2:

- `MethodRefExpr`
- `FunctionCallExpr`
- `StaticMethodCallExpr`
- `InstanceMethodCallExpr`
- `ConstructorCallExpr`
- `IndexReadExpr`
- `SliceReadExpr`
- `IndexLValue`
- `SliceLValue`
- `SemanticForIn`
- `SyntheticExpr`

### Pass 3: Resolved Call Classification

Pass 3 is where ambiguous call interpretation disappears.

Mandatory in pass 3:

- `FunctionCallExpr`
- `StaticMethodCallExpr`
- `InstanceMethodCallExpr`
- `ConstructorCallExpr`
- `CallableValueCallExpr`
- `MethodRefExpr` if first-class callable values remain supported at this stage
- `CallExpr` -> `FunctionCallExpr`, `StaticMethodCallExpr`, `InstanceMethodCallExpr`, `ConstructorCallExpr`, `CallableValueCallExpr`, or `SyntheticExpr`

Wrappers in pass 3:

- `LocalRefExpr`
- `FunctionRefExpr`
- `ClassRefExpr`
- `FieldReadExpr`

Deferred in pass 3:

- `IndexReadExpr`
- `SliceReadExpr`
- `IndexLValue`
- `SliceLValue`
- `SemanticForIn`
- `SyntheticExpr`

### Pass 4: Structural Sugar And Synthetic Classification

Pass 4 should make all structural and hidden-helper semantics explicit.

Mandatory in pass 4:

- `IndexReadExpr`
- `SliceReadExpr`
- `IndexLValue`
- `SliceLValue`
- `SemanticForIn`

Mandatory in pass 4 if helper cannot be modeled as an ordinary resolved call:

- `SyntheticExpr`

Preferred rule for pass 4:

- if a hidden dependency is a real source-backed method like `Str.from_u8_array` or `Str.concat`, lower it to `StaticMethodCallExpr`
- use `SyntheticExpr` only when there is no real source-backed callable to point at

Deferred beyond pass 4:

- CFG nodes
- SSA/value form
- backend runtime op nodes

## Recommended Implementation Interpretation

To keep the refactor manageable:

1. The declaration and structured statement nodes should appear early because they define the semantic container shape.
2. Explicit resolved call nodes are the highest-value semantic upgrade and should be the first non-wrapper expression family to become mandatory.
3. Structural sugar nodes should wait until the call-resolution path is stable.
4. `SyntheticExpr` should remain a last resort, not a default encoding.

## Deliberate Omissions From The First Semantic IR

To keep the first refactor manageable, the semantic IR should not attempt these yet.

### 1. No CFG Nodes

The first IR is still structured, not control-flow-graph based.

### 2. No SSA Or Temporary Value Form

Do not introduce SSA names, phi nodes, or backend temporaries yet.

### 3. No Separate Primitive Operation Nodes Unless Needed

Unary and binary primitive operations can remain as typed `UnaryExprS` and `BinaryExprS` for now.

### 4. No Dedicated Array Runtime Nodes Yet

Array constructor and array indexing can remain semantic expression nodes without committing to final runtime-call lowering.

## Mapping From Current Source AST

The initial lowering should roughly map as follows:

- `IdentifierExpr` -> `LocalRefExpr`, `FunctionRefExpr`, or `ClassRefExpr`
- `LiteralExpr` -> `LiteralExprS` or explicit synthetic form when the literal implies helper construction
- `FieldAccessExpr` -> `FieldReadExpr`, `MethodRefExpr`, `StaticMethodCallExpr`, or `InstanceMethodCallExpr`
- `CallExpr` -> one explicit resolved call node
- `IndexExpr` -> `IndexReadExpr`
- parser-lowered slice call forms -> `SliceReadExpr` or `SliceLValue`
- `ForInStmt` -> `SemanticForIn`

## Why This Node Set Is The Right Size

This node set is deliberately chosen to do three things and no more:

1. eliminate ambiguous call and member-resolution work from later stages
2. make reachability edges explicit
3. preserve enough source structure that diagnostics and migration stay manageable

If a later pass still has to flatten field chains or infer whether a call is a constructor or method call, then the node set is still too weak.