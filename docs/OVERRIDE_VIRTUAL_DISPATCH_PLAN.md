# Override And Virtual Dispatch Plan

This document defines a concrete design and implementation plan for adding explicit `override` declarations and real virtual class dispatch.

The design is intentionally scoped as the next stage after single inheritance without overriding.

The main goal is to move ordinary class instance calls from early-bound concrete labels to explicit dynamic dispatch semantics, while preserving a clean path for later devirtualization and `super.method(...)` support.

## Status

Planned.

The current compiler/runtime supports single inheritance without overriding.

Today, inherited methods resolve to their declaring class and ordinary class instance calls are lowered as direct calls.

## Why This Plan Exists

Single inheritance established the object-layout and subtype foundations needed for real OO dispatch:

- base fields are a physical prefix of subclass fields
- runtime class checks walk a superclass chain
- subclass metadata already inherits effective interface implementation state
- semantic and lowered IR already distinguish direct class calls from dynamic interface calls

What is still missing is the method-dispatch half of OO semantics.

Today, all of the following assumptions are still baked into the pipeline:

- every ordinary class instance call is resolved to one concrete `MethodId` during lowering
- that `MethodId` doubles as both the method-body identity and the dispatch target
- subclasses may not redeclare inherited method names at all
- class runtime metadata contains superclass and interface information, but no virtual dispatch table
- interface dispatch is explicit and dynamic, but class dispatch is still early-bound

That works for inherited-method reuse, but it does not scale to:

- method overriding in subclasses
- polymorphic calls through base-class typed receivers
- base methods calling overridden subclass implementations through `__self`
- later direct-call devirtualization based on exact receiver facts
- later `super.method(...)` support with explicit non-virtual dispatch

This plan addresses the real structural problem rather than patching call lowering heuristically in codegen.

## Goals

- Add explicit `override` declarations for subclass instance methods.
- Add virtual dispatch for ordinary non-static, non-private instance methods.
- Preserve direct-call lowering for functions, constructors, static methods, and private methods.
- Keep method-body identity separate from virtual dispatch slot identity.
- Make interface implementation metadata follow the effective overridden method implementation.
- Keep the design compatible with later semantic devirtualization passes.
- Leave a clean path for later `super.method(...)` support without redefining method identity again.

## Non-Goals

- No multiple inheritance.
- No abstract classes.
- No protected visibility tier.
- No field hiding.
- No method overloading.
- No covariant or contravariant override rules in this slice.
- No generic virtual dispatch.
- No speculative codegen-only devirtualization.
- No `super.method(...)` in the first implementation slice unless explicitly pulled forward.
- No fat-pointer object representation.

## Current Baseline

The current single-inheritance implementation already exposes the main boundaries this plan must change.

### Frontend And AST

- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
  - method declarations have no `override` marker.
- [compiler/frontend/tokens.py](../compiler/frontend/tokens.py)
  - there is no `override` keyword.

### Typecheck Model And Declaration Collection

- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
  - `ClassInfo.method_members` tracks the effective visible method by name, but does not distinguish slot origin from selected implementation.
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
  - inherited method name reuse is rejected outright.
- [compiler/typecheck/relations.py](../compiler/typecheck/relations.py)
  - already handles subtype-aware class relations, which virtual dispatch will depend on semantically.

### Semantic Symbols And Lowering

- [compiler/semantic/symbols.py](../compiler/semantic/symbols.py)
  - `MethodId` identifies a concrete declaring-class method body.
- [compiler/semantic/lowering/resolution.py](../compiler/semantic/lowering/resolution.py)
  - ordinary instance member lookup resolves directly to one concrete `MethodId`.
- [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py)
  - ordinary class receiver calls lower to `ResolvedInstanceMethodCallTarget`.
- [compiler/semantic/ir.py](../compiler/semantic/ir.py)
  - semantic IR distinguishes direct instance calls from dynamic interface calls, but has no explicit virtual-class call target.

### Codegen And Metadata

- [compiler/codegen/class_hierarchy.py](../compiler/codegen/class_hierarchy.py)
  - method lookup walks the inheritance chain until it finds the first declaration, which is sufficient for inherited reuse but not for overriding.
- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - declaration tables know concrete method labels only.
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - emits superclass and interface metadata, but no class virtual tables.
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - emits `RtType` records with no class dispatch table fields.
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - lowers ordinary class method calls as direct named calls.

