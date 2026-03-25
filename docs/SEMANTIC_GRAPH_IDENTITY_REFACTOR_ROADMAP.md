# Semantic Graph Identity Refactor Roadmap

This document defines the concrete refactor plan for evolving the semantic graph from its current name-heavy, string-heavy representation into a more stable semantic model.

The starting point is the current semantic IR described in [SEMANTIC_IR_SPEC.md](SEMANTIC_IR_SPEC.md). That document still describes the baseline IR shape and current behavior. This roadmap describes the ordered changes needed to move beyond that baseline without making the intermediate states confusing or unsafe.

The sequence starts with introducing `LocalId` and ends with removing span-derived temporaries from codegen.

## Why This Refactor Exists

The current semantic graph already has strong global symbol identity through canonical IDs such as `FunctionId`, `ClassId`, and `MethodId`. That part is in good shape.

The remaining weak spots are mostly local and type identity boundaries:

- locals are represented by source names instead of semantic identities
- several passes still key environments by local name
- types are represented primarily as strings that later passes must reinterpret
- codegen still synthesizes some semantic temporaries from source spans instead of consuming explicit semantic identities
- lowering still reconstructs part of the semantic environment from AST-era structures

None of those are blockers for the current compiler, but together they make shadowing, stronger optimization, and future semantic cleanup harder than necessary.

## Goals

- introduce stable local identity throughout semantic IR and downstream passes
- separate source spelling from semantic identity
- reduce places where later passes need to reinterpret `type_name` strings
- make hidden semantic temporaries explicit instead of deriving them from spans
- keep the compiler working at every step with small reviewable changes
- keep diagnostics and source mapping intact while identities become more semantic

## Non-Goals

- do not introduce SSA in this refactor
- do not replace the structured semantic IR with a CFG IR in this refactor
- do not redesign the language surface
- do not combine this with unrelated runtime or backend feature work
- do not require every pass to migrate to canonical type objects on day one

## Design Principles

1. Identity should be explicit.
   Local variables, loop temporaries, and compiler-introduced temporaries should have semantic IDs, not inferred names.

2. Source spelling should remain available.
   Diagnostics, debug dumps, and user-facing errors still need access to original names and spans.

3. Migrations should preserve behavior before improving structure.
   Each phase should first make identity explicit, then let later cleanups simplify code.

4. Backend-invented semantics should move upstream.
   If codegen depends on a value existing, semantic IR should describe that value.

## Current Baseline

Today the semantic graph has these notable properties:

- global declarations use canonical typed IDs
- locals use source names in `SemanticVarDecl`, `LocalRefExpr`, and `LocalLValue`
- optimization environments such as constant folding also key by local name
- many nodes carry resolved types as strings
- `for-in` helper slots are synthesized in codegen from source spans rather than represented explicitly in semantic IR

This roadmap intentionally keeps the current graph usable while shifting those boundaries in a controlled order.

## Dependency Order

The order below is deliberate.

- `LocalId` must come first because it unblocks shadowing, robust local reasoning, and explicit temp modeling.
- local identity should be propagated through lowering, optimizations, and codegen before any broader cleanup, otherwise both representations leak into every pass.
- explicit compiler-owned temporaries should only be introduced after local identity exists, otherwise they immediately fall back to fragile naming conventions.
- removing span-derived temps from codegen is the last step because it depends on the earlier semantic identity work already being in place.

## Ordered Checklist

Use this checklist to track progress. Each item is intended to be completable as a focused reviewable change set.

1. Introduce `LocalId` as the canonical identity for locals
  - [x] add `LocalId` to semantic symbol identities
  - [x] define ownership and uniqueness rules for `LocalId`
  - [x] document whether IDs are unique per function-like body or globally unique within the semantic program
  - [x] keep source names on declarations for diagnostics and debug printing
  - Purpose:
    establish a semantic identity layer for locals before changing any behavior
  - Expected outcome:
    every local can eventually be referred to without depending on source spelling
  - Tests to add:
    - [x] unit tests for `LocalId` equality and construction rules
    - lowering tests proving two locals with the same source name in different scopes can receive distinct IDs once shadowing is enabled later

Step 1 status:

- `LocalId` now exists in the semantic symbol layer.
- A `LocalId` is unique per function-like body, not globally by a standalone counter.
- The concrete representation is `(owner_id, ordinal)`, where `owner_id` is a `FunctionId` or `MethodId` and `ordinal` is a non-negative integer local to that owner.
- This step intentionally does not change semantic IR nodes yet, so declarations and references still keep source names for current behavior and diagnostics.

