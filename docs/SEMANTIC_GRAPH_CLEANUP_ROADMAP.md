# Semantic Graph Cleanup Roadmap

This document defines the follow-on cleanup plan after the semantic graph identity refactor.

The identity roadmap solved the biggest correctness problem: local binding identity no longer depends on source spelling. The remaining work is more structural. The semantic graph still mixes canonical semantic data with cached display data, still carries some typed-AST-era node shapes, and still lets a few backend-oriented details leak into the main semantic representation.

This roadmap describes how to clean that up in dependency order without destabilizing the compiler.

## Relationship To Existing Documents

- [SEMANTIC_IR_SPEC.md](SEMANTIC_IR_SPEC.md) describes the current implemented semantic IR shape.
- [SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md](SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md) describes the completed identity migration.
- This document covers the next layer of cleanup: making the graph more canonical, less duplicated, and less syntax-shaped.

## Why This Refactor Exists

The current semantic graph is now correct about symbol identity, but several parts still look transitional:

- many nodes still carry both `SemanticTypeRef` and string type fields
- local use-site nodes still copy readability metadata that now lives authoritatively in owner-local tables
- several expression nodes are still shaped like a typed AST rather than a normalized semantic graph
- `SyntheticExpr` is still a generic escape hatch for semantics that are not yet modeled explicitly
- the current graph mixes source-near semantic structure with execution-shaped lowered details such as `SemanticForIn` helper locals

None of these are urgent correctness bugs. They are design and maintenance costs.

## Goals

- make one representation authoritative for semantic type identity
- reduce duplicated metadata on semantic use-site nodes
- separate semantic meaning from source-token spelling where practical
- make synthetic or backend-facing semantics explicit instead of generic
- define a cleaner boundary between source-level semantic IR and lowered semantic IR
- keep diagnostics and debugging readable throughout the migration

## Non-Goals

- do not introduce SSA in this roadmap
- do not replace the structured semantic graph with CFG or bytecode IR
- do not redesign the language surface
- do not combine this with unrelated runtime or backend feature work
- do not force codegen onto a radically different IR shape in a single step

## Design Principles

1. One fact should have one owner.
   If a type, local display name, or dispatch target is canonical somewhere, other copies should become derived or temporary compatibility views.

2. Semantic nodes should describe resolved meaning, not just typed syntax.
   Operator strings, generic synthetic nodes, and syntax-shaped variants should gradually give way to semantically resolved forms.

3. High-level semantic structure and low-level lowering structure should be distinct when they serve different purposes.
   If a node exists only because codegen needs it, that detail should not be forced into the source-near semantic layer forever.

4. Diagnostics remain a first-class constraint.
   Removing cached names or strings must not make errors, debug dumps, or tests unreadable.

## Current Baseline

Today the semantic graph has these notable properties:

- global declarations and local bindings use canonical IDs
- owner-local metadata is authoritative for local names, declared types, declaration spans, and binding kinds
- many semantic nodes still store both `SemanticTypeRef` and `type_name`-style string data
- `LocalRefExpr`, `LocalLValue`, and some declaration nodes still carry copied display and type metadata for readability and compatibility
- expression nodes such as `UnaryExprS` and `BinaryExprS` still encode semantics partly through source-like operator strings
- call and member-access modeling is explicit but somewhat fragmented across several node kinds with overlapping fields
- `SyntheticExpr` still represents a generic bucket of synthetic semantics
- `SemanticForIn` is now identity-correct, but it still bundles execution-shaped helper locals into the main semantic IR

## Dependency Order

The order below is deliberate.

- canonical type authority should come first because it simplifies every later semantic cleanup
- once type ownership is clear, copied local use-site metadata becomes easier to remove cleanly
- semantic operation and dispatch normalization should happen before splitting semantic layers, otherwise the split just preserves old duplication in two places
- the high-level versus lowered semantic IR boundary should be addressed after the graph is more canonical internally, not before

## Ordered Checklist