### Runtime

- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - `RtType` contains superclass and interface metadata, but no vtable pointer/count.
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - interface dispatch uses explicit metadata lookup; there is no runtime helper or ABI surface for virtual class calls.

## Core Semantics

## 1. Which Methods Are Virtual

For this stage:

- ordinary instance methods are virtual by default
- `static` methods are never virtual
- `private` instance methods are never virtual
- constructors are never virtual

Rationale:

- this matches the user expectation for OO dispatch once inheritance exists
- it avoids a second keyword such as `virtual` in the first design
- it keeps the language surface smaller while preserving explicitness at the override point

## 2. `override` Is Required

If a subclass redeclares an inherited virtual method, the declaration must use `override`.

Recommended syntax:

```nif
class Derived extends Base {
    override fn read() -> i64 {
        return 42;
    }
}
```

Semantics:

- a same-name inherited virtual method must exist
- the inherited method must be non-private and non-static
- the overriding method must match the inherited signature exactly in this slice
- omitting `override` is an error when a base method exists
- using `override` with no matching base method is also an error

Rationale:

- preserves the explicitness that slice 2 intentionally reserved by banning pseudo-overrides
- keeps source intent unambiguous
- prevents accidental behavior changes from method-name collisions

## 3. Dispatch Semantics

An ordinary instance method call uses the runtime class of the receiver, not the static receiver type, whenever the target method is virtual.

That means:

- `base_ref.read()` dispatches to `Derived.read()` when `base_ref` refers to a `Derived`
- calls inside base methods through `__self` also use virtual dispatch
- static calls remain direct and class-qualified
- private method calls remain direct and declaring-class bound

This is the main user-visible behavior change of the feature.

## 4. Method Body Identity vs Virtual Slot Identity

This stage must keep two concepts distinct:

- concrete method body identity:
  - still represented by `MethodId`
  - still used for emitted text labels and direct-call targets
- virtual slot identity:
  - anchored to the method declaration that first introduced the virtual member in the inheritance chain
  - stable across all subclasses

Rationale:

- a vtable entry must remain position-stable across the whole inheritance chain
- overridden implementations replace the slot contents, not the slot identity
- later `super.method(...)` should target a concrete base implementation, not “the slot” abstractly

## 5. Interface Conformance Uses Effective Implementations

If a base class implements an interface method and a subclass overrides that method, the subclass's interface metadata must point to the override.

This means interface implementation metadata must be built from the class's effective method implementation map, not from naive declaring-class lookup.

Rationale:

- keeps interface dispatch and class dispatch semantically aligned
- avoids emitting stale interface tables that still call base implementations after override

## 6. Signature Rules For Overrides

In the first stage, override compatibility should be exact:

- same method name
- same parameter count
- same parameter types
- same return type
- instance method only

No variance rules yet.

Rationale:

- consistent with current interface-conformance strictness
- avoids introducing a second layer of subtype reasoning during the virtual-dispatch rollout

## 7. Scope Of `super.method(...)`

This plan intentionally keeps `super.method(...)` out of the core override + virtual dispatch rollout unless it is explicitly chosen as a follow-up slice in the same series.

Reason:

- override and virtual dispatch require a new dynamic-dispatch path
- `super.method(...)` requires an explicit non-virtual base-call path
- both are related, but they are not the same change

The design in this plan should preserve a clean later path for `super.method(...)` by keeping direct-call targets distinct from virtual-call targets.

## Main Design Decisions

## 1. Add A Dedicated Virtual Class Call Target In Semantic IR

Recommended new semantic IR node shape in [compiler/semantic/ir.py](../compiler/semantic/ir.py):

```python
@dataclass(frozen=True)
class VirtualMethodCallTarget:
    slot_owner_class_id: ClassId
    slot_method_name: str
    access: BoundMemberAccess
```

The exact field names may differ, but the intent should be:

- identify the virtual slot origin
- preserve the receiver access explicitly
- keep this target distinct from `InstanceMethodCallTarget`

Rationale:

- ordinary class dispatch becomes explicit in semantic IR, just like interface dispatch already is
- direct-call rewrites can still convert virtual calls into `InstanceMethodCallTarget` later
- codegen stays a straightforward lowering of semantic call target shapes

## 2. Keep Direct Instance Calls As A Separate IR Shape