2. Extend semantic IR nodes to carry local identity explicitly
  - [x] update `SemanticVarDecl` to own a `LocalId`
  - [x] update `LocalRefExpr` to refer to `LocalId`
  - [x] update `LocalLValue` to refer to `LocalId`
  - [x] decide whether params become `SemanticParam` plus `LocalId`, or whether a function-level local declaration model should subsume params
  - [x] update any semantic dump or debug formatting helpers accordingly
  - Purpose:
    make local identity part of the semantic graph itself instead of an external convention
  - Expected outcome:
    local references and assignments become identity-based even while diagnostics still show user-written names
  - Tests to add:
    - [x] semantic lowering tests asserting declaration/reference/lvalue IDs line up
    - [x] semantic IR tests covering params and nested blocks

Step 2 status:

- `SemanticVarDecl`, `LocalRefExpr`, and `LocalLValue` now carry both `local_id` and source `name`.
- `LocalId` is the canonical binding identity; `name` remains on these nodes temporarily for readability, diagnostics, and compatibility with later roadmap steps.
- Parameters remain represented as `SemanticParam` values without embedded `LocalId`s for now.
- Lowering now allocates parameter bindings and `__self` bindings into the same `LocalId` space used by local declarations, so references to params and locals are identity-based even before a dedicated local-metadata table exists.

3. Add a function-local symbol table or metadata view over semantic locals
  - [x] introduce a stable mapping from `LocalId` to metadata such as display name, declared type, declaration span, and owning function or method
  - [x] decide whether the metadata lives directly on nodes, in a per-function table, or both
  - [x] ensure debug tooling can print readable local names without depending on identity internals
  - Purpose:
    separate semantic identity from user-facing metadata instead of duplicating name and type information on every use-site forever
  - Expected outcome:
    later passes can use IDs while diagnostics still recover original names and declaration locations cleanly
  - Tests to add:
    - [x] unit tests for local metadata lookup
    - [x] diagnostic tests proving error messages still show original source names after the identity migration

Step 3 status:

- Semantic local metadata now lives in a per-function or per-method `local_info_by_id` table keyed by `LocalId`.
- Each metadata entry records the local display name, declared type, declaration span, binding kind, and owning function-like symbol.
- Local names still remain on `SemanticVarDecl`, `LocalRefExpr`, and `LocalLValue` for compatibility, but readable-name recovery no longer depends on those use-site fields alone.
- Method codegen wrappers now preserve method-local metadata when a `SemanticMethod` is re-expressed as a temporary `SemanticFunction` for emission.

4. Finish the lowering migration around canonical local identity
  - [x] allocate `LocalId` values during body lowering
  - [x] thread local identity through nested block scopes
  - [x] preserve current no-shadowing behavior initially unless shadowing is introduced in the same change set intentionally
  - [x] remove the remaining name-keyed lookup path inside lowering so local resolution no longer depends on source spelling after typecheck lookup succeeds
  - Purpose:
    keep lowering as the sole place that constructs lexical local identity, then remove the remaining transitional dependence on names inside the lowering implementation itself
  - Expected outcome:
    downstream passes receive a semantically bound graph and lowering no longer has to reconstruct final local identity from source spelling once a local binding is known
  - Tests to add:
    - [x] lowering tests for nested scopes
    - [x] lowering tests for `if`, `while`, and `for-in`
    - [x] tests showing that renamed source locals do not affect identity behavior except in diagnostics

Step 4 status:

- Lowering already allocates `LocalId` values in `lower_function_like_body` and threads them through nested lexical scopes.
- Local declarations, local references, local assignment targets, params, `__self`, and `for-in` element bindings are already emitted with canonical `LocalId` values.
- The current no-shadowing behavior remains intentionally unchanged at the typecheck boundary.
- Lowering now resolves local bindings through the typecheck scope's binding objects and only carries source names forward as metadata for diagnostics and debug readability.

5. Migrate semantic optimization passes from local-name environments to `LocalId`
  - [ ] update constant folding environments to key by `LocalId`
  - [ ] update any future flow simplification or propagation scaffolding to key by `LocalId`
  - [ ] audit reachability and any semantic walkers for remaining local-name assumptions
  - Purpose:
    make optimization semantics match the semantic graph instead of source spelling
  - Expected outcome:
    local reasoning becomes robust against shadowing and less fragile under transforms
  - Tests to add:
    - constant-folding tests with nested scopes and repeated source names
    - regression tests showing propagated values do not leak across distinct locals that share a source name

6. Enable lexical shadowing as a semantic feature after identity migration
  - [ ] remove the function-wide unique-local-name restriction in typechecking and lowering
  - [ ] define the exact shadowing rules for params, loop variables, and nested blocks
  - [ ] validate interactions with closures or method references if those semantics exist by then
  - Purpose:
    cash in the main language-design benefit of explicit local identity
  - Expected outcome:
    block-scoped bindings behave naturally without destabilizing optimizations or codegen
  - Tests to add:
    - positive typecheck tests for nested shadowing
    - negative tests for still-illegal same-scope duplicates
    - integration tests covering shadowing inside lowered control flow