1. Make `SemanticTypeRef` the only authoritative semantic type representation
  - [x] define which current `*_type_name` fields remain true compatibility views and which should be removed entirely
  - [x] add helper APIs for display rendering and simple predicates so semantic consumers do not need raw type-name strings
  - [x] migrate semantic passes that still reinterpret type strings to use canonical type refs first
  - [x] restrict `best_effort_semantic_type_ref_from_name(...)` to tests, compatibility shims, or carefully named boundary code
  - Purpose:
    remove the largest remaining source of duplicated semantic truth
  - Expected outcome:
    semantic meaning of types is no longer carried primarily by strings after lowering
  - Tests to add:
    - semantic type traversal tests covering nominal, array, callable, and null forms
    - regression tests proving semantic passes behave the same when display strings change

Step 1 implementation slices:

1.1 Audit and classify current type-string fields
  - [x] inventory every `type_name`, `target_type_name`, `receiver_type_name`, `element_type_name`, and `value_type_name` field in semantic IR
  - [x] classify each field as one of:
    - canonical semantic input still used incorrectly
    - cached display data worth keeping temporarily
    - redundant field that should be removed
  - [x] document which semantic passes and backend paths still read each class of field
  - Stop condition:
    there is a written field-by-field migration table, so later changes do not guess which strings are still required

Step 1.1 audit results:

This table records the current post-step-1.6 field families, their canonical twin when one exists, their current classification, and the main production readers that still depend on them.

| Field family | Representative semantic IR fields | Canonical twin today | Classification | Main current readers | Notes |
| --- | --- | --- | --- | --- | --- |
| Declaration and signature type strings | `SemanticField.type_name`, `SemanticParam.type_name`, `SemanticInterfaceMethod.return_type_name`, `SemanticFunction.return_type_name`, `SemanticMethod.return_type_name` | `type_ref` or `return_type_ref` on the same node | cached display data worth keeping temporarily | declaration lowering in `compiler/semantic/lowering/orchestration.py`; constructor parameter synthesis in `compiler/codegen/emitter_fn.py`; low-priority diagnostics and tests | ABI shape decisions for parameter spills and function epilogues now use canonical refs, and linker entrypoint validation now uses `return_type_ref`. The copied strings remain mainly as readability caches and fixture conveniences. |
| Owner-local declared type metadata | `SemanticLocalInfo.type_name` | `SemanticLocalInfo.type_ref` | cached display data worth keeping temporarily | owner-local helper builders in `compiler/semantic/ir.py`; low-priority diagnostics and tests | Layout root-slot classification and layout slot type storage now use canonical refs, so the owner-local string cache is no longer part of ABI/layout authority. It remains useful as the readable local-type cache until more display plumbing is simplified. |
| Removed redundant compatibility fields | `SemanticVarDecl.type_name`, `FunctionRefExpr.type_name`, `ClassRefExpr.type_name`, `MethodRefExpr.type_name` | owner-local metadata or node-local `type_ref` | removed in completed slices | no production readers remain | These fields were removed in steps `1.6` because their canonical twin already carried the same semantic information and compatibility rendering could be centralized elsewhere. |
| Removed local use-site compatibility fields | `LocalRefExpr.type_name`, `LocalLValue.type_name` | `type_ref` on the same node plus owner-local metadata | removed in completed slices | no production readers remain | Step `2` removed these copied strings after diagnostics, layout, and optimizations switched to owner-local metadata plus canonical refs. |
| Receiver and target compatibility strings | `FieldReadExpr.receiver_type_name`, `FieldLValue.receiver_type_name`, `InstanceMethodCallExpr.receiver_type_name`, `InterfaceMethodCallExpr.receiver_type_name`, `CastExprS.target_type_name`, `TypeTestExprS.target_type_name` | `receiver_type_ref` or `target_type_ref` on the same node | cached display data worth keeping temporarily | lowering construction in `compiler/semantic/lowering/expressions.py`, `compiler/semantic/lowering/calls.py`, and `compiler/semantic/lowering/references.py`; low-priority diagnostics in `compiler/codegen/emitter_expr.py` | Semantic folding, cast/type-test codegen, runtime metadata collection, and nominal dispatch helpers now use canonical refs or canonicalized checked types. The copied strings remain mainly as compatibility display caches and handwritten-fixture conveniences. |
| Collection element and value compatibility strings | `SemanticForIn.element_type_name`, `ArrayCtorExprS.element_type_name`, `IndexLValue.value_type_name`, `SliceLValue.value_type_name` | `element_type_ref` or `value_type_ref` on the same node | cached display data worth keeping temporarily | lowering construction in `compiler/semantic/lowering/expressions.py`, `compiler/semantic/lowering/statements.py`, `compiler/semantic/lowering/executable.py`, `compiler/semantic/lowering/references.py`, and `compiler/semantic/lowering/collections.py` | Array constructor emission, lowered `for-in` iteration emission, and array runtime-dispatch selection now use canonical refs. The remaining strings are lower-priority readability caches and future removal candidates. |
| Field-access result type strings on nodes that already have a canonical ref | `FieldReadExpr.type_name`, `FieldLValue.type_name` | `type_ref` on the same node | cached display data worth keeping temporarily | generic expression typing through `compiler/semantic/ir.py:expression_type_name` | Backend expression emission and layout planning no longer need these copied strings. They now mostly serve compatibility display paths and handwritten fixtures. |
| Executable result type strings on nodes that now also carry canonical refs | `LiteralExprS.type_name`, `UnaryExprS.type_name`, `BinaryExprS.type_name`, `FunctionCallExpr.type_name`, `StaticMethodCallExpr.type_name`, `InstanceMethodCallExpr.type_name`, `InterfaceMethodCallExpr.type_name`, `ConstructorCallExpr.type_name`, `CallableValueCallExpr.type_name`, `IndexReadExpr.type_name`, `SliceReadExpr.type_name`, `ArrayCtorExprS.type_name`, `SyntheticExpr.type_name` | `type_ref` on the same node | cached display data worth keeping temporarily | `compiler/semantic/ir.py:expression_type_name`; a few low-priority diagnostics such as the type-test error path in `compiler/codegen/emitter_expr.py` | Constant folding and backend expression emission now use canonical refs for integer width, return ABI shape, runtime dispatch selection, and argument rooting decisions. These copied strings are no longer primary semantic inputs. |
| Fixed-result compatibility display strings | `NullExprS.type_name`, `ArrayLenExpr.type_name` | built-in `type_ref` on the same node | cached display data worth keeping temporarily | generic expression helpers and backend emission paths | These now have built-in canonical refs and no longer carry unique semantic information, but removing the copied string is lower value than the higher-churn field families above. |

