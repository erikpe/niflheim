# Semantic Pipeline Refactor Plan

This document describes a concrete plan to simplify the compiler pipeline by introducing a semantic lowering stage between typechecking and reachability/codegen.

The immediate goal is to stop making reachability recover semantic meaning from partially lowered source ASTs. The medium-term goal is to make fine-grained reachability, codegen, and future optimization work operate on one normalized representation with explicit symbol identity.

This plan assumes the current coarse reachability has been restored and treats that as the correct starting point.

## Goals

- Move semantic normalization to one dedicated stage after typechecking.
- Ensure global symbol references are resolved to canonical identities before reachability.
- Make hidden lowering dependencies explicit instead of introducing them ad hoc in codegen.
- Let reachability traverse resolved semantic operations rather than raw source syntax.
- Reduce duplication between typecheck, reachability, and codegen call-resolution logic.
- Create a stable seam for future optimizations and diagnostics.

## Non-Goals

- Do not redesign the entire backend IR in one step.
- Do not rewrite typechecking and codegen at the same time without migration boundaries.
- Do not introduce CFG-based optimization infrastructure as part of this first refactor.
- Do not try to solve every future language feature up front.

## Current Problems

The current compiler pipeline is effectively:

- parse source AST
- resolve modules
- typecheck source AST
- reachability on source-ish AST
- module merge
- codegen with additional lowering

That creates several forms of duplicated semantic work.

### 1. Semantic Meaning Is Split Across Stages

Today:

- some sugar is lowered in the parser
- some name/type resolution exists only in typecheck state
- some callable dependencies are introduced only during codegen

As a result, reachability is forced to reconstruct information that another stage already knew earlier or will invent later.

### 2. Reachability Is Operating At The Wrong Abstraction Level

The current coarse walker in `compiler/reachability.py` works on syntax and local heuristics:

- bare function/class names
- flattened field chains
- local variable type guesses

This is inherently brittle for:

- static method calls
- instance method calls on chained receivers
- constructor calls
- structural sugar
- synthetic codegen dependencies such as string literal lowering and string concatenation lowering

### 3. Canonical Ownership Exists Only Partially

Typechecking already uses module-qualified names such as `owner.module::Class`, but that information is not the primary representation for later stages. Later stages fall back to leaf names or reconstruct ownership from AST shape.

### 4. Codegen Still Performs Semantic Recovery

Codegen currently resolves call targets and lowers synthetic operations like:

- string literals -> `Str.from_u8_array`
- string `+` -> `Str.concat`
- structural indexing/slicing into method-call forms

This means codegen still owns semantic behavior that should already be explicit before emission starts.

## Refactor Principles

### 1. Keep Parse Mostly Surface-Faithful

The parser should produce a source-oriented AST that mirrors the user program as much as practical.

It is acceptable to keep harmless syntactic normalization in parsing, but semantic lowering should not be spread between parser and backend.

### 2. Resolve Symbol Identity Once

Every cross-module function, class, method, and constructor reference should have a canonical identity by the time semantic lowering finishes.

Prefer typed symbol IDs or dataclasses over string parsing.

### 3. Lower Semantics Once

Constructs that imply semantic desugaring should become explicit in one dedicated lowering pass, not partly in parser, partly in reachability, and partly in codegen.

### 4. Reachability Should Traverse Resolved Operations

Reachability should become a graph walk over explicit semantic edges:

- function call edges
- method call edges
- constructor edges
- class/type metadata dependencies
- synthetic helper edges

It should not need to infer semantics from field chains and local type guesses.

### 5. Codegen Should Emit, Not Reinterpret

Codegen should primarily map already-resolved operations to assembly/runtime calls. If codegen still contains semantic reconstruction logic, the stage boundary is wrong.

## Target Pipeline

The target pipeline should become:

- parse source AST
- resolve modules
- typecheck source AST
- lower to semantic IR
- analyze reachability on semantic IR
- prune semantic IR using reachability facts
- emit code from semantic IR

Conceptually:

```python
program = resolve_program(entry)
typed_program = typecheck_program(program)
semantic_program = lower_program(typed_program)
reachability = analyze_reachability(semantic_program)
pruned_program = prune_unreachable(semantic_program, reachability)
codegen_module = build_codegen_module(pruned_program)
emit_asm(codegen_module)
```

The exact function names can differ, but the stage ownership should match this shape.

The ordered implementation checklist for bypassing reachability during backend migration now lives in `docs/SEMANTIC_CODEGEN_MIGRATION_CHECKLIST.md`.