`InstanceMethodCallTarget` should remain the explicit direct-call form.

It should be used for:

- devirtualized virtual calls
- future `super.method(...)` calls
- any other intentionally non-virtual internal lowering path

Rationale:

- avoids overloading one node shape with both “ordinary virtual call” and “forced direct body call” meaning
- preserves a clean optimization boundary

## 3. Inline Virtual Dispatch In Codegen, Do Not Route It Through A Runtime Helper First

Recommended first implementation:

- codegen emits the vtable load inline from the object's `RtType`
- codegen emits the final indirect call inline
- null-dereference behavior follows the same runtime failure policy as interface dispatch

Avoid a first-class runtime helper unless implementation complexity proves otherwise.

Rationale:

- class virtual dispatch is structurally simpler than interface dispatch
- a helper would add avoidable call overhead to the hot path
- interface dispatch still needs helper logic because it searches interface metadata

## 4. Extend `RtType` Instead Of Introducing A Separate Side Structure

Recommended runtime metadata addition in [runtime/include/runtime.h](../runtime/include/runtime.h):

```c
const void* class_vtable;
uint32_t class_vtable_count;
uint32_t reserved2;
```

or the moral equivalent.

Rationale:

- `RtType` is already the canonical runtime metadata anchor for class checks and interface dispatch
- this keeps all runtime type information reachable from `header->type`
- later devirtualization can bypass the lookup entirely without changing metadata shape

## 5. Build One Effective Method Index For Typecheck, Metadata, And Lowering

The current codebase already has multiple places that partially answer “which method does this class expose for this name?”

This stage should centralize that into a single effective-method model with at least:

- slot-introducing declaration lookup
- selected implementation lookup for a concrete class
- stable slot ordering for vtable emission

Primary places:

- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
- [compiler/codegen/class_hierarchy.py](../compiler/codegen/class_hierarchy.py)

Rationale:

- avoids duplicating override rules in typecheck and codegen separately
- lets interface metadata reuse the same effective implementation map
- reduces the risk of direct-call and metadata emission drifting apart

## Tradeoffs And Risks

## Virtual-By-Default vs `virtual` Keyword

Recommended choice:

- virtual by default for ordinary instance methods
- explicit `override` on overriding declarations

Tradeoff:

- simpler user model and smaller surface syntax
- more ordinary calls become indirect until later devirtualization rewrites them

This is the right tradeoff because the compiler already has an explicit devirtualization architecture for interface calls, and the same pattern can be extended later to class virtual calls.

## Exact Override Matching vs Flexible Variance

Recommended choice:

- exact match only in the first stage

Tradeoff:

- slightly less expressive than richer OO languages
- dramatically easier to validate and reason about across typecheck, interface conformance, and vtable layout

## Codegen-Inline Dispatch vs Runtime Helper

Recommended choice:

- inline class virtual dispatch in codegen

Tradeoff:

- somewhat more backend-specific assembly logic
- avoids baking extra runtime helper cost into every virtual call

## Shipping Override Without `super.method(...)`

Recommended choice:

- acceptable for the first core rollout

Tradeoff:

- keeps the override/dispatch slice smaller and more defensible
- users cannot yet call the base implementation explicitly from overrides

The plan still preserves a clean next step for `super.method(...)` by retaining a distinct direct-call target shape.

## Ordered Implementation Plan

This feature should be implemented in ordered slices.

## Slice 1: Frontend Surface For `override`

Purpose:

- add the source-level syntax needed to express an override explicitly

What to change:

- [compiler/frontend/tokens.py](../compiler/frontend/tokens.py)
  - add `override` keyword/token
- [compiler/frontend/ast_nodes.py](../compiler/frontend/ast_nodes.py)
  - extend method declaration AST with `is_override`
- parser modules that handle class member declarations
  - parse `override fn ...` for instance methods
  - reject invalid combinations such as `override static fn ...`

What to test:

- parser tests for valid `override fn` syntax
- parser tests for invalid keyword placement
- AST snapshot coverage if relevant in this repo's frontend tests

Checklist:

- [x] add `override` keyword/token
- [x] add AST support for override methods
- [x] parse `override fn ...` in class bodies
- [x] add parser/frontend coverage

## Slice 2: Typecheck Override Legality And Effective Method Metadata

Purpose:

- define the language rules for overriding and build the effective-method metadata needed by later stages

What to change:

- [compiler/typecheck/model.py](../compiler/typecheck/model.py)
  - extend method metadata so it can distinguish:
    - declaring method body owner
    - virtual slot origin owner
    - effective selected implementation
- [compiler/typecheck/declarations.py](../compiler/typecheck/declarations.py)
  - replace the blanket inherited-name collision error for methods with explicit override validation
  - keep same-name collisions illegal for fields and for non-override methods
- [compiler/typecheck/relations.py](../compiler/typecheck/relations.py)
  - add helpers for exact override signature comparison if needed

Semantics to enforce:

- override requires a matching inherited virtual instance method
- inherited private methods are not overridable
- static methods are not overridable
- exact signature match only
- missing `override` on inherited virtual method reuse is an error
- stray `override` with no base method is an error

What to test:

- valid override with exact signature
- invalid override with wrong return type
- invalid override with wrong parameter type or arity
- invalid override of private/static/base-missing methods
- invalid inherited name reuse without `override`
- inherited interface implementation still accepted after override metadata refactor

Checklist:

- [x] define override legality rules in typecheck
- [x] replace no-redeclaration method rule with explicit override validation
- [x] add effective-method metadata carrying slot origin and selected implementation
- [x] add typecheck unit coverage for valid and invalid overrides

## Slice 3: Symbol And Semantic IR Separation Between Virtual And Direct Calls

Purpose:

- represent ordinary virtual class calls explicitly in semantic IR instead of smuggling them through direct-call targets

What to change:

- [compiler/semantic/ir.py](../compiler/semantic/ir.py)
  - add `VirtualMethodCallTarget`
  - update helper functions such as `call_target_dispatch_mode` and `call_target_receiver_access`
- [compiler/semantic/lowering/resolution.py](../compiler/semantic/lowering/resolution.py)
  - return virtual-slot-aware member resolution info for ordinary instance methods
- [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py)
  - lower ordinary instance calls to `VirtualMethodCallTarget`
  - keep static and private method calls on direct targets
- [compiler/semantic/lowering/references.py](../compiler/semantic/lowering/references.py)
  - preserve direct method-reference semantics intentionally; do not accidentally reinterpret all method refs as virtual

What to test:

- semantic lowering tests showing base-typed receiver calls become virtual targets
- semantic lowering tests showing static/private/direct paths remain direct
- display/debug output tests if semantic IR pretty-printing covers call targets

Checklist:

- [x] add explicit virtual class call target to semantic IR
- [x] lower ordinary instance calls to virtual targets
- [x] preserve direct-call targets for static/private paths
- [x] add semantic lowering coverage

## Slice 4: Compute Stable Virtual Slots Across The Inheritance Chain

Purpose:

- give codegen and metadata a stable, testable source of truth for vtable layout

What to change:

- [compiler/codegen/class_hierarchy.py](../compiler/codegen/class_hierarchy.py)
  - add effective virtual-member modeling alongside field layout modeling
  - support:
    - slot ordering
    - slot owner lookup
    - effective implementation lookup for each class
- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - add declaration-table support for virtual slot indices and vtable symbols

Design rule:

- subclasses inherit base slot order unchanged
- an override replaces the implementation pointer in an existing slot
- introducing a new virtual method appends a new slot after inherited slots

What to test:

- stable base slot index across subclasses
- override replaces implementation without changing slot index
- new subclass virtual method appends at the end
- inherited non-overridden methods remain mapped to base implementation labels

Checklist:

- [ ] compute stable virtual slot ordering per class hierarchy
- [ ] compute effective implementation per slot per class
- [ ] expose slot metadata through declaration/codegen tables
- [ ] add codegen-model tests for slot stability and replacement

## Slice 5: Extend Runtime Metadata For Class Vtables

Purpose:

- give runtime objects enough metadata to support virtual class dispatch from `header->type`

What to change:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - extend `RtType` with class vtable pointer/count fields
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - add class-vtable metadata records
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - emit class vtable tables and wire them into `RtType` records
- [compiler/codegen/symbols.py](../compiler/codegen/symbols.py)
  - add stable symbol names for class vtables if needed

What to test:

- emitted type record includes class vtable pointer/count fields
- emitted vtable symbols have stable layout
- override case emits subclass slot contents with overriding label
- interface implementation metadata still uses effective implementations after the refactor