Current reader summary by subsystem:

- Semantic graph traversal is now largely canonical. Reachability in `compiler/semantic/optimizations/reachability.py` follows `SemanticTypeRef` structure first and uses explicit compatibility reconstruction only at the remaining fallback boundary.
- Semantic optimizations are now canonical for executable behavior. Constant folding uses `SemanticTypeRef` structure and canonical names rather than copied executable type strings.
- Lowering-time collection dispatch and instance-method resolution now use canonical refs or canonicalized checked types instead of compatibility strings. The remaining lowering-side string fields are construction-time readability caches.
- Backend codegen is no longer broadly string-driven for executable expression behavior. `compiler/codegen/emitter_expr.py`, `compiler/codegen/layout.py`, `compiler/codegen/emitter_stmt.py`, `compiler/codegen/metadata.py`, `compiler/codegen/emitter_fn.py`, and `compiler/codegen/generator.py` now use canonical refs for the migrated cast, type-test, array, call, temp-rooting, parameter-spill, and return-ABI decisions. The remaining backend string usage is mostly readability-oriented constructor/declaration plumbing rather than ABI authority.
- `compiler/semantic/ir.py:expression_type_name(...)` is now primarily a compatibility display helper rather than a semantic or backend decision primitive.
- `best_effort_semantic_type_ref_from_name(...)` is now test-only by direct usage, while production compatibility reconstruction is visually fenced behind `compat_semantic_type_ref_from_name(...)`.

Conclusion of step 1.1:

- The remaining meaningful duplication is now lower priority than it was at step `1.1`: declaration/signature strings, owner-local readable type caches, and a handful of receiver/target, collection, field-access, and executable display strings remain primarily as compatibility or readability caches rather than semantic or ABI inputs.
- The first redundant-field removals have already been proven end to end: `SemanticVarDecl.type_name`, `FunctionRefExpr.type_name`, `ClassRefExpr.type_name`, and `MethodRefExpr.type_name` are gone, and compatibility display rendering for the reference-expression slice is centralized instead of copied per node.
- Local use-site result strings are now also gone: `LocalRefExpr.type_name` and `LocalLValue.type_name` were removed once owner-local metadata became authoritative.
- Declaration/signature strings, owner-local readable type caches, and fixed-result default strings are the remaining acceptable temporary compatibility stores at the end of step 1 because they still support ABI, layout, diagnostics, or low-priority rendering paths that have not yet moved to canonical helpers.