Current implementation state:

- semantic codegen is now the default checked backend path
- the semantic path currently runs:
    - resolve
    - typecheck
    - lower to semantic IR
    - semantic codegen
- reachability is still intentionally bypassed on that path
- the legacy source-AST backend remains behind `--source-ast-codegen` only as a temporary rollback path
- compiler pytest, golden tests, runtime smoke tests, and runtime harness validation are green with the semantic backend as the preferred path

## Core Design

### 1. Introduce A Semantic IR Layer

Add a new post-typecheck representation whose job is to preserve source structure where useful but replace ambiguous syntax with explicit semantics.

This does not need to be a low-level backend IR.

It should be a normalized semantic tree or graph with:

- canonical symbol references
- explicit call targets
- explicit constructor calls
- explicit structural operations
- explicit synthetic helper dependencies when needed
- stable result type information where later passes need it

Suggested location:

- `compiler/semantic_ir.py`
- `compiler/semantic_lowering.py`

### 2. Canonical Symbol Identity

Introduce shared symbol identity types used by semantic lowering, reachability, and later codegen.

The exact ID definitions live in `docs/SEMANTIC_IR_SPEC.md`. The architectural decision here is simply that all post-typecheck global symbol identity should flow through typed canonical IDs, not leaf names or fully qualified strings used as ad hoc keys.

### 3. Normalize Call Shapes

Lowering should replace syntax-dependent call interpretation with explicit resolved call nodes.

The exact node families are defined in `docs/SEMANTIC_IR_SPEC.md`. The important pipeline constraint is that later stages should never need to inspect a generic callee expression and guess whether it names a function, static method, instance method, constructor, or helper-backed operation.

### 4. Lower Structural Sugar Explicitly

Structural sugar should not survive into reachability as ambiguous source syntax.

Examples:

- `obj[index]` -> explicit resolved `index_get`
- `obj[index] = value` -> explicit resolved `index_set`
- `obj[begin:end]` -> explicit resolved `slice_get`
- `obj[begin:end] = value` -> explicit resolved `slice_set`
- `for elem in coll` -> explicit iteration form with resolved `iter_len` and `iter_get`

This can still preserve high-level structure. It does not need to lower all the way to while-loops yet. The semantic IR spec defines the concrete nodes involved.

### 5. Make Synthetic Dependencies Explicit

Any operation that codegen currently expands into hidden helper calls must become explicit before reachability runs.

Initial required cases:

- string literal -> static `Str.from_u8_array`
- string `+` -> static `Str.concat`

If later codegen-only helpers exist, either lower them to source-backed methods or represent them with explicit synthetic nodes as defined in `docs/SEMANTIC_IR_SPEC.md`.

### 6. Carry Type Information Where It Reduces Recovery Logic

The semantic IR should retain just enough type information to avoid later re-inference.

Examples:

- expression result class/reference type when needed for method dispatch
- array element reference type when needed for indexing results
- explicit receiver type on resolved instance calls

This should be stored structurally, not recovered from identifier text. The semantic IR spec is the source of truth for which node fields carry those resolved type names.

### 7. Lock The Semantic IR Node Set Before Implementation

Before any code changes, the semantic IR node set should be fixed explicitly so later passes do not grow it ad hoc.

The semantic IR should be intentionally small and should only include nodes that later stages actually need.

The full semantic IR specification now lives in `docs/SEMANTIC_IR_SPEC.md`.

That document locks down:

- the exact node set
- semantic IR invariants
- AST-to-semantic-IR mapping guidance
- pass-by-pass node classification into mandatory, wrappers, and deferred

### Node Classification Decision

The implementation should follow this policy:

- declaration and structured statement nodes are introduced early to establish container shape
- explicit resolved call nodes are the first non-wrapper expression family that must become mandatory
- structural sugar nodes follow after call resolution is stable
- `SyntheticExpr` remains a last resort, not the default encoding for helper-backed operations

### Pass Expectations Summary

Pass 2:

- introduce the semantic IR containers and wrapper-friendly expression surface
- do not require resolved call nodes to be active everywhere yet

Pass 3:

- make explicit resolved call nodes mandatory
- remove ambiguous call interpretation from later stages

Pass 4:

- make structural sugar and any remaining hidden helper dependencies explicit

For exact node-by-node classification, use `docs/SEMANTIC_IR_SPEC.md` as the source of truth.

## File Boundary Proposal

Suggested new modules:

```text
compiler/
  semantic_symbols.py          # canonical symbol IDs
  semantic_ir.py               # lowered semantic node dataclasses
  semantic_lowering.py         # source AST + typecheck data -> semantic IR
  reachability.py              # rewritten later to consume semantic IR
```

Likely existing modules to update:

- `compiler/cli.py`
- `compiler/typecheck/api.py`
- `compiler/module_linker.py`
- `compiler/codegen/generator.py`
- `compiler/codegen/call_resolution.py`
- `compiler/codegen/emitter_expr.py`

## Concrete Implementation Passes

### Pass 1: Introduce Shared Symbol Identity Types

### Goal

Create canonical post-typecheck symbol identifiers without changing compiler behavior.

### Changes

1. Add `FunctionId`, `ClassId`, `MethodId`, `ConstructorId`, and `SyntheticId` in a shared module.
2. Add helper builders that enumerate module-qualified functions, classes, methods, and constructors from `ProgramInfo`.
3. Make these helpers reusable by future semantic lowering and reachability.

### Non-Goals

- no semantic IR yet
- no pipeline changes yet
- no reachability rewrite yet

### Validation

- unit tests for canonical symbol collection
- module collision tests proving distinct IDs for duplicate leaf names

### Pass 1 Checklist

This pass should be implemented as a small, behavior-preserving extraction. The output should be reusable symbol identity helpers, not a reachability rewrite.

#### Step 1: Add Shared Symbol ID Module

Primary file:

- `compiler/semantic_symbols.py`

Tasks:

1. Add `FunctionId`, `ClassId`, `MethodId`, `ConstructorId`, and `SyntheticId`.
2. Keep them as frozen dataclasses.
3. Reuse `ModulePath` from `compiler/resolver.py` rather than defining a second module-path type.
4. Keep this module dependency-light. It should not import reachability, codegen, or typecheck implementation modules.

Exit criteria:

- the symbol ID module can be imported independently
- IDs have no behavioral logic beyond identity/display helpers if needed

#### Step 2: Add Program Symbol Inventory Helpers

Primary file:

- `compiler/semantic_symbols.py`

Inputs:

- `ProgramInfo`
- `ModuleInfo`
- `ModuleAst`

Tasks:

1. Add helper functions that enumerate all top-level functions by `FunctionId`.
2. Add helper functions that enumerate all classes by `ClassId`.
3. Add helper functions that enumerate all methods by `MethodId`.
4. Add helper functions that enumerate all implicit constructors by `ConstructorId`.
5. Add helper functions that build lookup maps such as:
    - `FunctionId -> FunctionDecl`
    - `ClassId -> ClassDecl`
    - `MethodId -> MethodDecl`
    - `ConstructorId -> ClassDecl`
6. Decide whether these are exposed as free functions or wrapped in one small inventory dataclass such as `ProgramSymbolIndex`.

Recommendation:

- prefer one inventory builder such as `build_program_symbol_index(program)` returning a dataclass with all maps and sets

Exit criteria:

- one call can build the full canonical symbol inventory from `ProgramInfo`
- inventory construction does not depend on typecheck or codegen internals

#### Step 3: Add Local-By-Module Convenience Lookups

Primary file:

- `compiler/semantic_symbols.py`

Tasks:

1. Add module-scoped lookup maps for unqualified local declarations:
    - `ModulePath -> dict[str, FunctionId]`
    - `ModulePath -> dict[str, ClassId]`
2. Add a class-name fanout map for duplicate-leaf-name analysis:
    - `str -> set[ClassId]`
3. Add any equivalent function-name fanout map only if it is immediately useful for diagnostics/tests. Do not add speculative indexes.

Why this belongs in pass 1:

- later lowering and reachability work will need these inventories repeatedly
- building them once in a shared place avoids reintroducing custom indexing in each subsystem

Exit criteria:

- later passes can ask shared helpers for local and global canonical symbol identity without re-scanning the whole program

#### Step 4: Keep Existing Reachability Untouched Except Optional Read-Only Probe Usage

Primary files:

- `compiler/reachability.py`

Tasks:

1. Do not rewrite the coarse walker in pass 1.
2. If useful, add a minimal non-semantic test or debug-only use of the shared symbol inventory helpers.
3. Do not change pruning behavior in this pass.

Why:

- the point of this pass is to establish shared identity primitives before any behavioral migration
- behavior-preserving infrastructure is much easier to review and validate

Exit criteria:

- compiler output and reachability behavior remain unchanged
- new symbol helpers exist and are available for the next pass

#### Step 5: Add Direct Tests For Symbol Identity Inventory