Checklist:

- [ ] extend `RtType` for class vtable metadata
- [ ] emit per-class vtable tables in codegen metadata
- [ ] wire vtable pointer/count into type records
- [ ] update metadata/codegen tests

## Slice 6: Emit Virtual Class Calls In Codegen

Purpose:

- make ordinary instance calls actually dispatch through the runtime class at execution time

What to change:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - add virtual-class-call emission path
  - inline:
    - receiver evaluation
    - null check or equivalent runtime panic path
    - `header->type` load
    - vtable load
    - slot entry load
    - indirect call
- any ABI helper modules if call planning needs a shared indirect-call helper

Important backend rule:

- keep rooting and call-argument preservation semantics correct across the new indirect call path

What to test:

- assembly tests showing indirect vtable call instead of direct label call for virtual targets
- assembly tests showing static/private calls still use direct labels
- root-slot and temp-root coverage if the indirect call path introduces different preservation requirements

Checklist:

- [ ] add codegen path for virtual class calls
- [ ] preserve existing rooting/call ABI guarantees across indirect calls
- [ ] keep static/private calls direct
- [ ] add assembly-level coverage for new dispatch shape

## Slice 7: End-To-End Override Semantics Validation

Purpose:

- lock the user-visible runtime behavior before later optimization work starts rewriting calls again

What to change:

- [tests/compiler/integration/](../tests/compiler/integration/)
  - add focused runtime integration programs for override through base-typed receivers
- [tests/golden/](../tests/golden/)
  - add positive golden cases if this feature is stable enough for language-level end-to-end assertions
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](../docs/LANGUAGE_MVP_SPEC_V0.1.md)
  - update class-method semantics once implemented
- [README.md](../README.md)
  - update current status summary when the feature lands

What to test:

- base-typed receiver dispatches to subclass override
- base method calling another virtual method through `__self` reaches the override
- inherited non-overridden methods still behave the same
- override + interface dispatch agrees on the selected implementation
- null receiver still panics deterministically

Checklist:

- [ ] add integration coverage for override through base-typed receivers
- [ ] add end-to-end language/golden coverage where appropriate
- [ ] update language/docs references after behavior is stable

## Slice 8: Optional Follow-Up `super.method(...)`

Purpose:

- complete the practical override surface with an explicit non-virtual base-call path

This slice is intentionally optional and should not block the core rollout.

What to change:

- frontend syntax and parser for `super.method(...)`
- typecheck validation that the referenced base method exists and is callable
- semantic IR lowering to a direct base `InstanceMethodCallTarget`
- tests showing override bodies can invoke the base implementation explicitly

What to test:

- valid base-method call from override
- invalid `super.method(...)` without superclass or without matching base method
- codegen path remains direct, not virtual

Checklist:

- [ ] decide whether to include `super.method(...)` in the same series or leave it as follow-up
- [ ] if included, lower it as explicit direct base dispatch
- [ ] add dedicated frontend/typecheck/codegen coverage

## Recommended Execution Order

1. Frontend `override` syntax.
2. Typecheck legality and effective-method metadata.
3. Semantic IR split between virtual and direct class calls.
4. Stable slot computation.
5. Runtime metadata and vtable emission.
6. Virtual-call codegen.
7. End-to-end validation and docs.
8. Optional `super.method(...)` follow-up.

## Testing Strategy Summary

The minimum validation set for the core rollout should include:

- parser coverage for `override`
- typecheck coverage for legal/illegal overrides
- semantic lowering coverage for virtual vs direct call targets
- metadata/codegen model coverage for slot stability and overriding replacement
- assembly coverage for indirect vtable calls
- integration coverage for runtime behavior through base-typed receivers
- interface-dispatch regression coverage showing overrides update effective interface implementation targets

## Key Risks To Watch Closely

1. Conflating direct-call identity with virtual slot identity.
2. Emitting interface metadata from stale base implementations after override.
3. Letting codegen infer dispatch kind heuristically instead of preserving it explicitly in semantic IR.
4. Breaking rooting/temporary preservation on the new indirect-call path.
5. Allowing silent pseudo-overrides by weakening `override` validation too early.

This plan avoids those risks by making dispatch shape explicit, centralizing effective-method metadata, and keeping the override rules intentionally narrow in the first rollout.