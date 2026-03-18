# Interfaces v1 Design

This document describes a minimal but general interface design for Niflheim.

It is a future-facing design note, not a statement that interfaces are already implemented.

The goal is to support interface-typed values, class conformance checking, runtime-checked casts, and dynamic method dispatch without overextending the current compiler/runtime architecture.

## Status

Proposed design.

Interfaces remain out of scope for MVP v0.1 as defined in [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md).

## Goals

- Support interface declarations with method signatures only.
- Allow classes to declare `implements` clauses.
- Require compile-time conformance between class methods and declared interface methods.
- Treat interfaces as first-class reference types.
- Support implicit upcast from implementing class to interface.
- Support explicit runtime-checked casts from `Obj` to interface.
- Support dynamic method dispatch through interface-typed receivers.
- Keep the design compatible with the current semantic IR, codegen, and runtime metadata direction.

## Non-Goals

- No interface inheritance in v1.
- No default method bodies.
- No fields declared on interfaces.
- No generic interfaces.
- No automatic interface implementation by arrays or other built-in runtime types.
- No overloading rules beyond exact signature matching.

## Principles

### 1) Interfaces Are Real Reference Types

Interfaces are not just compile-time traits. They must be usable in:

- variable declarations
- parameters
- return types
- fields
- explicit casts

That means the compiler and runtime must agree on what an interface value means.

### 2) Conformance Is Checked Statically

If a class declares `implements Hashable`, the compiler must verify that the class defines every required interface method with a compatible signature.

For v1, compatibility should be exact:

- same method name
- same parameter count
- same parameter types
- same return type
- instance method only

### 3) Interface Dispatch Must Be Explicit In IR

Interface calls are not the same as concrete class method calls.

The current semantic IR already distinguishes concrete call shapes clearly. Interface dispatch should continue that pattern by introducing explicit interface-call nodes instead of pushing interface lookup logic into codegen heuristics.

### 4) Runtime Casts Must Use Metadata, Not Syntax Recovery

`Obj -> Interface` casts must succeed or fail using runtime type/interface metadata. They should not rely on leaf-name matching or compiler-only assumptions.

### 5) Keep v1 Narrow But General

The first version should solve the general mechanism once:

- interface declarations
- class conformance
- interface types
- runtime cast checks
- interface dispatch

More advanced features can layer on later.

### 6) Interface Values Use The Same Runtime Representation As Object References

For v1, interface-typed values are represented at runtime as the same single object pointer used for class references and `Obj`.

That means:

- class-to-interface upcast is a runtime representation no-op
- interface-to-`Obj` upcast is a runtime representation no-op
- checked interface casts return the original object pointer on success
- interface dispatch performs lookup from the concrete object's runtime type metadata

v1 does not use fat pointers or `(object, interface)` pairs.

## Surface Syntax

### Interface Declaration

```nif
interface Hashable {
    fn hash_code() -> u64;
}

interface Comparable {
    fn equals(other: Obj) -> bool;
}
```

### Class Implementation

```nif
class MyKey implements Hashable, Comparable {
    fn hash_code() -> u64 {
        return 42u;
    }

    fn equals(other: Obj) -> bool {
        return false;
    }
}
```

### Cast And Dispatch Example

```nif
var key_obj: Obj = ...;
var key_hashable: Hashable = (Hashable)key_obj;
var hash: u64 = key_hashable.hash_code();
```

If `key_obj` does not implement `Hashable`, the cast must fail at runtime.

## Type System Decisions

### Interface Kind

`TypeInfo` should gain a new kind:

```python
TypeInfo(kind="interface", name="Hashable")
```

Interfaces are reference-like and nullable, but they are not concrete class types.

### Assignability Rules

For v1:

- class type -> same class type: allowed
- class type -> implemented interface type: allowed
- interface type -> `Obj`: allowed
- class type -> `Obj`: allowed
- `null` -> interface type: allowed
- `Obj` -> interface type: explicit cast only
- interface type -> class type: explicit cast only
- interface type -> interface type: explicit cast only unless identical

Interfaces are allowed anywhere ordinary reference types are allowed:

- locals
- parameters
- returns
- fields
- arrays of interface type

### Cast Rules

The existing cast model should be extended as follows:

- exact same-type cast: allowed
- class/interface/reference -> `Obj`: allowed
- `Obj` -> class/interface/reference: allowed only as explicit runtime-checked cast
- interface -> interface: allowed only as explicit runtime-checked cast

For v1, direct explicit interface-to-interface casts are allowed and runtime-checked. A detour through `Obj` is not required.

Primitive and callable cast rules remain unchanged.

### Equality, Identity, And Null

Interface values follow the same reference semantics as class values:

- equality/inequality compares underlying object identity
- casting between class/interface/`Obj` does not change identity
- interface-typed values are nullable
- interface-typed locals and fields default to `null`
- null dereference through an interface value follows the same runtime failure policy as any other reference dereference

## Frontend AST Shape

The frontend should gain explicit interface declarations.

Suggested additions:

```python
@dataclass(frozen=True)
class InterfaceMethodDecl:
    name: str
    params: list[ParamDecl]
    return_type: TypeRefNode
    span: SourceSpan


@dataclass(frozen=True)
class InterfaceDecl:
    name: str
    methods: list[InterfaceMethodDecl]
    is_export: bool
    span: SourceSpan
```

And extend `ClassDecl`:

```python
implements: list[TypeRefNode]
```

And extend `ModuleAst`:

```python
interfaces: list[InterfaceDecl]
```

Interfaces are exportable and importable exactly like classes in v1. Unqualified imported interface names follow the same local-first and ambiguity rules already used for classes.

## Canonical Symbol Identity

Interfaces should participate in the same post-typecheck canonical ID model as functions, classes, and methods.

Suggested new IDs:

```python
@dataclass(frozen=True)
class InterfaceId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class InterfaceMethodId:
    module_path: ModulePath
    interface_name: str
    name: str
```

The shared symbol index should provide:

- `InterfaceId -> InterfaceDecl`
- `InterfaceMethodId -> InterfaceMethodDecl`
- module-local interface lookup by unqualified name

## Typecheck Model Shape

The typechecker should add explicit interface metadata.

Suggested model:

```python
@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    methods: dict[str, FunctionSig]
```

The typecheck context and declaration pass should collect:

- local interfaces
- imported interfaces
- interface conformance for classes declaring `implements`

For v1, private methods do not satisfy interface conformance. Interface requirements must be implemented by public instance methods.

## Semantic IR Decisions

### Why New Nodes Are Needed

The existing semantic IR uses concrete call targets for class methods:

- `InstanceMethodCallExpr(method_id=...)`
- `StaticMethodCallExpr(method_id=...)`

That is correct for concrete dispatch, but not for interface dispatch.

If the receiver is typed as an interface, the runtime target depends on the concrete object type. That must be represented explicitly.

### Suggested Interface Call Node

Minimal v1 addition:

```python
@dataclass(frozen=True)
class InterfaceMethodCallExpr:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    receiver: SemanticExpr
    receiver_type_name: str
    args: list[SemanticExpr]
    type_name: str
    span: SourceSpan
```

If first-class interface method values become necessary later, add a corresponding `InterfaceMethodRefExpr`. That is not required for v1.

For v1, interface method references are out of scope. Only interface method calls are supported. Attempting to use an interface method as a first-class callable value should be rejected by the typechecker.

### Cast Nodes

`CastExprS` can remain the semantic cast node if `target_type_name` is extended to include interface type names.

No separate interface-cast expression node is required for v1.

## Lowering Decisions

Lowering should distinguish concrete method dispatch from interface dispatch.

Rules:

- class receiver + resolved class method -> `InstanceMethodCallExpr`
- interface receiver + resolved interface method -> `InterfaceMethodCallExpr`
- static interface methods are not supported in v1

This keeps dispatch semantics explicit before codegen begins.

## Runtime Metadata Shape

### Current Limitation

Current runtime type metadata only supports exact concrete type comparison for checked casts.

That is sufficient for `Obj -> ConcreteClass`, but not for `Obj -> Interface`.

### Required Extension

Each concrete runtime type must know which interfaces it implements and how to dispatch those interface methods.

Suggested runtime types:

```c
typedef struct RtInterfaceType RtInterfaceType;
typedef struct RtInterfaceImpl RtInterfaceImpl;

struct RtInterfaceType {
    const char* debug_name;
    uint32_t method_count;
    uint32_t reserved;
};

struct RtInterfaceImpl {
    const RtInterfaceType* interface_type;
    const void* method_table;
    uint32_t method_count;
    uint32_t reserved;
};
```

Extend `RtType` conceptually with:

```c
const RtInterfaceImpl* interfaces;
uint32_t interface_count;
```

Because interface values are represented as raw object pointers, no separate runtime wrapper or adjusted receiver representation is introduced in v1.

### Dispatch Table Shape

For v1, interface method dispatch should use stable slot order, not method-name lookup at runtime.

That means:

- each interface defines method order statically
- each implementing class emits a matching function-pointer table for that interface
- interface method dispatch uses `(interface descriptor, method slot)`

This is simpler and faster than string-based method lookup.

## Runtime Cast Design

### Current Limitation

Current `rt_checked_cast` only accepts exact type matches.

### v1 Requirement

For interface casts, runtime must succeed if the object's concrete type implements the requested interface.

Two viable shapes:

1. Extend `rt_checked_cast` to understand both class and interface metadata kinds.
2. Add a separate `rt_checked_cast_interface(obj, expected_interface)` helper.

For a minimal v1, the second option is acceptable if it keeps the code clearer.

Expected behavior:

- `null` cast to interface returns `null`
- object implementing interface returns object unchanged
- non-implementing object panics with bad-cast diagnostics

The returned value is the original object pointer, not a wrapped interface object.

## Codegen Shape

### Metadata Emission

Codegen must emit:

- interface descriptors
- per-class implemented-interface tables
- per-interface method tables for implementing classes

This is a natural extension of the existing type-metadata emission work.

### Interface Dispatch

For `InterfaceMethodCallExpr`, codegen should conceptually:

1. evaluate receiver
2. obtain concrete object type metadata
3. find the interface implementation record for the requested interface
4. load the method-table entry for the requested slot
5. pass receiver as the first argument
6. emit an indirect call through the loaded function pointer

To keep assembly simpler, interface lookup can be centralized in the runtime with a helper such as:

```c
void* rt_lookup_interface_method(void* obj, const RtInterfaceType* iface, uint32_t slot);
```

Then codegen only needs to prepare the arguments and indirect-call the returned function pointer.

For v1, the lookup strategy should be locked as:

- linear scan over the concrete runtime type's implemented-interface table
- match by interface descriptor pointer
- dispatch by stable slot index within the matched interface method table

`rt_lookup_interface_method(...)` should assume the object already implements the interface, with cast-validation handled separately by checked-cast logic. It may still panic on corrupted metadata.

## Standard Library Use Case: `Map`

This design directly supports interface-based key operations.

Example conceptual interfaces:

```nif
interface Hashable {
    fn hash_code() -> u64;
}

interface Comparable {
    fn equals(other: Obj) -> bool;
}
```

Then `Map` can:

- cast key object to `Hashable` before hashing
- cast candidate key to `Comparable` before equality checks

If a key does not implement the required interface, the cast fails at runtime.

This matches the intended `Map` use case without needing generics in v1.

## Key Design Decisions

1. Interfaces are reference types, not compile-time-only traits.
2. Class conformance is checked statically.
3. Interface dispatch is represented explicitly in semantic IR.
4. Runtime casts use metadata, not compiler-only guesses.
5. Interface dispatch uses slot-based method tables, not string lookup.
6. Interface values are represented as raw object pointers, not fat pointers.
7. Interfaces are exportable/importable exactly like classes.
8. Private methods do not satisfy interface conformance.
9. Direct explicit interface-to-interface casts are allowed and runtime-checked.
10. Interface method references are out of scope for v1.
11. v1 stays narrow: no inheritance, no defaults, no generics.

## Implementation Outline

Recommended order:

1. Add frontend syntax and AST nodes.
2. Add `InterfaceInfo` and interface declaration collection in typecheck.
3. Add interface assignability and cast legality rules.
4. Add `InterfaceId` and `InterfaceMethodId` to semantic symbol indexing.
5. Add `InterfaceMethodCallExpr` to semantic IR.
6. Lower interface method calls explicitly.
7. Extend runtime type metadata for implemented interfaces.
8. Add runtime checked interface cast support.
9. Emit interface metadata in codegen.
10. Emit interface dispatch calls in codegen.
11. Add stdlib/integration coverage using `Hashable` and `Comparable`.

## Testing Requirements

Frontend:

- parse interface declarations
- parse class `implements` clauses

Typecheck:

- reject missing interface methods
- reject wrong parameter/return types
- accept class-to-interface assignability
- accept explicit `Obj -> Interface` cast typing

Semantic lowering:

- interface receiver call lowers to `InterfaceMethodCallExpr`
- concrete receiver call remains `InstanceMethodCallExpr`

Runtime/codegen:

- cast succeeds for implementing classes
- cast fails for non-implementing classes
- interface dispatch calls correct concrete implementation
- multiple interfaces on one class work correctly

Integration:

- interface-based `Map` key path works end-to-end

## Open Questions Deferred From v1

- Should built-in reference types like `Str` be able to declare interfaces immediately?
- Should interface values be allowed in extern function signatures immediately, or deferred until the FFI ABI is documented explicitly?

Recommended follow-up direction for externs:

- if interface values remain raw object pointers, they can later ABI-lower exactly like `Obj`
- v1 implementation may still choose to reject interfaces in extern signatures until that is documented and tested explicitly

## Summary

Interfaces v1 are feasible as a general feature in this compiler, but only if they are treated as a full cross-layer feature:

- syntax and AST support
- type-system support
- semantic IR support
- runtime metadata support
- codegen dispatch support

The minimal maintainable design is to keep interfaces explicit in the typechecker, semantic IR, and runtime metadata rather than trying to compile them away into concrete class calls.