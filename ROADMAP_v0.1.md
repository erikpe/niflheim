# Roadmap v0.1

This roadmap operationalizes [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) into a practical sequence of milestones and weekly execution blocks.

## Planning Assumptions

- Single primary developer.
- Stage-0 compiler implemented in Python.
- Runtime implemented in C.
- Linux x86-64 SysV ABI target only.
- Schedule is flexible; "week" means one focused iteration block.

---

## Milestone Summary

1. **M0 Spec Freeze** — lock language and runtime boundaries.
2. **M1 Frontend Core** — lexer, parser, module resolution.
3. **M2 Type System** — static typing and cast/nullability rules.
4. **M3 Runtime + GC** — C runtime ABI and mark-sweep GC.
5. **M4 Codegen Core** — executable assembly output.
6. **M5 Built-ins** — `Str`, `Vec`, `Map`, box types.
7. **M6 Stabilization** — diagnostics, long-run behavior, docs.
8. **M7 Post-MVP Hook** — specialized container prototype.

---

## Week-by-Week Plan

## Week 1 — M0 Spec Freeze

### Goals
- Finalize grammar and type rules.
- Freeze compiler/runtime ABI contract.

### Deliverables
- Finalized spec sections in [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md).
- A small `ABI_NOTES.md` (optional) describing object header and root frame contract.

### Exit Criteria
- No unresolved TODOs in spec.
- A signed-off “no new core features for v0.1” decision.

### Risks
- Scope creep from adding inheritance/generics early.

### Mitigation
- Explicitly defer non-MVP items to a backlog section.

---

## Week 2 — M1 Lexer + Parser

### Goals
- Implement deterministic lexer and parser.
- Build robust source-span diagnostics.

### Deliverables
- Lexer module with token stream tests.
- Parser module producing AST for modules/classes/functions/statements/expressions.
- Golden tests for precedence and malformed syntax.

### Exit Criteria
- Parser accepts all planned syntax forms for v0.1.
- Invalid syntax reports stable, human-readable errors with source spans.

### Risks
- Grammar ambiguities causing parser churn.

### Mitigation
- Lock precedence table and associativity early.

---

## Week 3 — M1 Module Resolution + Symbol Binding

### Goals
- Implement `import`/`export` visibility model.
- Add symbol tables and duplicate/unresolved symbol checks.

### Deliverables
- Module loader and resolver.
- Visibility enforcement and re-export support.
- Multi-module tests.

### Exit Criteria
- Cross-module references resolve correctly.
- Private symbols are inaccessible outside module.

### Risks
- Circular imports edge cases.

### Mitigation
- Start with simple acyclic requirement; detect/report cycles explicitly.

---

## Week 4 — M2 Type Checker Core

### Goals
- Enforce primitive/reference types and nullability.
- Enforce explicit primitive casts.

### Deliverables
- Type checker pass over AST.
- Rules for default initialization and null checks.
- Positive/negative type test suite.

### Exit Criteria
- Type checker catches all planned invalid programs.
- Valid examples pass with stable typing behavior.

### Risks
- Under-specified cast semantics.

### Mitigation
- Add a compact cast matrix table in docs and tests.

---

## Week 5 — M2 `Obj` Casting + Class Semantics

### Goals
- Implement `Obj` upcast/downcast rules.
- Implement class field/method type validation.

### Deliverables
- Checked downcast behavior (panic on failure at runtime boundary).
- Class method/field access typing tests.

### Exit Criteria
- `Obj` conversion semantics are deterministic and tested.
- Null dereference and invalid cast paths are surfaced correctly.

### Risks
- Ambiguous behavior for `null` + cast combinations.

### Mitigation
- Define exact rules and add dedicated tests.

---

## Week 6 — M3 Runtime ABI Skeleton (C)

### Goals
- Establish object header/type metadata layout.
- Implement runtime entry points and panic API.

### Deliverables
- C runtime with allocation stubs and panic/abort.
- Shadow stack frame structs/API used by generated code.
- Minimal hand-crafted smoke test harness.

### Exit Criteria
- Compiler can target runtime call signatures without ABI uncertainty.
- Runtime compiles and links cleanly on Linux x86-64.

### Risks
- ABI mismatch between Python codegen and C structs.

### Mitigation
- Keep ABI declared in a single shared header consumed by both sides.

