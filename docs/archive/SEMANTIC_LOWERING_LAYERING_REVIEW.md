# Semantic Lowering Layering Review

This document is a narrower follow-up review of `compiler/semantic/lowering` only.

The goal is to propose a cleaner dependency layering for the lowering package without changing the external lowering entrypoint or forcing a large semantic redesign in one step.

## Scope

Reviewed modules:

- `compiler/semantic/lowering/orchestration.py`
- `compiler/semantic/lowering/statements.py`
- `compiler/semantic/lowering/expressions.py`
- `compiler/semantic/lowering/calls.py`
- `compiler/semantic/lowering/references.py`
- `compiler/semantic/lowering/collections.py`
- `compiler/semantic/lowering/literals.py`
- `compiler/semantic/lowering/locals.py`
- `compiler/semantic/lowering/type_refs.py`
- `compiler/semantic/lowering/ids.py`
- `compiler/semantic/lowering/executable.py`

This review is about readability, responsibility boundaries, and import direction. It is not a correctness review.

## Current Shape

The package already has a sensible coarse split:

- `orchestration.py` owns program and declaration lowering
- `statements.py` owns statement lowering
- `expressions.py` owns expression lowering
- specialized helpers exist for literals, collections, locals, IDs, and checked-type conversion

The main problem is that these responsibilities are not layered cleanly enough. Several files mix discovery, classification, conversion, and construction in the same place.

## Current Dependency Hotspots

### 1. `expressions.py` is an overloaded hub

`expressions.py` currently imports:

- `calls.py`
- `references.py`
- `collections.py`
- `literals.py`
- `locals.py`
- `type_refs.py`
- semantic operation helpers
- typecheck expression/type-resolution helpers

That makes it the central coordinator for nearly every expression concern:

- AST dispatch
- result-type inference
- call lowering
- field and identifier lowering
- array structural special-casing
- literal lowering

This is not an import cycle problem, but it does create a high-friction maintenance hub.

### 2. `calls.py` and `references.py` duplicate target discovery logic

Both modules independently perform variants of:

- local function lookup
- imported function lookup
- imported class lookup
- module-member resolution
- receiver-type inspection
- callable-class special handling
- method and interface lookup

They produce different resolved-target dataclasses, but much of the search logic is conceptually the same.

### 3. `ids.py` mixes two kinds of work

`ids.py` currently contains both:

- pure ID construction helpers like `class_id_from_type_name(...)`
- lookup and validation helpers like `resolve_instance_method_id(...)` and `resolve_static_method_id(...)`

Those are different responsibilities.

One is pure mapping.

The other is semantic lookup against typecheck state.

Keeping them together makes `ids.py` look lower-level than it actually is.

### 4. Local allocation logic exists in two places

- `locals.py` has `LocalIdTracker` for source lowering
- `executable.py` has `_HelperLocalAllocator` for post-lowering helper locals

These are not identical, but they are close enough that the duplication is a readability smell. A reader has to learn two local-allocation patterns inside the same package.

### 5. `type_refs.py` is the real bottom-layer converter, but it is treated as an incidental helper

Almost every lowering submodule imports `semantic_type_ref_from_checked_type(...)` directly.

That is a sign that checked-type to semantic-type conversion is a foundational lowering service. The code already behaves that way, but the package structure does not make that role visually explicit.

## Important Non-Issue

The lowering package entrypoint is intentionally explicit.

- import `lower_program` from `compiler.semantic.lowering.orchestration`
- do not add package-level re-exports in `compiler/semantic/lowering/__init__.py`

That boundary should stay as-is.

## Proposed Layered Structure

The cleanest practical layering is four tiers.

### Tier 1: Foundational Conversion And Mapping

Purpose:

- no AST dispatch
- no semantic node orchestration
- only stable conversion and mapping helpers

Modules:

- `type_refs.py`
- `ids.py` split into narrower helpers over time
- local-ID allocation support from `locals.py`

Responsibilities:

- checked `TypeInfo` to `SemanticTypeRef`
- ID construction from qualified names or symbol index data
- local binding to `LocalId` tracking and metadata recording

Allowed dependencies:

- semantic core modules like `compiler.semantic.types`, `compiler.semantic.symbols`, `compiler.semantic.ir`
- typecheck context/model helpers
- no imports from statement or expression dispatch layers

### Tier 2: Resolution Helpers

Purpose:

- discover what an AST thing means before building the final semantic node

Recommended modules:

- `calls.py`
- `references.py`
- optionally a future shared `resolution.py`

Responsibilities:

- identifier target classification
- module-member target classification
- receiver/member lookup
- lvalue target discovery
- call target discovery

Allowed dependencies:

- Tier 1 only
- typecheck query helpers
- no imports from statement or orchestration layers

### Tier 3: Syntax-Family Lowering

Purpose:

- convert a specific family of AST nodes into semantic IR once resolution facts are known

Modules:

- `literals.py`
- `collections.py`
- `expressions.py`
- `statements.py`

Responsibilities:

- semantic node construction
- small dispatch over AST node kinds
- local use of resolution helpers and foundational converters

Allowed dependencies:

- Tier 1
- Tier 2
- same-tier helpers only when they represent true subhandlers, not peer orchestration

### Tier 4: Program-Level Orchestration

Purpose:

- entrypoint and module/program assembly

Modules:

- `orchestration.py`
- `executable.py` as the post-semantic lowering stage

Responsibilities:

- build checked contexts
- lower whole modules and declarations
- invoke function-body lowering
- transform linked semantic IR into lowered executable IR

Allowed dependencies:

- Tier 1 to Tier 3
- no lower tier should import Tier 4