Primary files:

- `tests/compiler/semantic/` (new directory)
- or `tests/compiler/reachability/` only if you want to defer creating a semantic test area

Recommended files:

- `tests/compiler/semantic/test_semantic_symbols.py`

Tasks:

1. Test `FunctionId` collection across multiple modules.
2. Test `ClassId` collection across multiple modules.
3. Test `MethodId` collection for classes with duplicate method names in different modules/classes.
4. Test `ConstructorId` collection for implicit constructors.
5. Test duplicate leaf-name non-collision across modules.
6. Test that local-by-module lookups return the expected canonical IDs.

Suggested fixture shapes:

- one `main.nif` plus one or two imported modules
- duplicate class names in different modules
- duplicate function names in different modules
- classes with both static and instance methods sharing leaf method names across owners

Exit criteria:

- tests prove canonical IDs are module-qualified and collision-safe
- tests do not depend on reachability behavior

#### Step 6: Add One Small Facade Import Point If Needed

Primary files:

- `compiler/__init__.py` only if the project already treats the package root as a public import facade

Tasks:

1. Decide whether `semantic_symbols` should be imported directly by internal callers or surfaced through a package facade.
2. Prefer direct internal imports unless there is already a stable facade pattern.

Exit criteria:

- import story is clear and consistent

### Pass 1 File-By-File Change List

Expected new files:

- `compiler/semantic_symbols.py`
- `tests/compiler/semantic/test_semantic_symbols.py`

Expected existing files touched lightly or not at all:

- `compiler/reachability.py`
- `compiler/resolver.py`
- `compiler/cli.py`

Expected files not to change in this pass:

- `compiler/codegen/*`
- `compiler/typecheck/*`
- `compiler/module_linker.py`

### Pass 1 Recommended Order

Implement in this order:

1. Add symbol ID dataclasses.
2. Add symbol inventory builder and lookup maps.
3. Add direct tests for inventory behavior.
4. Optionally wire one read-only consumer to prove the helpers are usable.
5. Run the full test suite.

### Pass 1 Review Checklist

Before considering pass 1 done, verify:

1. There is exactly one canonical definition of post-typecheck symbol IDs.
2. Module-qualified identity no longer depends on ad hoc string concatenation in future-facing code.
3. The new helpers do not import codegen or reachability internals.
4. The compiler behavior is unchanged.
5. The new tests are focused on identity/inventory, not semantic lowering.

### Pass 1 Exit Criteria

Pass 1 is complete when all of the following are true:

1. Shared canonical symbol ID types exist in one module.
2. `ProgramInfo` can be converted into a canonical symbol inventory with reusable lookup maps.
3. Direct tests cover duplicate-leaf-name collision cases.
4. No semantic lowering has started yet.
5. Existing compiler behavior remains green under the full test suite.

### Pass 2: Add Semantic IR Skeleton And Lowered Program Container

### Goal

Introduce the semantic IR types and a lowered program container while still mirroring current source structure closely.

### Changes

1. Add semantic IR dataclasses for modules, classes, functions, methods, statements, and expressions.
2. Add explicit symbol-ref nodes for globals and members.
3. Add a `lower_program(program)` entry point that can initially perform mostly structural conversion.
4. Keep codegen and reachability unchanged for this pass if needed.

### Non-Goals

- no full semantic lowering yet
- no behavior changes yet
- no pruning changes yet

### Validation

- snapshot tests or structural tests proving source AST converts into semantic IR consistently

### Pass 3: Resolve Calls And Constructors During Semantic Lowering

### Goal

Move function/class/method/constructor interpretation out of reachability and codegen.

### Changes

1. Lower identifier and field-chain calls into explicit resolved call node kinds.
2. Resolve constructor calls into `ConstructorCall` nodes.
3. Resolve static method calls into `StaticMethodCall` nodes.
4. Resolve instance method calls into `InstanceMethodCall` nodes.
5. Lower first-class callable values to explicit symbol-backed nodes where supported.

### Non-Goals

- no reachability rewrite yet
- no codegen deletion yet

### Validation

- tests for local/imported function calls
- tests for static method calls
- tests for instance method chains
- tests for constructor calls
- tests for callable values

### Pass 4: Lower Structural Sugar And Synthetic Helpers

### Goal

Make structural protocol calls and hidden helper dependencies explicit before reachability.

### Changes

