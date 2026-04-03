# Single Inheritance Plan

This document defines a concrete implementation plan for adding single inheritance without overriding.

The feature is intentionally scoped as a subtype/layout feature first:

- base fields are a prefix of subclass fields
- inherited methods resolve to their declaring class
- subclass concrete types inherit all base interfaces
- runtime class checks walk a superclass chain

The design is also intentionally shaped as preparation for later virtual class dispatch and explicit `override` support.

## Status

Planned.

The current compiler/runtime still assumes flat classes.

## Why This Plan Exists

The compiler already has most of the ingredients needed for nominal subtyping:

- nominal class IDs
- explicit constructors
- semantic/lowered IR with owner-aware locals
- runtime type metadata for checked casts and type tests
- interface metadata and method-table emission

What is still missing is the actual inheritance spine that ties those pieces together.

Today, the pipeline assumes all of the following:

- every class is layout-rooted at itself
- field offsets are computed from one class's declared fields only
- member lookup only inspects the receiver's own class
- checked casts and `is` tests for class types are exact-type only
- implemented interfaces are attached only to the declaring concrete class

Those assumptions are exactly what prevent class subtyping.

The goal of this plan is to add single inheritance in a way that is immediately useful, but that does not paint the compiler into a corner before virtual dispatch and overriding are added later.

## Goals

- Add one optional superclass per class.
- Treat subclass values as assignable to base-class types.
- Make inherited instance methods callable on subclasses.
- Make inherited fields part of subclass object layout with base-prefix offsets.
- Make class type tests and checked casts subtype-aware at runtime.
- Make subclass runtime metadata inherit base interfaces transitively.
- Keep inherited methods owned by their declaring class for semantic IDs and codegen labels.
- Leave room for later virtual dispatch and `override` without redoing class metadata from scratch.

## Non-Goals

- No multiple inheritance.
- No method overriding in this slice.
- No dynamic class-method dispatch in this slice.
- No `override` keyword yet.
- No abstract classes.
- No protected visibility tier.
- No field hiding.
- No super-method calls in this slice.
- No interface inheritance in this slice.

## Current Baseline

The current flat-class assumptions are visible in these areas:

- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
  - `ClassDecl` has no superclass reference.
- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
  - `ClassInfo` stores only one class-local field/method view.
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
  - class declaration collection is module-local and flat.
- [compiler/typecheck/relations.py](../compiler/typecheck/relations.py)
  - class assignability/casts do not walk superclass relations.
- [compiler/semantic/lowering/resolution.py](../compiler/semantic/lowering/resolution.py)
  - member lookup resolves fields/methods against the receiver's own class only.
- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - field offsets are generated from one class's declared field list only.
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - interface metadata is attached from `cls.implemented_interfaces` only.
- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - `RtType` has no superclass pointer.
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - `rt_checked_cast` and `rt_is_instance_of_type` use exact-type equality only.

## Surface Syntax

Recommended class syntax:

```nif
class Derived extends Base {
    ...
}

class Derived extends Base implements Hashable, Equalable {
    ...
}
```

Recommended constructor chaining syntax:

```nif
class Derived extends Base {
    extra: i64;

    constructor(base_value: i64, extra: i64) {
        super(base_value);
        __self.extra = extra;
        return;
    }
}
```

Only constructor chaining uses `super(...)` in this slice.

No `super.method(...)` and no `super.field` syntax yet.

## Main Design Decisions

## 1. Add One Optional `extends` Clause

Each class may declare zero or one superclass.

Recommended AST shape:

```python
base_class: TypeRefNode | None
```

Rationale:

- one explicit superclass keeps layout and runtime checks simple
- the shape extends naturally later to overriding and virtual dispatch
- it matches the existing `implements` clause style better than punctuation-only syntax

## 2. Subclassing Is A Real Nominal Subtype Relation

If `Derived extends Base`, then:

- `Derived` is assignable to `Base`
- explicit casts and `is` tests between `Obj` and `Base` must accept `Derived` instances
- identity equality remains unchanged
- `same_type` remains exact-type only

Rationale:

- this preserves a clean distinction between exact-type tests and subtype-aware instance tests
- it aligns later virtual dispatch with later override semantics without changing identity rules

## 3. Base Fields Are A Physical Prefix Of Subclass Fields

The runtime layout rule is:

- subclass payload layout begins with all inherited base fields, in base layout order
- subclass-declared fields follow after that

This means every inherited field keeps the same offset in every subclass.

Rationale:

- field access to a base-declared field can use the base owner's offset even on subclass instances
- this is the right physical foundation for future virtual dispatch and upcasts
- it avoids later offset churn when overriding is introduced

## 4. Inherited Methods Resolve To Their Declaring Class

If `Base.read()` is inherited by `Derived`, then a call on a `Derived` receiver lowers to the `MethodId` for `Base.read`, not a copied `Derived.read` symbol.

Rationale:

- no method body duplication
- declaring-class ownership remains stable in semantic IR and codegen
- later overriding can replace method lookup results without redefining the method identity model

## 5. No Member Redeclaration In This Slice

Without overriding, duplicate member names across the inheritance chain should be rejected.

That includes:

- a subclass field reusing any inherited field name
- a subclass method reusing any inherited method name
- subclass field/method collisions with inherited members

Recommended rule: reject all collisions, including collisions with inherited private members.

Rationale:

- avoids accidental field hiding or pseudo-overrides
- keeps the current slice semantically crisp
- keeps later `override` introduction explicit rather than inferred from shadowing

## 6. Private Members Stay Owned By Their Declaring Class

Private members are inherited physically, but not accessible from subclasses.

That means:

- inherited private fields still exist in layout
- inherited private methods still exist as declarations
- subclass bodies cannot access them

Rationale:

- preserves current `private` meaning
- avoids introducing a protected-like access tier implicitly

## 7. Subclasses Inherit All Base Interfaces Transitively

If `Base implements Hashable` and `Derived extends Base`, then `Derived` is also assignable to `Hashable` even if it does not mention `implements Hashable` directly.

Runtime metadata for `Derived` should therefore contain the full effective interface set, not only directly declared interfaces.

Rationale:

- keeps typecheck/runtime behavior aligned
- simplifies interface casts and interface dispatch on subclass instances
- later overriding can update method tables while preserving the same effective interface model

## 8. Runtime Class Checks Walk A Superclass Chain

Class checked casts and `is` tests should stop using exact-type equality.

Instead:

- object exact-type tests remain available for `same_type`
- subtype-aware class checks walk `header->type`, then `super_type`, and so on

Recommended runtime metadata addition:

```c
const RtType* super_type;
```

Rationale:

- simple and correct for single inheritance
- avoids introducing a full subtype bitset or RTTI lattice too early
- later virtual dispatch can still layer a vtable or method-slot structure onto the same runtime type record

## 9. Constructor Chaining Should Be Explicit

Because explicit constructors already exist, inheritance should use explicit base-constructor chaining instead of silently synthesizing base-field writes in subclass constructors.

Recommended rule:

- every explicit subclass constructor must begin with `super(...)`
- that call is required before any field assignment or other statement
- classes with no declared constructors continue to get a compatibility constructor, now chained through the base compatibility constructor

Rationale:

- matches the explicit-constructor direction already chosen
- prepares directly for later override/virtual-dispatch semantics
- keeps base initialization owned by the base class

## 10. Separate Declared Members From Effective Members In Metadata

This slice should not treat `ClassInfo.methods` or semantic class methods as purely class-local forever.

Recommended direction:

- keep declared members as declared members
- build effective lookup tables that include inherited members and store declaring-owner information

Rationale:

- later overriding needs both declared and effective views
- inherited-method resolution should be data-driven rather than ad hoc

## Suggested Data Model Changes

These are suggested shapes, not mandatory exact names.

## Frontend AST

In [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py):

```python
@dataclass(frozen=True)
class ClassDecl:
    name: str
    fields: list[FieldDecl]
    methods: list[MethodDecl]
    is_export: bool
    span: SourceSpan
    base_class: TypeRefNode | None = None
    implements: list[TypeRefNode] = field(default_factory=list)
    constructors: list[ConstructorDecl] = field(default_factory=list)
```

Optionally add a dedicated constructor-first `super(...)` AST node later if constructor chaining is implemented in the same feature wave.

## Typecheck Model

In [compiler/typecheck/model.py](../compiler/typecheck/model.py), move away from a purely class-local `ClassInfo` view.

Suggested supporting records:

```python
@dataclass(frozen=True)
class FieldMemberInfo:
    owner_class_name: str
    type_info: TypeInfo
    is_private: bool
    is_final: bool
    layout_index: int


@dataclass(frozen=True)
class MethodMemberInfo:
    owner_class_name: str
    signature: FunctionSig
    is_private: bool
    is_static: bool


@dataclass(frozen=True)
class ClassInfo:
    name: str
    superclass_name: str | None
    declared_fields: dict[str, TypeInfo]
    declared_field_order: list[str]
    effective_fields: dict[str, FieldMemberInfo]
    effective_field_order: list[str]
    constructors: list[ConstructorInfo]
    declared_methods: dict[str, FunctionSig]
    effective_methods: dict[str, MethodMemberInfo]
    private_fields: set[str]
    final_fields: set[str]
    private_methods: set[str]
    implemented_interfaces: set[str]
    effective_interfaces: set[str]
```

The important part is not the exact shape; it is preserving both:

- the local declarations of a class
- the effective inherited view with declaring-owner metadata

## Semantic IR

In [compiler/semantic/ir.py](../compiler/semantic/ir.py) and [compiler/semantic/lowered_ir.py](../compiler/semantic/lowered_ir.py):

- add `superclass_id: ClassId | None` to semantic/lowered classes
- keep `methods` as declared methods only
- keep field and method accesses tagged with the declaring `owner_class_id` / `MethodId`
- keep `implemented_interfaces` as the effective transitive set

This is the representation that best prepares later override and virtual dispatch.

## Runtime Metadata

In [runtime/include/runtime.h](../runtime/include/runtime.h):

```c
struct RtType {
    uint32_t type_id;
    uint32_t flags;
    uint32_t abi_version;
    uint32_t align_bytes;
    uint64_t fixed_size_bytes;
    const char* debug_name;
    void (*trace_fn)(void* obj, void (*mark_ref)(void** slot));
    const uint32_t* pointer_offsets;
    uint32_t pointer_offsets_count;
    uint32_t reserved0;
    const RtType* super_type;
    const RtInterfaceImpl* interfaces;
    uint32_t interface_count;
    uint32_t reserved1;
};
```

If ABI padding needs reshaping, do that deliberately rather than squeezing `super_type` into a misleading reserved slot implicitly.

## What Must Change, And Where

## Frontend / Parser

Change:

- [compiler/frontend/tokens.py](../compiler/frontend/tokens.py)
- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
- [compiler/frontend/declaration_parser.py](../compiler/frontend/declaration_parser.py)

Work:

- add `extends` keyword
- parse optional superclass clause before `implements`
- if constructor chaining is in scope for the same rollout, parse `super(...)` as a constructor-only statement form

## Typecheck Declaration Collection

Change:

- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
- [compiler/typecheck/module_lookup.py](../compiler/typecheck/module_lookup.py)
- [compiler/typecheck/type_resolution.py](../compiler/typecheck/type_resolution.py)

Work:

- resolve superclass names using the same import/module rules as ordinary class references
- reject unknown superclasses
- reject self-inheritance and cycles
- reject non-class bases
- build classes in topological superclass order
- compute effective field/method/interface views from the base chain
- reject member collisions across the chain

## Type Relations And Visibility

Change:

- [compiler/typecheck/relations.py](../compiler/typecheck/relations.py)
- [compiler/typecheck/expressions.py](../compiler/typecheck/expressions.py)
- [compiler/typecheck/calls.py](../compiler/typecheck/calls.py)
- [compiler/typecheck/statements.py](../compiler/typecheck/bodies.py)

Work:

- make `Derived -> Base` assignable
- make explicit casts and `is` tests subtype-aware
- keep `same_type` exact
- resolve inherited fields/methods through effective member tables
- preserve declaring-class visibility rules for inherited private members
- add constructor-chaining validation for subclass constructors
- extend definite field-initialization logic to inherited required fields via `super(...)`

## Semantic Lowering

Change:

- [compiler/semantic/symbols.py](../compiler/semantic/symbols.py)
- [compiler/semantic/lowering/orchestration.py](../compiler/semantic/lowering/resolution.py)
- [compiler/semantic/lowering/references.py](../compiler/semantic/lowering/calls.py)
- [compiler/semantic/lowering/type_refs.py](../compiler/semantic/lowering/ids.py)

Work:

- record `superclass_id` on semantic classes
- ensure inherited field reads/writes lower with the base declaring `owner_class_id`
- ensure inherited method calls lower to the base declaring `MethodId`
- keep constructor IDs unchanged except for new superclass-aware semantics
- if constructor chaining is parsed explicitly, lower the validated `super(...)` call into a dedicated constructor-call form or early constructor statement form

## Semantic Optimization Helpers

Change:

- [compiler/semantic/optimizations/helpers/type_compatibility.py](../compiler/semantic/optimizations/helpers/type_compatibility.py)
- [compiler/semantic/optimizations/helpers/interface_dispatch.py](../compiler/semantic/optimizations/helpers/interface_dispatch.py)
- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](../compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

Work:

- make class/interface compatibility indexes transitive over superclasses
- ensure narrowing and devirtualization treat subclass instances as compatible with base types and inherited interfaces

## Codegen Metadata And Layout

Change:

- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_stmt.py)
- [compiler/codegen/emitter_fn.py](../compiler/codegen/layout.py)

Work:

- compute field offsets from effective field order, not declared-only fields
- keep inherited field offsets equal to base offsets
- use the declaring `owner_class_id` to load/store fields
- emit method labels only for declared methods, not inherited copies
- emit effective interface metadata for subclasses including base interfaces
- add `super_type` to emitted class metadata records

## Runtime

Change:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- runtime metadata tests under [tests/runtime](../tests/runtime)

Work:

- extend `RtType` with `super_type`
- add a helper that walks the superclass chain
- update checked casts and `is` tests for class types to use chain walking
- keep interface lookup unchanged except that subclass metadata now carries inherited interfaces too
- keep `rt_obj_same_type` exact

## Ordered Implementation Slices

## Slice 1: Syntax And Declaration Graph

Purpose:

- add superclass syntax and make class declaration order inheritance-aware

Checklist:

- [x] add `extends` token and parser support
- [x] extend `ClassDecl` with `base_class`
- [x] resolve superclass names through module/import lookup
- [x] reject unknown bases, non-class bases, self-inheritance, and cycles
- [x] establish topological class-processing order for declaration collection

Tests:

- parser tests for `extends` alone and `extends ... implements ...`
- parser rejection tests for duplicated/invalid superclass syntax
- typecheck tests for unknown superclass and cycle diagnostics
- multimodule tests for imported superclass resolution

How to test:

- unit tests in frontend parser and typecheck suites
- one multimodule positive/negative test in `tests/compiler/typecheck/test_program_imports.py`

## Slice 2: Effective Class Metadata And Subtyping

