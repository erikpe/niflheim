# Explicit Constructors Plan

This document defines a concrete design and implementation plan for adding explicit constructors with constructor-only overload resolution.

The design is intentionally scoped as preparation for later class inheritance.

The main goal is to replace the current single implicit field-derived constructor model with an explicit constructor model that the compiler, semantic IR, and codegen can represent directly.

This plan does not add general method overloading.

## Status

Planned.

The current compiler still uses one implicit constructor per class, derived from fields without declaration-time initializers.

## Why This Plan Exists

The current constructor model is a good MVP simplification, but it becomes a liability once inheritance is introduced.

Today, all of the following assumptions are baked into the pipeline:

- one constructor per class
- constructor parameters are derived from fields, not declared explicitly
- constructor visibility is approximated from private-field presence
- constructor codegen is synthesized from field metadata, not from an explicit body

That works for flat classes, but it does not scale cleanly to:

- multiple construction paths for one class
- constructor-specific visibility
- constructor-local initialization logic
- later `super(...)` chaining for inheritance
- later reasoning about definite field initialization across constructor bodies

Explicit constructors solve the real structural problem without forcing the much larger redesign needed for general method overloading.

## Goals

- Add explicit constructor declarations as class members.
- Allow multiple constructors per class.
- Restrict overloading to constructors only.
- Keep ordinary methods name-unique for now.
- Preserve existing source compatibility for classes that declare no constructors.
- Lower constructors as first-class executable owners in semantic IR.
- Emit constructor code from explicit bodies rather than synthesizing it from field order.
- Define overload resolution now in a way that remains valid after inheritance is added.

## Non-Goals

- No general method overloading.
- No named arguments.
- No default parameter values.
- No constructor delegation between overloads in this slice.
- No `super(...)` in this slice.
- No class inheritance in this slice.
- No static constructors.
- No first-class constructor values.

## Current Baseline

The current implementation centers around one implicit constructor per class.

### Frontend And AST

- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
  - `ClassDecl` contains `fields` and `methods`, but no constructor declarations.
- [compiler/frontend/declaration_parser.py](../compiler/frontend/declaration_parser.py)
  - class members are parsed as field or method only.

### Typecheck Model

- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
  - `ClassInfo` stores `constructor_param_order` and `constructor_is_private`.
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
  - constructor parameters are derived from fields whose declarations omit initializers.
- [compiler/typecheck/call_helpers.py](../compiler/typecheck/call_helpers.py)
  - constructor calls are checked against that one field-derived parameter list.

### Semantic Symbols And Lowering

- [compiler/semantic/symbols.py](../compiler/semantic/symbols.py)
  - `ConstructorId` is keyed only by `(module_path, class_name)`.
- [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py)
  - class-call resolution assumes one constructor target per class.

### Codegen

- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - `DeclarationTables` stores one `ConstructorLayout` per class.
- [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py)
  - constructor emission is synthesized from field metadata and declaration-time initializers.

Those assumptions are exactly what this plan replaces.

## Main Design Decisions

## 1. Add A Dedicated `constructor` Class Member

Recommended surface syntax:

```nif
class Box {
    value: i64;
    next: Box;

    constructor(value: i64, next: Box) {
        __self.value = value;
        __self.next = next;
    }

    private constructor(value: i64) {
        __self.value = value;
        __self.next = null;
    }
}
```

Rationale:

- it is explicit and unambiguous
- it fits the current class-member grammar shape
- it does not overload the meaning of ordinary methods
- it provides a clean insertion point for future `super(...)`

Constructors are class members, but they are not ordinary methods:

- they have no name
- they have no explicit return type
- they are not `static`
- they are only callable through class construction syntax

## 2. Keep Method Overloading Out Of Scope

Constructor overloading is useful here because constructor identity is already special and the current constructor model must change anyway.

General method overloading would force a much larger redesign across:

- member lookup
- `MethodId`
- interface conformance
- interface dispatch lookup
- ambiguity and specificity rules for instance and static calls

That work is not necessary to prepare for inheritance.

Ordinary methods should therefore remain unique by name inside a class.

## 3. Preserve Backward Compatibility For Classes Without Constructors

For the initial rollout:

- if a class declares zero constructors, synthesize one compatibility constructor using the current field-derived behavior
- if a class declares one or more constructors, do not synthesize the legacy constructor