Step 1.1 status:

- complete
- post-step-7 reduction slices have refreshed this audit after migrating constant folding, backend cast/type-test/array handling, backend temp-rooting and ABI-shape decisions, lowering collection dispatch helpers, and linker entrypoint validation to canonical refs.
- no executable tests added; this slice is a documentation and audit step, and its validation is the migration table itself

1.2 Establish canonical type helper APIs
  - [x] add central helper APIs for common semantic questions now answered via string inspection
  - [x] cover at least:
    - nominal identity
    - primitive/reference/interface/array/callable/null kind checks
    - array element access
    - callable parameter and return access
    - rendering a stable display string from `SemanticTypeRef`
  - [x] move string-parsing helpers behind explicitly compatibility-named boundaries
  - Stop condition:
    new semantic code can ask normal type questions without branching on raw type-name strings

Step 1.2 status:

- complete
- `compiler/semantic/types.py` now exposes canonical helper APIs for type kind checks, nominal identity, array element access, callable parameter access, callable return access, display-name rendering, and canonical-name rendering.
- raw string reconstruction now has an explicit compatibility entrypoint via `compat_semantic_type_ref_from_name(...)`.
- the older `best_effort_semantic_type_ref_from_name(...)` name remains as a thin compatibility wrapper for now; fencing off remaining direct uses is still tracked separately in step `1.5`.

1.3 Migrate semantic analyses to canonical type refs first
  - [x] update semantic passes that currently reinterpret strings, starting with reachability and any semantic helpers that still parse nominal names or callable signatures
  - [x] make migrated passes treat type strings as fallback-only compatibility data rather than primary input
  - [x] keep the migration narrow enough that codegen is not forced to switch in the same step
  - Stop condition:
    semantic analyses no longer need string parsing for the node categories already carrying canonical type refs

Step 1.3 status:

- complete
- semantic reachability no longer maintains its own local parser for callable and nominal type strings.
- `compiler/semantic/optimizations/reachability.py` now follows canonical `SemanticTypeRef` structure through shared helper APIs and uses type-name reconstruction only as an explicit compatibility fallback.
- this step intentionally does not migrate codegen or constant-folding result-type logic yet; those consumers still rely on string fields that remain compatibility or executable data until later slices.

1.4 Tighten type ownership at the IR construction boundary
  - [x] make lowering populate canonical `SemanticTypeRef` values for any remaining frequently used nodes that still rely mainly on strings
  - [x] reduce creation of semantic nodes that have meaningful type strings but missing canonical type refs
  - [x] treat missing canonical type info as a bug in lowering unless the node is explicitly marked as a compatibility case
  - Stop condition:
    newly lowered semantic nodes consistently arrive with canonical type refs wherever later semantic passes need them

Step 1.4 status:

- complete
- lowering now populates canonical result `type_ref` values for the main executable expression families that previously carried only `type_name`, including literals, unary and binary expressions, casts, type tests, call nodes, array reads and slices, array constructors, and synthetic string-literal byte payloads.
- `NullExprS` and `ArrayLenExpr` now expose built-in canonical type refs for their fixed result types, so executable semantic expressions have a uniform canonical type query even when the result type is intrinsic rather than inferred from typecheck output.
- the remaining string result fields are now explicitly compatibility and display data for these node families rather than the only semantic type payload established at lowering time.

1.5 Fence off `best_effort_semantic_type_ref_from_name(...)`
  - [x] move direct production usage behind carefully named compatibility helpers or clearly delimited boundary modules
  - [x] keep direct use in tests where synthetic semantic fixtures are still handwritten
  - [x] add comments or assertions clarifying that the function is a reconstruction shim, not the preferred semantic path
  - Stop condition:
    the codebase makes it visually obvious which type refs are canonical lowering output and which are reconstructed compatibility values

Step 1.5 status:

- complete
- direct `best_effort_semantic_type_ref_from_name(...)` usage is now confined to handwritten test fixtures; production reconstruction sites use the explicitly named `compat_semantic_type_ref_from_name(...)` boundary instead.
- `compiler/semantic/types.py` now documents the distinction directly: `compat_...` is the production compatibility shim, while `best_effort_...` is retained as a backward-compatible convenience wrapper for tests.
- semantic type tests pin the wrapper behavior so future cleanup can remove or rename it deliberately instead of letting production call sites drift back in implicitly.

1.6 Remove the first redundant string fields
  - [x] pick a small set of high-confidence redundant fields and remove them after their consumers have switched to canonical refs
  - [x] prefer fields on nodes already carrying an equivalent `SemanticTypeRef` and already consumed semantically through that ref
  - [x] keep display rendering centralized so diagnostics do not regress when the copied string disappears
  - Stop condition:
    at least one end-to-end slice proves a semantic node family can operate without duplicated type strings

Step 1.6 status:

- `SemanticVarDecl.type_name` has been removed. It had no remaining production readers and was already effectively dead compatibility data after the local-metadata migration.
- `FunctionRefExpr.type_name`, `ClassRefExpr.type_name`, and `MethodRefExpr.type_name` have also been removed. These nodes already carried equivalent canonical `type_ref` values, and no production reader required the copied string once `expression_type_name(...)` was taught to render reference-expression display names from the canonical ref.
- this slice keeps compatibility rendering centralized in `compiler/semantic/ir.py:expression_type_name(...)`, so downstream code that still asks for a display-oriented type name does not need to know which nodes still store a copied string and which derive one from canonical metadata.

1.7 Re-evaluate remaining string type fields after the first migration slice
  - [x] update the migration table from step 1.1 with what is now truly required for compatibility
  - [x] decide which remaining fields are acceptable long-lived caches and which belong in later removal slices
  - [x] only then move to step 2 of the cleanup roadmap
  - Stop condition:
    step 1 ends with a narrowed, explicit, justified set of remaining type-string compatibility fields rather than a blanket duplication policy

Step 1.7 status:

- complete
- the migration table now reflects the post-step-1.6 state instead of the original step `1.1` snapshot: removed fields are called out explicitly, nodes that gained canonical result refs in step `1.4` are no longer described as string-only, and the remaining compatibility set is narrowed to concrete field families with named readers.
- the remaining acceptable temporary caches at the end of step 1 are declaration/signature type strings, owner-local readable type caches, and a few low-priority fixed-result display strings. The remaining duplicated executable and use-site strings are now explicitly queued as later removal or migration targets rather than being treated as an undifferentiated blanket policy.
- no executable tests were added for this slice because step `1.7` is a documentation and audit checkpoint; its validation is the refreshed field-by-field migration table and reader summary.

2. Remove copied local readability and declared-type data from local use sites
  - [x] stop treating `LocalRefExpr.name`, `LocalRefExpr.type_name`, `LocalLValue.name`, and similar fields as semantic data
  - [x] decide whether those fields should be removed outright or retained only in debug-only wrappers/builders
  - [x] update diagnostics and codegen helpers to recover display metadata strictly through owner-local lookup APIs
  - [x] finish the same cleanup for `SemanticVarDecl` compatibility fields if any remaining downstream users still depend on them
  - Purpose:
    make `LocalId` plus owner metadata the only semantic local source of truth
  - Expected outcome:
    local use-site nodes describe identity and value flow, not cached copies of declaration metadata
  - Tests to add:
    - diagnostics tests proving local names still appear correctly after copied name removal
    - codegen and optimization tests using synthetic or rewritten semantic functions with owner metadata only

Step 2 status:

- complete
- `LocalRefExpr` and `LocalLValue` now carry only `LocalId`, canonical `type_ref`, and span data; copied display names and declared type strings have been removed.
- lowering no longer threads copied local readability metadata through resolved local targets, so owner-local metadata is the only semantic source of truth for local display and declared-type recovery.
- codegen diagnostics now recover local display names through `local_display_name_for_owner(...)` when an owner is available, and generic local result-type rendering goes through canonical `SemanticTypeRef` display helpers.
- `SemanticVarDecl` compatibility fields required no extra step-2 migration beyond the earlier removal slice; the remaining downstream checks now assert owner-local metadata directly instead of copied use-site fields.