1. Lower indexing/slicing operations to explicit resolved structural call nodes.
2. Lower `for in` into an explicit semantic iteration form with resolved `iter_len` and `iter_get` IDs.
3. Lower string literals to explicit helper-backed construction form.
4. Lower string `+` to explicit `Str.concat` call form.
5. Audit any other codegen-only hidden helper edges and move them here.

### Non-Goals

- no control-flow CFG lowering yet
- no optimization passes yet

### Validation

- tests for arrays and structural object protocols
- tests for `for in`
- tests for string literal lowering
- tests for string concatenation lowering

### Pass 5: Rewrite Reachability To Consume Semantic IR

### Goal

Replace the current source-AST reachability walker with a semantic IR graph traversal.

### Changes

1. Change reachability input from `ProgramInfo` to semantic program data.
2. Traverse explicit call nodes and explicit type-use edges.
3. Track fine-grained liveness using canonical IDs.
4. Stop using flattened field-chain recovery and local type guessing.
5. Keep reachability analysis separate from pruning.

### Non-Goals

- no codegen rewrite yet

### Validation

- direct reachability tests for functions/classes/methods/constructors
- tests for duplicate leaf-name modules
- tests for structural and synthetic helper edges

### Pass 6: Move Codegen To Semantic IR And Delete Recovery Logic

### Goal

Make codegen consume explicit semantic operations instead of re-resolving syntax.

### Changes

1. Update module-linker and codegen entry points to accept semantic IR.
2. Remove call-target recovery logic that becomes redundant.
3. Remove hidden codegen semantic lowering for string literals and string `+`.
4. Build symbol tables from semantic declarations and resolved IDs.
5. Use reachability facts directly to skip dead functions/methods/constructors.

### Non-Goals

- no optimizer yet unless required for correctness

### Validation

- all existing codegen, integration, and golden tests
- targeted tests proving codegen emits the resolved method/constructor targets directly

## Migration Strategy

The safest migration is overlap, not replacement.

Recommended approach:

1. Introduce symbol IDs first.
2. Introduce semantic IR in parallel with the old AST path.
3. Route one category of semantics at a time through semantic lowering.
4. Move reachability after semantic lowering once resolved call nodes are available.
5. Move codegen after semantic lowering once the main call/structural forms are covered.
6. Delete fallback semantic recovery logic only after the tests prove parity.

This avoids a one-shot rewrite and lets the compiler stay runnable throughout.

## Immediate Decisions To Lock

These decisions should be made explicitly before implementation starts.

### 1. Canonical Representation

Use typed symbol IDs, not fully qualified strings, as the primary post-typecheck representation.

Strings can still exist for diagnostics and display.

### 2. Reachability Input

Reachability should run on semantic IR, not source AST.

### 3. Synthetic Lowering Ownership

String literals, string concatenation, and similar helper-backed operations should be lowered before reachability.

### 4. Parser Responsibility

The parser should not continue accumulating semantic lowering responsibilities beyond simple syntax normalization.

## Risks And Trade-Offs

### 1. Temporary Duplication During Migration

For a while, source AST and semantic IR will coexist. That is acceptable if the boundary is clear and temporary.

### 2. Over-Lowering Too Early

Do not jump directly to a low-level backend IR. The first semantic IR should stay close to source control-flow structure so diagnostics and migration stay manageable.

### 3. Leaking Typecheck Internals

Semantic lowering will need some typecheck outputs. That should be exposed through stable data structures, not by reaching into checker-local implementation details.

### 4. Hidden Remaining Synthetic Cases

The compiler likely has more than the currently visible string-related synthetic edges. These should be audited as part of pass 4.

## Recommended Testing Plan

Add tests for the new stage itself, not just for end-to-end behavior.

Recommended test groups:

- canonical symbol identity collection
- semantic lowering snapshots for function/static/instance/constructor calls
- semantic lowering of structural sugar
- semantic lowering of string literals and string `+`
- reachability over semantic IR
- codegen fed from semantic IR
- existing golden/integration suites as regression coverage

## Why This Refactor Pays Off

If this refactor is done well, it should simplify more than reachability.

Expected benefits:

- reachability becomes a simple resolved-edge traversal
- codegen call resolution shrinks substantially
- hidden lowering behavior becomes testable in one place
- future optimizations have a stable semantic starting point
- diagnostics can be improved without backend coupling
- future language features have a clearer stage to plug into

## Immediate First Step

Start with pass 1.

Do not begin by re-implementing fine-grained reachability on the current source-level AST again. First introduce shared canonical symbol IDs and define the semantic IR boundary. That will make the later reachability rewrite smaller, more correct, and easier to maintain.