## Proposed Dependency Direction

The intended dependency direction should be:

`Tier 4 -> Tier 3 -> Tier 2 -> Tier 1`

and never the reverse.

Concretely:

- `orchestration.py` may import `statements.py`, `expressions.py`, `type_refs.py`, `ids.py`
- `statements.py` may import `expressions.py`, `collections.py`, `references.py`, `locals.py`, `type_refs.py`
- `expressions.py` may import `calls.py`, `references.py`, `collections.py`, `literals.py`, `type_refs.py`
- `calls.py` and `references.py` should depend only on Tier 1 plus typecheck helpers
- `type_refs.py`, local-ID helpers, and pure ID helpers should not depend on expression or statement lowering

## Cleaner File Responsibility Proposal

### Keep `orchestration.py` as the only public lowering entrypoint

Keep:

- `lower_program(...)`
- `lower_module(...)`
- declaration-level lowering helpers

Do not expand it into a grab bag of lower-level helper logic.

### Shrink `expressions.py` into a dispatcher plus simple node constructors

`expressions.py` should remain the main expression entrypoint, but it should become thinner.

It should ideally own:

- the top-level `lower_expr(...)` AST switch
- simple expression cases that do not need heavy resolution
  - unary
  - binary
  - cast
  - type test
  - array constructor

It should delegate more aggressively for:

- call lowering
- identifier and field reference lowering
- special array/slice structural lowering

That keeps the public API stable while reducing the current hub pressure.

### Consolidate call/reference target discovery behind a shared resolution boundary

The biggest structural cleanup opportunity is to introduce a shared target-resolution layer.

That does not have to mean a giant new file. A small shared module is enough if it centralizes the duplicated logic currently spread across `calls.py` and `references.py`.

Good candidates for consolidation:

- local or imported function lookup
- local or imported class lookup
- module-member lookup
- callable-class handling
- class versus interface member lookup

`calls.py` and `references.py` can still return different resolved-target types, but they should build those from a shared discovery result instead of independently re-deriving the same facts.

### Split `ids.py` by role over time

`ids.py` wants to become two conceptual parts:

- pure ID builders
- checked lookup/resolution helpers

The simplest end state is either:

- keep one file but separate it into clearly named sections with a documented split, or
- split into `id_builders.py` and `id_resolution.py`

Either option is better than the current mixed role.

### Unify local allocation concepts

`LocalIdTracker` and `_HelperLocalAllocator` are close enough in purpose that the package would be clearer if helper-local allocation reused the same abstraction family.

The recommended direction is:

- keep source-body lexical tracking in `LocalIdTracker`
- add a sibling helper allocator in `locals.py`, or rename the module to reflect both roles
- remove the bespoke allocator hidden inside `executable.py`

The important part is not the exact class name. The important part is that local allocation is learned in one place.

## Recommended Near-Term Module Layout

Without doing a full rename pass, the package can move toward this structure:

- `orchestration.py`
  - program/module lowering only
- `statements.py`
  - statement dispatch only
- `expressions.py`
  - thin expression dispatch
- `calls.py`
  - call target resolution and call-specific lowering helpers
- `references.py`
  - reference and lvalue target resolution and lowering helpers
- `collections.py`
  - array/slice structural special cases and dispatch classification
- `literals.py`
  - literal and string-special lowering
- `locals.py`
  - local ID allocation, binding tracking, helper-local allocation support
- `type_refs.py`
  - checked-type to semantic-type conversion
- `ids.py`
  - pure ID building first, checked lookup second, with the split made explicit

## Migration Plan

### Step 1: Clarify roles without moving files

Low risk.

- add module comments or section comments that define each file's responsibility
- separate `ids.py` into documented sections: pure builders versus lookup helpers
- move `_HelperLocalAllocator` out of `executable.py` into `locals.py` or a sibling helper module

Expected payoff:

- immediate readability gain without import churn

### Step 2: Introduce a shared resolution layer

Medium risk.

- extract shared target-discovery helpers from `calls.py` and `references.py`
- centralize callable-class detection and module-member classification
- keep existing `resolve_call_target(...)` and `resolve_*_ref_target(...)` APIs stable during migration

Expected payoff:

- less duplicated logic
- lower risk of semantic drift between call and reference resolution

### Step 3: Thin `expressions.py`

Medium risk.

- keep `lower_expr(...)` in place
- move heavier specialized subhandlers behind a smaller dispatch surface
- leave simple expression families in `expressions.py`

Expected payoff:

- expression lowering becomes easier to scan and test

### Step 4: Enforce dependency direction

Medium risk.

- after the earlier refactors, audit imports so lower tiers do not depend on higher tiers
- reduce same-tier peer imports to true subhandler relationships only
- remove remaining wildcard imports in lowering files to make dependencies visually obvious

Expected payoff:

- the package becomes easier to navigate by dependency direction rather than institutional memory

## Recommended End State

The desired end state is not many more files. The desired end state is clearer dependency direction.

The lowering package should read like this:

- foundational converters and ID helpers at the bottom
- target resolution in the middle
- AST-family lowering above that
- program-level orchestration at the top

If that layering is visible, the current package split becomes much easier to maintain even without a dramatic file reorganization.

## Summary

The main issue in `compiler/semantic/lowering` is not a hard cycle or a broken design. The issue is that responsibilities are currently mixed enough that dependency direction is implicit.

The highest-value cleanup is:

1. centralize shared call/reference discovery
2. reduce hub pressure in `expressions.py`
3. unify local allocation concepts
4. make lower-tier helper roles explicit

That should yield a cleaner lowering package without changing the explicit public entrypoint at `compiler.semantic.lowering.orchestration`.