3. Normalize semantic operations away from raw source-token strings
  - [x] introduce canonical enums or operation descriptors for unary, binary, cast, and type-test semantics where raw strings still do semantic work
  - [x] distinguish operations whose source spelling matches but whose semantics differ after type resolution
  - [x] keep pretty-printing helpers so test output and diagnostics stay readable
  - Purpose:
    move the graph from typed syntax toward resolved semantic operations
  - Expected outcome:
    later passes ask semantic questions directly instead of branching on source token text
  - Tests to add:
    - constant-folding and codegen tests keyed by semantic op kind rather than operator string spelling
    - regression tests for operations whose legality depends on resolved operand type

Step 3 status:

- complete
- canonical semantic operation descriptors now live in `compiler/semantic/operations.py`: unary and binary expressions carry resolved op descriptors, while casts and type tests carry explicit semantic kind enums.
- lowering now classifies operation semantics from canonical `SemanticTypeRef` values instead of copying raw source operator text into the semantic IR.
- constant folding and codegen now branch on canonical op kinds and resolved operation flavors rather than source-token strings, while diagnostics still render readable operator text through shared pretty-print helpers.
- focused lowering and codegen regressions cover integer vs double `+`, identity comparison, unary negation, reference-compatible casts, interface type tests, and backend integer-op helper coverage through the new canonical op model.

4. Normalize resolved call and member-access modeling
  - [x] factor the overlapping call/member fields into a clearer resolved target model
  - [x] decide whether instance, static, interface, constructor, and callable-value invocation should remain separate node kinds or share a common resolved call payload
  - [x] define a canonical dispatch structure that owns receiver type, target identity, and dispatch mode
  - Purpose:
    reduce duplicated call-shape logic and make dispatch reasoning easier across semantic passes and codegen
  - Expected outcome:
    call semantics live in one consistent model instead of several partially overlapping node forms
  - Tests to add:
    - semantic lowering tests covering every resolved call category through the same normalization boundary
    - codegen tests proving normalized call metadata still produces correct labels and runtime dispatch

Step 4 status:

- complete
- executable calls now lower to a single `CallExprS` node that carries a discriminated `target` payload rather than six partially overlapping call node shapes.
- target identity and dispatch semantics now live in explicit target dataclasses: `FunctionCallTarget`, `StaticMethodCallTarget`, `InstanceMethodCallTarget`, `InterfaceMethodCallTarget`, `ConstructorCallTarget`, and `CallableValueCallTarget`.
- receiver metadata shared by field access and bound call dispatch now lives in `BoundMemberAccess`, which centralizes the receiver expression plus canonical receiver type information instead of copying that triple across field reads, field writes, and bound call forms.
- lowering, constant folding, reachability, layout planning, codegen emission, and semantic/codegen walk tests now consume the shared target model instead of repeating category-specific call-shape logic.
- validation covered focused lowering, emitter, walk, and optimization tests (`59 passed`) plus the broad semantic and codegen suites (`238 passed`).

5. Replace `SyntheticExpr` with explicit semantic node kinds or explicit synthetic categories
  - [x] inventory all current `SyntheticExpr` uses and group them by actual semantic meaning
  - [x] promote common synthetic forms into dedicated node types where semantics are stable
  - [x] if any generic synthetic bucket remains, make it a narrowly typed, well-documented escape hatch rather than an open-ended catch-all
  - Purpose:
    prevent the semantic graph from accumulating an unstructured miscellaneous node
  - Expected outcome:
    synthetic semantics become visible and reviewable in the node set itself
  - Tests to add:
    - semantic walk and reachability tests covering the new explicit synthetic node coverage
    - regression tests proving no old synthetic use falls through undocumented paths

Step 5 status:

- complete
- the generic `SyntheticExpr` bucket has been removed because the only live synthetic form was string-literal byte payload lowering.
- string literal byte payloads now use an explicit `StringLiteralBytesExpr` node with fixed canonical `u8[]` type metadata instead of an open-ended synthetic identifier and argument bag.
- `SyntheticId` has been removed, and the relevant lowering, constant folding, reachability, walk, layout, string-collection, and codegen paths now consume the explicit node directly.
- `compiler/semantic/types.py` now exposes `semantic_array_type_ref(...)`, which lets explicit fixed-shape nodes construct canonical array type refs without routing through compatibility-era string reconstruction.
- validation covers lowering and semantic type regressions directly, and broad semantic plus codegen validation remains required for the step.

