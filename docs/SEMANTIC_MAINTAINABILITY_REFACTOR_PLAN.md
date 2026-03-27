# Semantic Maintainability Refactor Plan

This document turns the current semantic-module review into an execution plan.

The goal is not to redesign the compiler in one pass. The goal is to improve readability, boundary clarity, and maintainability with a small number of ordered slices that each leave the compiler in a better state.

## Why This Plan Exists

The semantic package is in a much better place than it was before the identity and canonical-type cleanups, but a few structural issues still make it harder to work in than it should be:

- compatibility-era type reconstruction still lives inside the core semantic type layer
- lowering is tightly coupled to mutable typecheck state and sequencing
- call, reference, and lvalue lowering duplicate resolution logic
- the boundary between source-level semantic IR and lowered semantic IR is still blurry
- a small amount of compatibility residue still obscures the canonical data model

None of these are immediate correctness failures. They are maintenance costs.

## Planning Principles

1. Prefer slices that improve clarity without forcing a broad compiler rewrite.
2. Move compatibility logic outward instead of spreading more of it through the core package.
3. Make authoritative data sources visually obvious in types and APIs.
4. Keep every slice testable with focused semantic regressions plus the existing broad semantic and codegen suite.

## Ordering Rationale

This plan is ordered by payoff versus risk, not by architectural purity alone.

- slice 1 removes low-risk residue and tightens authority boundaries
- slice 2 consolidates duplicated lowering logic before deeper boundary changes
- slice 3 makes the semantic-lowering contract explicit and less mutation-driven
- slice 4 is the higher-risk structural split that should only happen after the earlier simplifications land

Slices 2 and 3 are executed through the lowering review document in [docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md](docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md). The maintainability plan defines the package-level goals and sequencing; the lowering review document is the implementation guide for the lowering-heavy middle work.

## Slice 1: Finish Canonical-Type Boundary Cleanup

Payoff: high

Risk: low to medium

### Purpose

Make the canonical semantic type model easier to understand by removing the last obvious authority leaks and moving compatibility reconstruction behind a narrower boundary.

### Scope

- remove the remaining `type_name` payload fields from semantic constants in `compiler/semantic/ir.py`
- update literal lowering and constant folding to treat `LiteralExprS.type_ref` as the only semantic type authority
- move compatibility reconstruction helpers out of `compiler/semantic/types.py` into an explicitly compatibility-named boundary module, or at minimum isolate them in a clearly separated section with a smaller public surface
- simplify `compiler/semantic/optimizations/reachability.py` so the string fallback path is visibly exceptional rather than structurally central
- re-audit `SemanticVarDecl.name` and `SemanticVarDecl.type_ref` as compatibility fields and document whether they can be removed in a later dedicated slice

### Concrete Changes

- `compiler/semantic/ir.py`
  - [x] remove `IntConstant.type_name`
  - [x] remove `FloatConstant.type_name`
  - [x] remove `BoolConstant.type_name`
  - [x] remove `CharConstant.type_name`
- `compiler/semantic/lowering/literals.py`
  - [x] stop constructing constant payload type strings
- `compiler/semantic/optimizations/constant_folding.py`
  - [x] stop reconstructing folded literals through payload `type_name`
  - [x] derive folded literal type from the enclosing expression or helper arguments that produce `type_ref`
- `compiler/semantic/types.py`
  - [x] reduce the surface area of compatibility reconstruction helpers
  - [x] keep canonical helper APIs visually separate from fallback parsing code
- `compiler/semantic/optimizations/reachability.py`
  - [x] keep fallback reconstruction only where canonical traversal genuinely cannot express the edge

Deferred note:

- `SemanticVarDecl.name` and `SemanticVarDecl.type_ref` remain in place for now; they still participate in readable diagnostics and owner-local metadata flows, so they should be revisited in a dedicated follow-up slice instead of being folded into this cleanup.

### Expected Outcome

- semantic type authority becomes easier to explain in one sentence: semantic meaning flows through `SemanticTypeRef`
- readers of `types.py` no longer need to mentally mix canonical helpers and migration-era reconstruction logic
- literal payloads become plain values again instead of partially typed mini-objects

### Validation

- focused tests:
  - semantic lowering
  - semantic type helpers
  - constant folding
  - reachability
- broad tests:
  - `tests/compiler/semantic`
  - `tests/compiler/codegen`
  - existing semantic/codegen integration suite

## Slice 2: Consolidate Call, Reference, and LValue Resolution

Payoff: high

Risk: medium

Execution note: this slice is executed through the lowering review phases in [docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md](docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md). The slice here defines the maintainability goal; the lowering review document defines the implementation phases and dependency-layering work used to deliver it.

### Purpose

Remove duplicated lowering logic so member resolution rules live in one place instead of being partially reimplemented across call and reference lowering.

### Scope

- extract shared identifier and field/member resolution logic currently split across:
  - `compiler/semantic/lowering/references.py`
  - `compiler/semantic/lowering/calls.py`
- make callable-class handling explicit instead of relying on repeated `"__class__:"` string checks
- reduce repeated typecheck lookups for imported functions, imported classes, module members, instance methods, and interface methods

### Concrete Changes