Internally, both explicit and compatibility constructors should use the same constructor representation. This avoids a second cleanup pass later.

## 4. Make Constructors First-Class Executable Owners

Constructors should stop being a codegen-only synthesis artifact.

They should become explicit executable units in the pipeline, parallel to functions and methods.

That means:

- constructors get semantic symbol IDs
- constructors own locals
- constructors lower into semantic IR and lowered IR
- constructor bodies are typechecked and emitted directly

This is the main architectural change that prepares the compiler for inheritance.

## 5. Define Overload Resolution Now With Future Subtyping In Mind

Constructor overload resolution should not be exact-match-only.

Recommended selection rule:

1. filter by arity
2. keep only candidates whose parameter types are applicable under existing assignability rules
3. select the unique most-specific candidate
4. if no candidate remains, emit a normal no-match error
5. if multiple candidates remain without a unique most-specific winner, emit an ambiguity error

Recommended specificity rule:

- candidate `A` is more specific than candidate `B` if each `A` parameter type is assignable to the corresponding `B` parameter type, and at least one position is strictly narrower

This rule matters because it still works after inheritance introduces subtype relations like `Derived -> Base`.

## Surface Syntax

## Constructor Declaration

```nif
constructor(param1: T1, param2: T2) {
    ...
}
```

## Private Constructor

```nif
private constructor(secret: Str) {
    ...
}
```

## Multiple Constructors

```nif
class Counter {
    value: i64;

    constructor() {
        __self.value = 0;
    }

    constructor(value: i64) {
        __self.value = value;
    }
}
```

## Compatibility Constructor

This still remains valid with no source changes:

```nif
class Pair {
    left: Obj;
    right: Obj;
}

var p: Pair = Pair(a, b);
```

The compiler synthesizes one compatibility constructor only because the class declares no constructors.

## AST And Parser Changes

## New Token

Add `constructor` as a dedicated keyword in [compiler/frontend/tokens.py](../compiler/frontend/tokens.py).

## New AST Node

Recommended addition in [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py):

```python
@dataclass(frozen=True)
class ConstructorDecl:
    params: list[ParamDecl]
    body: BlockStmt
    is_private: bool
    span: SourceSpan
```

Then extend `ClassDecl`:

```python
@dataclass(frozen=True)
class ClassDecl:
    name: str
    fields: list[FieldDecl]
    methods: list[MethodDecl]
    constructors: list[ConstructorDecl]
    is_export: bool
    span: SourceSpan
    implements: list[TypeRefNode] = field(default_factory=list)
```

## Parser Shape

Extend [compiler/frontend/declaration_parser.py](../compiler/frontend/declaration_parser.py) so class members become:

- field declaration
- constructor declaration
- method declaration

Recommended class-member rule:

```ebnf
class_member = field_decl
             | constructor_decl
             | method_decl
             ;

constructor_decl = [ "private" ] "constructor" "(" [ param_list ] ")" block ;
```

`final` should remain illegal on constructors.

## Typecheck Model Changes

## Replace Single-Constructor Metadata

In [compiler/typecheck/model.py](../compiler/typecheck/model.py), replace:

- `constructor_param_order`
- `constructor_is_private`

with an explicit constructor collection.

Recommended shape:

```python
@dataclass(frozen=True)
class ConstructorInfo:
    ordinal: int
    params: list[TypeInfo]
    param_names: list[str]
    is_private: bool


@dataclass(frozen=True)
class ClassInfo:
    name: str
    fields: dict[str, TypeInfo]
    field_order: list[str]
    methods: dict[str, FunctionSig]
    constructors: list[ConstructorInfo]
    private_fields: set[str]
    final_fields: set[str]
    private_methods: set[str]
    implemented_interfaces: set[str]
```

The methods table stays name-based and unique.

## Constructor Collection Rules

In [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py):

- collect explicit constructors from `ClassDecl.constructors`
- assign stable source-order ordinals
- reject duplicate constructor signatures by parameter types
- synthesize one compatibility constructor only if no explicit constructor is declared

Recommended duplicate-signature rule:

- same arity and same parameter types means duplicate constructor declaration

That is enough while only constructors overload.

## Constructor Body Semantics

Constructors should be checked as function-like bodies with an implicit `__self` receiver of the owning class type.