6. Define an explicit split between source-level semantic IR and lowered semantic IR
  - [x] decide whether the compiler should keep one IR with phases or two closely related IR layers
  - [x] identify which current nodes belong naturally to source-level semantics versus lowered execution-oriented semantics
  - [x] move execution-shaped details such as `SemanticForIn` helper-local bookkeeping behind a lowered-semantic boundary if that split pays for itself
  - [x] keep high-level semantic analyses operating on the source-near layer wherever practical
  - Purpose:
    stop one semantic graph from serving two different abstraction levels indefinitely
  - Expected outcome:
    source reasoning stays readable while codegen and backend preparation can still consume an explicit lowered form
  - Tests to add:
    - boundary tests proving source-level analysis output lowers deterministically into the execution-oriented layer
    - codegen regressions proving lowered helper locals remain explicit and identity-correct after the split

Step 6 status:

- complete
- source semantic lowering now keeps `SemanticForIn` source-level only: element binding, collection expression, dispatches, element type, and body remain, while execution-only helper locals move out of the source IR.
- `compiler/semantic/lowered_ir.py` defines the explicit executable-side boundary via `LoweredSemanticBlock`, `LoweredSemanticForIn`, `LoweredSemanticModule`, and `LoweredLinkedSemanticProgram`.
- `compiler/semantic/lowering/executable.py` now lowers linked source semantics into the executable layer, allocating deterministic `__for_in_collection`, `__for_in_length`, and `__for_in_index` locals after linking.
- semantic optimization and analysis continue to operate on the source-level semantic program, while CLI/codegen entrypoints now lower to the executable layer immediately before backend consumption.
- validation includes focused boundary tests and broad semantic plus codegen regression coverage, including explicit checks that source lowering no longer records helper locals and that executable lowering reintroduces them deterministically.

7. Audit diagnostics, walkers, and tests for over-coupling to compatibility fields
  - [x] remove tests that assert transitional storage details instead of semantic invariants
  - [x] centralize display rendering helpers for types, locals, and resolved call targets
  - [x] ensure semantic walkers and future optimization scaffolding rely on canonical fields only
  - Purpose:
    make the previous cleanup steps durable instead of reintroducing compatibility dependencies through tests and tooling
  - Expected outcome:
    the semantic graph stays canonical because the surrounding tooling no longer depends on transitional node copies
  - Tests to add:
    - walk and debug-format tests that validate central rendering helpers instead of node-field duplication

Step 7 status:

- complete
- `compiler/semantic/display.py` now centralizes semantic display rendering for module-relative type names, owner-local display names, bound-member receiver types, and resolved call-target labels.
- semantic tests that previously asserted compatibility-era storage fields such as raw receiver type strings, cast target strings, collection value-type strings, and element-type strings now assert canonical semantic meaning through shared display helpers and canonical `SemanticTypeRef` values instead.
- semantic reachability regression coverage now proves walker-style analysis continues to follow canonical refs even when a compatibility string is stale, which keeps future optimization scaffolding anchored to canonical semantic data.
- validation covers the new display-helper unit tests plus focused lowering and reachability regressions; broad semantic plus codegen validation remains required for the step.

## Recommended Execution Slices

If this roadmap is implemented incrementally, use these slices:

1. canonical-type authority
2. local use-site metadata removal
3. operation normalization
4. call and dispatch normalization
5. synthetic-node cleanup
6. semantic-layer split
7. tooling and test audit

## Success Criteria

This roadmap is complete when all of the following are true:

- semantic passes can use canonical type identity without reinterpreting type-name strings
- local use-site nodes no longer own semantic copies of declaration metadata
- operator and dispatch semantics are represented canonically rather than by token text and ad hoc field duplication
- generic synthetic semantics are either explicit node kinds or a narrowly constrained documented escape hatch
- the boundary between source-level semantic reasoning and lowered execution-oriented structure is explicit
- diagnostics and debug output remain readable through central rendering helpers rather than semantic duplication