---

## Week 7 — M3 Mark-Sweep GC

### Goals
- Implement exact root marking and sweep reclaim.
- Add threshold-based triggering.

### Deliverables
- Mark phase using globals + shadow stack roots.
- Sweep phase reclaiming unmarked objects.
- GC stress tests (including cyclic graphs).

### Exit Criteria
- Repeated allocation churn stabilizes memory usage.
- Reachable objects survive; unreachable objects are reclaimed.

### Risks
- Root bookkeeping bugs causing corruption or leaks.

### Mitigation
- Add debug-mode GC verification and heavy assertion checks.

---

## Week 8 — M4 Codegen: Core Expressions + Control Flow

### Goals
- Emit valid SysV assembly for primitive operations and flow.

### Deliverables
- Codegen for literals, arithmetic, comparisons, branching, loops, returns.
- Function prologue/epilogue emission.

### Exit Criteria
- Non-object sample programs compile, link, and run end-to-end.

### Risks
- Calling convention errors and register clobbering bugs.

### Mitigation
- Start with strict register discipline and small verified patterns.

---

## Week 9 — M4 Codegen: References + Runtime Calls

### Goals
- Emit object allocations and method/field access code.
- Maintain GC root correctness at safe points.

### Deliverables
- Runtime call emission for allocations/casts/panic.
- Root slot updates for live references before runtime calls.
- End-to-end object program tests.

### Exit Criteria
- Object-heavy programs run correctly under GC pressure.
- No crashes in basic allocation/cast/null scenarios.

### Risks
- Missing roots around temporary expressions.

### Mitigation
- Introduce a simple “every call is a safepoint” discipline for v0.1.

---

## Week 10 — M5 Built-ins: `Str`, `Vec`, `Map`, Box Types

### Goals
- Implement minimum standard reference types.

### Deliverables
- Immutable `Str`.
- `Vec` over `Obj` with core operations.
- `Map` `Obj -> Obj` with identity hash/equality semantics.
- Primitive box wrappers.

### Exit Criteria
- Nested container programs compile and pass tests.
- Container behavior matches spec exactly.

### Risks
- `Map` behavior confusion due to identity-only keys.

### Mitigation
- Document key semantics prominently and add explicit tests.

---

## Week 11 — M6 Stabilization and Diagnostics

### Goals
- Improve compiler diagnostics and runtime error reporting.
- Validate long-running behavior.

### Deliverables
- Stable diagnostic formatting with source spans.
- Integration test suite and sample programs.
- Long-run stress script for allocation churn.

### Exit Criteria
- Error messages are clear and consistent.
- Long-run sample does not exhibit unbounded growth from GC bugs.

### Risks
- Hidden runtime defects only visible under stress.

### Mitigation
- Add nightly stress runs and minimized repro capture process.

---

## Week 12 — M7 Post-MVP Hook (`VecI64` or `MapStrObj`)

### Goals
- Validate extension pathway for specialized containers.

### Deliverables
- One specialized container prototype (`VecI64` preferred first).
- No semantic changes required in core language.

### Exit Criteria
- Specialized container works without changing v0.1 type system invariants.

### Risks
- Specialized path introducing ad-hoc rules.

### Mitigation
- Keep specialization as runtime/library feature first.

---

## Cross-Cutting Engineering Rules

- Keep tests deterministic and lightweight.
- Prefer simple, explicit implementations over clever optimizations.
- Treat runtime ABI changes as high-friction; avoid churn.
- Any feature not in v0.1 spec must be documented in backlog, not implemented.

---

## MVP Definition of Done

v0.1 is complete when all are true:

1. Compiler can build and run multi-module programs on Linux x86-64.
2. Static typing rules in spec are enforced.
3. Class instances and built-in reference types are GC-managed and stable.
4. `Str`, `Vec`, `Map`, and box wrappers function as specified.
5. Panic/abort runtime model is consistent for null/cast/OOM/runtime faults.
6. Integration and stress tests pass at an acceptable baseline reliability.

---

## Suggested Backlog (Not v0.1)

- Interfaces and method dispatch abstraction.
- Generics.
- Better `Map` key semantics variants (value-based keys for selected types).
- Optimizations (register allocation improvements, inlining, better GC heuristics).
- Optional self-hosting stages.