Purpose:

- teach the type system what a class hierarchy means

Checklist:

- [x] extend `ClassInfo` with superclass and effective member/interface views
- [x] compute effective field order with base-prefix semantics
- [x] compute effective method lookup with declaring-owner metadata
- [x] compute transitive effective interfaces
- [x] make `is_assignable` accept subclass-to-base assignment
- [x] make explicit casts and `is` tests class-hierarchy aware
- [x] keep exact-type semantics for `same_type`

Tests:

- assignability tests: `Derived -> Base`, `Derived -> Obj`, `Derived -> inherited-interface`
- cast/type-test tests for base/subclass pairs and `Obj`
- comparable/equality tests confirming exact `same_type` remains unchanged
- rejection tests for member name collisions across the chain

How to test:

- `tests/compiler/typecheck/test_expressions.py`
- `tests/compiler/typecheck/test_calls.py`
- `tests/compiler/typecheck/test_declarations.py`
- add focused semantic type-compatibility helper tests if needed

## Slice 3: Member Lookup And Semantic Ownership

Purpose:

- make inherited members usable without duplicating declarations

Checklist:

- [x] resolve inherited field reads/writes using the declaring base owner
- [x] resolve inherited instance methods to the declaring base `MethodId`
- [x] keep semantic/lowered classes annotated with `superclass_id`
- [x] keep semantic class method lists declaration-local only
- [x] propagate transitive interfaces into semantic classes and compatibility indexes

Tests:

- semantic lowering tests for inherited field owner IDs
- semantic lowering tests for inherited method call targets resolving to base `MethodId`
- optimizer helper tests that subclass interface compatibility remains visible
- no-duplication tests ensuring inherited methods are not re-emitted as subclass declarations

How to test:

- `tests/compiler/semantic/test_lowering.py`
- `tests/compiler/semantic/test_lowering_resolution.py`
- `tests/compiler/semantic/test_symbol_index.py` where owner identity matters
- semantic optimization helper tests for type compatibility and interface dispatch

## Slice 4: Constructor Chaining And Initialization

Purpose:

- make subclass object construction semantically correct with inherited layout

Checklist:

- [ ] introduce constructor-only `super(...)` chaining syntax/validation
- [ ] require explicit subclass constructors to begin with `super(...)`
- [ ] define chained compatibility constructors for classes with no declared constructors
- [ ] ensure base fields are initialized only by the base constructor path
- [ ] extend constructor field-initialization analysis across inherited required fields
- [ ] forbid direct assignment to inherited final fields outside allowed constructor ownership rules

Tests:

- positive constructor-chaining tests across one and two inheritance levels
- rejection tests for missing first-statement `super(...)`
- rejection tests for duplicate/misordered base initialization
- tests confirming inherited default field initializers are preserved
- multimodule constructor inheritance tests

How to test:

- `tests/compiler/typecheck/test_statements.py`
- `tests/compiler/typecheck/test_visibility.py`
- `tests/compiler/semantic/test_lowering.py`
- later golden/integration tests once the runtime path is complete

## Slice 5: Codegen Layout And Runtime Instance Checks

Purpose:

- make subclass instances behave correctly at runtime

Checklist:

- [ ] compute effective field offsets from base-prefix layout
- [ ] emit `super_type` in runtime type metadata
- [ ] update class checked-cast runtime helpers to walk the superclass chain
- [ ] update class type tests to walk the superclass chain
- [ ] emit transitive interface metadata on subclass runtime types
- [ ] keep inherited method emission direct-to-declaring-label only

Tests:

- codegen tests for inherited field offsets staying stable between base and derived
- codegen tests for inherited method calls using the base method label
- runtime C tests for `rt_checked_cast` and `rt_is_instance_of_type` through a superclass chain
- runtime C tests for subclass interface metadata inheritance
- integration tests for `Obj -> Base` cast success on a `Derived` instance