7. Introduce canonical semantic type references alongside or beneath `type_name` strings
  - [ ] define a semantic type representation appropriate for the current compiler stage
  - [ ] start with declaration and use-site nodes that most frequently force string reinterpretation
  - [ ] decide whether `type_name` remains as cached display data or is derived from the canonical type representation
  - [ ] keep migration incremental so codegen does not need to switch in one large change
  - Purpose:
    reduce repeated parsing and interpretation of type strings in later passes
  - Expected outcome:
    semantic passes can ask direct questions about type identity and shape without string conventions doing semantic work
  - Tests to add:
    - unit tests for canonical type equality and rendering
    - reachability tests proving type traversal still finds class and interface dependencies correctly
    - lowering tests for qualified and unqualified type references

8. Reduce duplication between semantic nodes and semantic metadata
  - [ ] audit which repeated fields should remain on every node for convenience and which should move into metadata tables
  - [ ] consider whether receiver owner data, declared local type data, and resolved type data are duplicated more than needed
  - [ ] update walkers and pretty-printers to use the chosen metadata boundary consistently
  - Purpose:
    avoid turning the semantic graph into a large typed AST where every node repeats context that can be recovered cheaply and canonically
  - Expected outcome:
    the graph stays explicit where needed but less redundant and easier to evolve
  - Tests to add:
    - semantic dump tests
    - regression tests for any codegen or optimization pass that previously relied on duplicated fields

9. Make compiler-introduced temporaries explicit semantic locals
  - [ ] model hidden loop temporaries such as `for-in` collection, length, and index values as explicit semantic locals or explicit temp declarations
  - [ ] give those temporaries `LocalId`s and clear ownership
  - [ ] decide whether they should appear as ordinary `SemanticVarDecl`s or a dedicated internal-temp form
  - Purpose:
    stop relying on backend conventions for semantically real storage
  - Expected outcome:
    semantic IR fully describes the locals needed for execution of a construct like `for-in`
  - Tests to add:
    - semantic lowering tests asserting helper temps exist for `for-in`
    - codegen tests proving temp layout remains correct after explicit-temp lowering

10. Move frame-layout construction from name-based to identity-based slots
  - [ ] update layout building to use `LocalId` keys instead of source names
  - [ ] keep a display-name layer for debug output and diagnostics
  - [ ] ensure GC root tracking and temp root slots are still computed correctly
  - Purpose:
    make backend storage follow semantic identity instead of source spelling
  - Expected outcome:
    layout stays stable under shadowing and future transforms that rename or duplicate source-visible names
  - Tests to add:
    - layout unit tests for distinct locals with the same source spelling
    - end-to-end runtime tests that exercise reference-typed locals and temp roots

11. Remove span-derived temps from codegen
  - [ ] delete the codegen convention that synthesizes `for-in` helper slot names from `SourceSpan`
  - [ ] consume explicit semantic temp identities instead
  - [ ] ensure no backend logic depends on span structure for semantic correctness
  - Purpose:
    finish the migration from syntax-derived semantics to semantic-owned identities
  - Expected outcome:
    codegen becomes a consumer of semantic intent rather than a place that reconstructs hidden semantics from source locations
  - Tests to add:
    - regression tests covering multiple `for-in` loops on the same source line where practical
    - layout and codegen tests proving helper temp identity no longer depends on span values

## Recommended Change Boundaries

To keep the migration reviewable, use these boundaries:

- keep `LocalId` introduction separate from enabling shadowing
- keep type-identity work separate from local-identity work
- migrate optimizations immediately after lowering begins producing IDs, not much later
- land explicit compiler temp modeling before removing old codegen conventions, so both representations can briefly coexist behind assertions if needed

## Documentation Updates Required During The Refactor

As these changes land, update the following documents so they continue to describe the current state clearly:

- [SEMANTIC_IR_SPEC.md](SEMANTIC_IR_SPEC.md)
  - keep it as the baseline current-shape spec, but clearly mark where the roadmap intentionally evolves local and type identity beyond that baseline
- tests and debug logging docs
  - update any examples that print local names if they now include IDs or derive names through metadata tables

The old semantic lowering module-split plan has been removed because that refactor is complete and no longer needs active tracking.

## Suggested Validation Strategy

For each checklist item:

1. add or update focused unit tests first where possible
2. run the targeted semantic lowering, optimization, and codegen slices affected by the change
3. run the full test suite after each major boundary:
   - after `LocalId` lands in semantic IR
   - after lowering fully produces IDs
   - after optimizations migrate to IDs
   - after codegen stops using span-derived temps

## Exit Criteria

This roadmap is complete when all of the following are true:

- semantic locals are identified canonically, not by source names
- shadowing is either fully supported or explicitly rejected for language reasons rather than IR limitations
- later passes do not key semantic behavior off local source names
- compiler-introduced temporaries are explicit in semantic IR
- codegen no longer reconstructs semantic temps from source spans
- existing docs describe both the current state and the migration target without contradiction