Recommended rules:

- `__self` is available in every constructor body
- `return expr;` is illegal
- bare `return;` may be allowed as an early exit
- constructor parameters are scoped exactly like function parameters
- ordinary visibility rules apply inside constructor bodies

## Field Initialization Rules

This is the most important semantic design choice for later inheritance.

Recommended behavior:

- declaration-time field initializers count as already initialized defaults
- every field without a declaration-time initializer must be definitely assigned by each constructor on all normal exit paths
- `final` fields without declaration-time initializers must be assigned exactly once in each constructor

This creates one consistent model that later `super(...)` and inherited fields can extend.

## Overload Resolution Design

Constructor overload resolution lives in typechecking and should be reused by lowering.

## Applicability

A constructor overload is applicable if:

- arity matches
- each argument type is assignable to the corresponding parameter type using the existing assignability relation

## Selection

Among applicable overloads:

- choose the unique most-specific candidate
- if no unique most-specific candidate exists, report ambiguity

## Diagnostics

Recommended error classes:

- no constructor overload matches argument types
- constructor call is ambiguous
- constructor is private and not visible from the call site

For ambiguity, the diagnostic should list the competing signatures.

## Why This Is The Right Rule Before Inheritance

Once inheritance exists, overload sets like these should continue to work without redesign:

```nif
constructor(x: Obj) { ... }
constructor(x: Base) { ... }
constructor(x: Derived) { ... }
```

The unique most-specific rule already provides the right shape for that future.

## Semantic Symbol Changes

Constructors need overload-aware identity.

## ConstructorId

In [compiler/semantic/symbols.py](../compiler/semantic/symbols.py), change:

```python
@dataclass(frozen=True)
class ConstructorId:
    module_path: ModulePath
    class_name: str
```

to:

```python
@dataclass(frozen=True)
class ConstructorId:
    module_path: ModulePath
    class_name: str
    ordinal: int
```

This keeps constructor identity source-stable and simple.

## Local Owner Identity

Extend `LocalOwnerId` so constructors can own locals.

Without that change, constructor bodies cannot participate in the same local-ID and lowering machinery as functions and methods.

## ProgramSymbolIndex

Change `ProgramSymbolIndex.constructors` so it maps overload-aware constructor IDs to constructor declarations, not to whole classes.

That keeps symbol indexing honest once multiple constructors exist.

## Semantic IR Changes

Add explicit constructor nodes to [compiler/semantic/ir.py](../compiler/semantic/ir.py) and [compiler/semantic/lowered_ir.py](../compiler/semantic/lowered_ir.py).

Recommended shape:

```python
@dataclass(frozen=True)
class SemanticConstructor:
    constructor_id: ConstructorId
    params: list[SemanticParam]
    body: SemanticBlock
    is_private: bool
    span: SourceSpan
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)
```

Then add:

```python
constructors: list[SemanticConstructor]
```

to `SemanticClass` and its lowered equivalent.

This change is what turns constructors into real pipeline citizens rather than codegen synthesis.

## Lowering Changes

In [compiler/semantic/lowering/orchestration.py](../compiler/semantic/lowering/orchestration.py):

- lower explicit constructors in source order
- assign stable constructor ordinals
- lower constructor bodies with implicit `__self`

In [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py):

- resolve class calls to one overload-aware `ConstructorId`

In [compiler/semantic/lowering/ids.py](../compiler/semantic/lowering/ids.py):

- add overload-aware constructor-ID helpers

## Codegen Changes

## Constructor Layouts

In [compiler/codegen/model.py](../compiler/codegen/model.py), `ConstructorLayout` remains useful, but it must now be keyed by overload-specific `ConstructorId` values.

It should carry:

- constructor label
- owning class type symbol
- payload size
- parameter-slot information for this overload

It should no longer assume that parameters are always the set of non-default-initialized fields.

## Declaration Tables

In [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py):

- emit one `ConstructorLayout` per constructor overload
- assign one constructor label per overload
- keep field offsets keyed by declaring class and field name as today

Suggested label mangling should include the constructor ordinal.

## Constructor Emission

In [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py), stop synthesizing constructor bodies by iterating fields.

Instead:

1. allocate the object
2. root the allocated object
3. bind it as `__self`
4. execute the lowered constructor body
5. return the allocated object