How to test:

- `tests/compiler/codegen/`
- `tests/runtime/`
- `tests/compiler/integration/test_cli_semantic_codegen_runtime.py`

## Slice 6: Golden And End-To-End Coverage

Purpose:

- validate the feature on realistic source programs and freeze user-visible behavior

Checklist:

- [ ] add a positive golden source for single inheritance behavior
- [ ] include inherited field reads, inherited method calls, subclass-to-base assignment, inherited interface dispatch, and subtype-aware casts/type tests
- [ ] add constructor-chaining golden cases once `super(...)` is implemented
- [ ] update language/docs references after behavior is stable

Tests:

- one golden file for positive runtime behavior
- unit tests remain the main place for negative compile-time diagnostics unless the golden harness is extended for compile-fail expectations

How to test:

- `tests/golden/lang/`
- `./scripts/golden.sh --filter 'lang/test_*.nif'`

## Specific Behavioral Decisions To Lock Early

These should be decided before implementation starts to avoid churn.

1. Duplicate inherited member names are compile-time errors in this slice, even when the base member is private.
2. `same_type(a, b)` remains exact-type only; it is not widened to "same type or subtype".
3. Subclasses inherit all base interfaces transitively in both typecheck and runtime metadata.
4. Inherited methods lower to the declaring class's `MethodId`; no subclass alias symbols are emitted.
5. Field offsets are keyed by declaring owner and effective layout index, not by the receiver's concrete class alone.
6. Subclass constructors initialize base state through `super(...)`, not by directly reassigning base fields.

## Tradeoffs

## Strict No-Redeclaration Rule Now vs Earlier Override Surface

Recommended choice: reject redeclaration now.

Pros:

- simple and unambiguous
- avoids pseudo-overrides before virtual dispatch exists
- preserves a clean later path for an explicit `override` feature

Cons:

- slightly stricter than some OO languages
- may reject patterns that could eventually be legal with overriding or protected visibility

## Superclass Chain Walk Now vs Richer RTTI Indexing

Recommended choice: chain walk now.

Pros:

- simple runtime implementation
- enough for single inheritance
- easy to validate

Cons:

- subtype checks are linear in hierarchy depth
- later optimization may want cached subtype IDs or bitsets

This is acceptable because hierarchy depth will be small in the short term, and the semantic/runtime model stays extensible.

## Declaring-Owner Method Resolution Now vs Synthetic Subclass Aliases

Recommended choice: declaring-owner resolution.

Pros:

- preserves one canonical method identity per declaration
- matches future override/vtable lookup better
- avoids duplicate code emission

Cons:

- requires effective-method metadata rather than naive subclass-local lookup

This is the right tradeoff for future virtual dispatch work.

## Test Strategy Summary

The feature should be validated at four layers.

## 1. Frontend And Typecheck

- syntax, cycles, name collisions, visibility, assignability, casts, and constructor-chaining diagnostics

## 2. Semantic Lowering And Optimization Helpers

- declaring-owner correctness for inherited fields/methods
- transitive interface compatibility visibility

## 3. Backend And Runtime

- base-prefix layout offsets
- inherited method label selection
- superclass-chain runtime cast/type-test behavior
- transitive interface metadata on subclasses

## 4. Golden / Integration

- user-visible behavior across inheritance, casts, inherited methods, and interface dispatch

## Recommended First Execution Order

If implemented now, the recommended order is:

1. Slice 1: syntax and declaration graph
2. Slice 2: effective metadata and subtyping
3. Slice 3: member lookup and semantic ownership
4. Slice 5: runtime class checks and codegen layout for non-constructor paths
5. Slice 4: constructor chaining and inherited initialization
6. Slice 6: golden/integration polish

That order gets subtype behavior and layout/runtime correctness working first, while leaving constructor-chaining as the only deliberately larger follow-up within the same inheritance feature wave.