- [x] introduce a shared lowering resolver module, for example `compiler/semantic/lowering/resolution.py`, that owns:
  - identifier target classification
  - module-member classification
  - receiver/member lookup for field reads, method refs, and calls
  - callable-class detection behind a named helper
- [x] convert `references.py` and `calls.py` into thin adapters that translate shared resolved targets into semantic IR nodes
- [x] replace raw `receiver_type.name.startswith("__class__:")` checks with a typed helper or explicit predicate in one place

### Expected Outcome

- behavior changes around member resolution only need to be made once
- lowering files become easier to scan because they stop mixing target discovery with target construction
- the compiler's callable-class quirk becomes explicit instead of being a hidden string convention scattered across files

### Validation

- focused tests:
  - semantic lowering
  - lowering ID helpers
  - codegen walk and expression tests that exercise calls and member access
- add a small set of resolver-focused tests for ambiguous or edge-case target classification

## Slice 3: Make the Lowering Contract Explicit

Payoff: medium to high

Risk: medium to high

Execution note: this slice is also executed through the lowering review phases in [docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md](docs/SEMANTIC_LOWERING_LAYERING_REVIEW.md). It should be implemented as the later lowering-review work that follows the Slice 2-oriented consolidation steps.

### Purpose

Clarify what semantic lowering expects from typecheck and reduce the amount of hidden mutable context management embedded in lowering itself.

### Scope

- make it explicit that lowering consumes fully checked modules rather than performing an implicit second phase of typechecking
- narrow direct mutation of `TypeCheckContext` during lowering where practical
- isolate scope-push/pop and variable declaration bridging in a smaller boundary layer so statement lowering reads as semantic construction rather than typecheck orchestration

### Concrete Changes

- `compiler/semantic/lowering/orchestration.py`
  - [x] make the lowering entry contract explicit in types and naming
  - [x] introduce a `CheckedProgram` or `CheckedModuleContext` style wrapper instead of passing raw `TypeCheckContext` everywhere
- `compiler/semantic/lowering/statements.py`
  - [x] pull scope and binding bridging into a dedicated helper object so `lower_stmt(...)` is less state-management-heavy
- `compiler/semantic/lowering/locals.py`
  - [x] formalize the bridge from typecheck bindings to `LocalId` allocation and local metadata snapshots
- [x] add module-level documentation comments explaining which typecheck facts lowering is allowed to depend on

### Expected Outcome

- the lowering entrypoint becomes easier to trust and easier to test in isolation
- hidden sequencing assumptions become visible and documentable
- future contributors can distinguish semantic construction work from typecheck bookkeeping work

### Validation

- focused tests:
  - lowering entrypoint tests
  - local metadata tests
  - semantic lowering regressions around params, receivers, blocks, and `for-in`
- broad tests:
  - full semantic and codegen suite

## Slice 4: Sharpen the Source-Semantic vs Lowered-Semantic Boundary

Payoff: medium

Risk: high

### Purpose

Reduce conceptual blur between source-near semantic IR and codegen-shaped lowered semantic IR.

### Scope

- decide which nodes are genuinely source-semantic and which exist only for execution lowering
- reduce reuse of source-semantic statement unions inside lowered IR where that reuse hides phase-specific invariants
- revisit remaining compatibility fields on source-semantic nodes that only exist because lowered/codegen paths still consume them indirectly

### Concrete Changes

- `compiler/semantic/lowered_ir.py`
  - make lowered-only statement shapes more explicit
  - consider introducing lowered wrappers for more execution-shaped constructs instead of mixing source and lowered statements in the same union
- `compiler/semantic/lowering/executable.py`
  - keep source-to-lowered rewrites localized and explicit
- `compiler/semantic/ir.py`
  - re-evaluate whether compatibility fields such as optional var-decl metadata still belong on the source-semantic graph

### Expected Outcome

- readers can answer “which phase owns this invariant?” by looking at the type, not by reading call sites
- source-level semantic IR stays about resolved meaning
- lowered semantic IR becomes clearly about execution shaping for later backend passes

### Validation

- focused tests:
  - lowering executable pass
  - layout and walk tests
  - codegen stmt tests, especially `for-in` and helper-local behavior
- broad tests:
  - full semantic, codegen, and integration suite

## Deferred Work

The following are intentionally not in the first pass of this plan:

- a broad rename or reshuffle of every semantic module
- SSA, CFG, or a completely new backend IR
- redesigning the typecheck package to match the semantic package
- large codegen architecture changes outside the semantic boundary work above

## Recommended Execution Order

1. Slice 1
2. Lowering review phases for Slice 2 and Slice 3
3. Slice 4

This means the practical execution order is Slice 1, then the lowering review phases that implement Slice 2 and Slice 3, and then Slice 4.

This order keeps the early work concrete and low-risk while improving the package enough that the later structural slices can be done with less incidental complexity.

## Definition Of Success

This plan succeeds if, after these slices:

- the semantic type layer is obviously canonical-first
- lowering rules are easier to find and less duplicated
- the lowering/typecheck boundary is explicit instead of implicit
- source semantic IR and lowered semantic IR are easier to distinguish conceptually
- new contributors can read the semantic package without needing prior refactor history to understand which representation is authoritative