That keeps allocation semantics centralized while making constructor logic explicit.

## Compatibility Strategy

To avoid a disruptive rollout:

- classes with no explicit constructors continue to behave as they do today
- internally, those legacy constructors should still be lowered into the explicit constructor pipeline as ordinal `0`

That means later inheritance work can treat every class uniformly, regardless of whether the constructor was user-declared or synthesized.

## Why This Prepares The Compiler For Inheritance

This plan is deliberately designed around the future problems inheritance introduces.

It sets up the right seams for:

- superclass constructor chaining
- inherited field initialization guarantees
- subclass-specific construction paths
- overload resolution over future subtype relations

Most importantly, it prevents inheritance from having to redesign constructor identity and constructor codegen at the same time.

## Step-By-Step Checklist

1. Add the `constructor` keyword and parser support.
2. Add `ConstructorDecl` and `ClassDecl.constructors`.
3. Preserve legacy compatibility by synthesizing one constructor only when no explicit constructor is declared.
4. Replace single-constructor `ClassInfo` fields with `ConstructorInfo` collection metadata.
5. Reject duplicate constructor signatures.
6. Implement constructor-only overload resolution with unique most-specific selection.
7. Add constructor visibility handling independent of private fields.
8. Add constructor body typechecking with implicit `__self`.
9. Add definite field-initialization checks for explicit constructors.
10. Extend `ConstructorId`, `LocalOwnerId`, and `ProgramSymbolIndex` to represent explicit constructors directly.
11. Add semantic and lowered IR constructor nodes.
12. Lower constructor calls to a specific overload ordinal.
13. Emit one constructor layout and label per overload.
14. Replace synthetic field-store constructor emission with explicit constructor-body emission.
15. Update docs and add regression coverage.

## PR-Sized Checklist For Phases 1-3

This section turns the first three phases into a sequence of small implementation PRs.

The intent is:

- keep each PR mechanically reviewable
- preserve a working compiler after each merge
- defer overload selection and constructor-body semantics until the basic representation changes are in place

## PR 1: Frontend Syntax And AST

Scope:

- add constructor syntax only
- do not change typechecking behavior yet beyond carrying new AST data
- do not remove the legacy implicit-constructor path

Implementation checklist:

1. Add `TokenKind.CONSTRUCTOR` and the `constructor` keyword in [compiler/frontend/tokens.py](../compiler/frontend/tokens.py).
2. Add `ConstructorDecl` in [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py).
3. Add `constructors: list[ConstructorDecl]` to `ClassDecl` in [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py).
4. Update [compiler/frontend/declaration_parser.py](../compiler/frontend/declaration_parser.py) so class members can be field, constructor, or method.
5. Reuse existing callable-signature parsing for constructor parameter lists, but reject return types on constructors.
6. Reject invalid modifiers on constructors, especially `final` and `static`.
7. Keep classes with no constructors parsing exactly as before.

Suggested file set:

- [compiler/frontend/tokens.py](../compiler/frontend/tokens.py)
- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
- [compiler/frontend/declaration_parser.py](../compiler/frontend/declaration_parser.py)

Suggested tests:

- [tests/compiler/frontend/parser/test_parser.py](../tests/compiler/frontend/parser/test_parser.py)
- [tests/compiler/frontend/parser/test_parser_shape.py](../tests/compiler/frontend/parser/test_parser_shape.py)

Add test cases for:

- single constructor in a class
- multiple constructors in source order
- `private constructor(...) { ... }`
- mixed field, constructor, and method members
- invalid `constructor(...) -> T`
- invalid `static constructor`
- invalid `final constructor`
- regression coverage showing classes without constructors still parse unchanged

Review boundary:

- AST and parser only
- no semantic or codegen behavior changes expected

## PR 2: Typecheck Model And Compatibility Constructor Collection

Scope:

- replace the single-constructor metadata model
- collect explicit constructors into `ClassInfo`
- preserve compatibility constructor synthesis for classes that declare none
- reject duplicate constructor signatures
- do not implement overload resolution yet beyond simple collection and storage

Implementation checklist:

1. Add `ConstructorInfo` in [compiler/typecheck/model.py](../compiler/typecheck/model.py).
2. Replace `constructor_param_order` and `constructor_is_private` in `ClassInfo` with `constructors: list[ConstructorInfo]` in [compiler/typecheck/model.py](../compiler/typecheck/model.py).
3. Update [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py) to collect explicit constructor declarations from `ClassDecl.constructors`.
4. Assign stable source-order ordinals during collection.
5. Synthesize one compatibility constructor when `ClassDecl.constructors` is empty.
6. Reject duplicate constructor signatures by parameter types.
7. Keep ordinary methods name-unique and unchanged.
8. Keep existing interface-conformance logic unchanged except where it reads `ClassInfo` construction metadata.

Suggested file set:

- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)

Suggested tests:

- [tests/compiler/typecheck/test_declarations.py](../tests/compiler/typecheck/test_declarations.py)
- [tests/compiler/typecheck/test_visibility.py](../tests/compiler/typecheck/test_visibility.py)

Add test cases for:

- class with no declared constructors gets one compatibility constructor
- class with one explicit constructor gets exactly one collected constructor and no compatibility constructor
- class with multiple explicit constructors is accepted
- duplicate explicit constructor signatures are rejected
- constructor privacy is stored per constructor rather than derived from private fields
- existing method-duplicate rejection still behaves the same

Review boundary:

- type model and declaration collection only
- still no overload call-site selection logic

## PR 3: Constructor Call Resolution And Visibility

Scope:

- implement constructor-only overload resolution at call sites
- preserve method call resolution as-is
- add private-constructor visibility checking using the new constructor metadata
- keep constructor bodies and field-initialization analysis out of scope for this PR

Implementation checklist:

1. Add constructor overload applicability helpers in [compiler/typecheck/call_helpers.py](../compiler/typecheck/call_helpers.py).
2. Implement unique most-specific constructor selection in [compiler/typecheck/call_helpers.py](../compiler/typecheck/call_helpers.py).
3. Update [compiler/typecheck/calls.py](../compiler/typecheck/calls.py) so class calls resolve through constructor overload selection instead of the old single-signature path.
4. Update constructor visibility checks to use the selected constructor overload rather than a class-wide boolean.
5. Keep class-call surface syntax unchanged so `Box(...)` still means constructor call.
6. Keep imported constructor lookup and local-first type-name resolution behavior unchanged.
7. Add clear diagnostics for no-match and ambiguous-match constructor calls.

Suggested file set:

- [compiler/typecheck/call_helpers.py](../compiler/typecheck/call_helpers.py)
- [compiler/typecheck/calls.py](../compiler/typecheck/calls.py)
- [compiler/typecheck/test_program_imports.py](../compiler/typecheck/test_program_imports.py)

Suggested tests:

- [tests/compiler/typecheck/test_calls.py](../tests/compiler/typecheck/test_calls.py)
- [tests/compiler/typecheck/test_program_imports.py](../tests/compiler/typecheck/test_program_imports.py)
- [tests/compiler/typecheck/test_visibility.py](../tests/compiler/typecheck/test_visibility.py)

Add test cases for:

- exact-match constructor wins
- more-specific constructor wins over broader one
- ambiguous constructor call reports a dedicated ambiguity error
- explicit cast disambiguates an ambiguous constructor call
- private overload rejected when it is the selected match outside the class
- public overload accepted when it is the selected match
- imported overloaded constructors resolve correctly across modules
- existing classes with compatibility constructors still call successfully

Review boundary:

- typecheck call selection and visibility only
- no semantic symbol, lowering, or codegen changes yet

## Exit Criteria After PR 3

At the end of these three PRs, the compiler should have:

- constructor syntax in the frontend
- explicit constructor metadata in the typechecker
- compatibility constructors for legacy classes
- constructor-only overload resolution at class call sites
- per-constructor visibility rules

At that point the next natural PR can introduce constructor bodies as first-class semantic owners and start the semantic/codegen migration.

## Tests To Add By Step

## 1. Parser And AST

Add tests in:

- [tests/compiler/frontend/parser/test_parser.py](../tests/compiler/frontend/parser/test_parser.py)
- [tests/compiler/frontend/parser/test_parser_shape.py](../tests/compiler/frontend/parser/test_parser_shape.py)

Suggested cases:

- parse one constructor
- parse multiple constructors
- parse `private constructor`
- reject `constructor(...) -> T`
- reject `static constructor`
- reject `final constructor`
- ensure mixed field, constructor, and method ordering parses correctly

## 2. Declaration Collection

Add tests in:

- [tests/compiler/typecheck/test_declarations.py](../tests/compiler/typecheck/test_declarations.py)

Suggested cases:

- class with zero explicit constructors gets one compatibility constructor
- class with one explicit constructor gets no compatibility constructor
- class with multiple explicit constructors is accepted
- duplicate constructor signatures are rejected
- ordinary duplicate method names are still rejected

## 3. Overload Resolution

Add tests in:

- [tests/compiler/typecheck/test_calls.py](../tests/compiler/typecheck/test_calls.py)
- [tests/compiler/typecheck/test_program_imports.py](../tests/compiler/typecheck/test_program_imports.py)

Suggested cases:

- exact-match overload wins
- narrower overload wins over broader overload
- ambiguity is reported when two overloads are equally applicable
- explicit cast can disambiguate an otherwise ambiguous call
- imported constructor overloads resolve correctly
- local-first class-name resolution still works with overloaded constructors

## 4. Visibility And Bodies

Add tests in:

- [tests/compiler/typecheck/test_visibility.py](../tests/compiler/typecheck/test_visibility.py)
- [tests/compiler/typecheck/test_statements.py](../tests/compiler/typecheck/test_statements.py)

Suggested cases:

- private constructor rejected outside class
- private constructor accepted inside owning class
- constructor body can access private fields and methods of same class
- `return expr;` rejected in constructor body
- missing required field initialization rejected
- `final` field assigned twice in constructor rejected

## 5. Semantic Symbols And Lowering

Add tests in:

- [tests/compiler/semantic/test_symbol_index.py](../tests/compiler/semantic/test_symbol_index.py)
- [tests/compiler/semantic/test_lowering.py](../tests/compiler/semantic/test_lowering.py)
- [tests/compiler/semantic/test_lowering_ids.py](../tests/compiler/semantic/test_lowering_ids.py)
- [tests/compiler/semantic/test_local_ids.py](../tests/compiler/semantic/test_local_ids.py)

Suggested cases:

- constructor IDs include stable ordinals
- compatibility constructors lower as ordinal `0`
- overloaded constructor calls resolve to the chosen ordinal
- constructor locals are owned by constructor IDs

## 6. Codegen

Add tests in:

- [tests/compiler/codegen/test_program_generator.py](../tests/compiler/codegen/test_program_generator.py)
- [tests/compiler/codegen/test_generator.py](../tests/compiler/codegen/test_generator.py)
- [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py)
- [tests/compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)

Suggested cases:

- one layout per constructor overload
- constructor labels include overload identity
- constructor calls target the chosen overload label
- allocated object remains rooted during constructor body execution
- explicit constructor body field stores replace legacy synthetic field iteration

## 7. Golden And End-To-End

Add at least:

- one positive golden using multiple constructors
- one negative golden showing constructor ambiguity
- one positive golden showing backward compatibility for a class with no explicit constructors

## Open Design Choices

## 1. Compatibility Constructor Policy

Two viable rollout shapes exist:

1. keep implicit compatibility constructors for classes with no declared constructors
2. require constructors to be declared explicitly once the feature ships

Recommendation:

- choose option 1 for the first implementation to minimize breakage
- internally lower both paths into the same constructor representation

## 2. Bare `return;` In Constructors

Two viable choices exist:

1. allow bare `return;` as an early exit
2. forbid `return` entirely inside constructors

Recommendation:

- allow bare `return;` if it can reuse existing function-like statement machinery cleanly
- otherwise forbid `return` in the first slice and add it later if desired

## 3. Field Initialization Analysis Scope

Two viable first slices exist:

1. full definite field-initialization checking across structured control flow
2. narrow straight-line-only initialization rules for explicit constructors

Recommendation:

- implement proper definite field-initialization checking now if practical
- if time-constrained, start with a narrower rule but keep the checking entry points clearly separated so inheritance can extend them later

## Summary

The right first step before inheritance is not general method overloading.

It is explicit constructors with constructor-only overload resolution.

That change solves the real structural issue in the current class pipeline, establishes overload-aware constructor identity, makes constructor bodies explicit semantic units, and creates a clean path for later superclass construction and field-initialization rules.