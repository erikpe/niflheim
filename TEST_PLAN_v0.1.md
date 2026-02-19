# Test Plan v0.1

This document defines the testing strategy for Niflheim MVP v0.1.
It maps directly to:
- [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md)
- [ROADMAP_v0.1.md](ROADMAP_v0.1.md)
- [ABI_NOTES.md](ABI_NOTES.md)

## 1) Goals

- Validate correctness of language semantics in v0.1.
- Detect regressions quickly during rapid compiler/runtime iteration.
- Keep tests deterministic, simple, and cheap to run.
- Prioritize safety-critical areas: typing, codegen ABI correctness, and GC root correctness.

---

## 2) Test Levels

## Level A: Unit Tests

Fast tests for individual components:
- Lexer
- Parser
- Name/module resolver
- Type checker
- Small runtime units (header validation, allocator edge cases)

## Level B: Golden Tests

Text-based expected outputs:
- Token streams
- AST snapshots (or normalized trees)
- Compiler diagnostics (error code + span + message)

## Level C: Integration Tests

End-to-end compile + link + run tests:
- Language source -> assembly -> executable
- Runtime linked in
- Assert stdout/stderr/exit code

## Level D: Stress/Soak Tests

Longer-running and allocation-heavy tests:
- GC trigger behavior
- Reachability correctness
- Stability under repeated allocations and collections

---

## 3) Test Environment

- Primary OS target for execution tests: Linux x86-64.
- Stage-0 development may run frontend tests on host OS, but runtime/integration truth must be Linux x86-64.
- Build mode matrix:
  - `debug` runtime (assertions + optional GC logs)
  - `release` runtime (no heavy checks)

Recommended CI split:
1. Fast lane: unit + golden tests.
2. Full lane: integration + stress tests.

---

## 4) Pass/Fail Policy

- Any failing unit/golden/integration test blocks merge.
- Stress tests may be in a separate lane, but repeated failures block release candidate tags.
- New language feature/fix requires at least one test covering:
  - success path
  - expected failure path (if applicable)

---

## 5) Coverage by Compiler Stage

## 5.1 Lexer Tests

### Must Cover
- Keywords, identifiers, numeric literals, string literals.
- Operators, punctuation, delimiters.
- Whitespace/comments handling.
- Invalid token diagnostics.

### Example Cases
- Mixed tokens with no spaces.
- Unterminated string literal.
- Unknown character.
- Numeric edge literals for each primitive class.

### Exit Criteria
- Stable tokenization for all grammar forms.
- Error spans point to exact offending range.

---

## 5.2 Parser Tests

### Must Cover
- Expression precedence and associativity.
- Statements (`if`, loops, returns, assignments).
- Declarations (functions, classes, fields, methods).
- Module forms (`import`, `export`).

### Example Cases
- Deeply nested expressions.
- Missing delimiters/braces.
- Ambiguous-looking forms resolved by grammar.

### Exit Criteria
- All valid syntax forms parse.
- Invalid syntax produces deterministic diagnostics.

---

## 5.3 Module Resolution Tests

### Must Cover
- Import/export visibility rules.
- Re-export behavior.
- Duplicate symbol detection.
- Unresolved symbol detection.

### Example Cases
- Private symbol imported externally (must fail).
- Re-export chain across 3 modules.
- Cyclic import detection/reporting behavior.

### Exit Criteria
- Symbol resolution deterministic across multi-module projects.

---

## 5.4 Type Checker Tests

### Must Cover
- Primitive type checking.
- Reference nullability defaults and runtime null-dereference behavior.
- Explicit primitive cast enforcement.
- `Obj` upcast and checked downcast typing rules.
- Assignment/call/return compatibility.
- Non-`unit` return-path completeness across control flow.
- Strict assignment lvalue target enforcement (`ident`, `field`, `index`).
- Symmetric imported class resolution for constructors and type annotations (local-first unqualified, explicit qualified, ambiguity errors).

### Example Cases
- Implicit primitive cast attempt (must fail).
- Valid upcast to `Obj`.
- Invalid downcast path (compile-time when statically impossible; runtime when dynamic).
- Null dereference path panics deterministically at runtime (no compile-time static null analysis in v0.1).
- Non-`unit` function missing an `else` return path (must fail).
- Assignment to function symbol/expression target (must fail).
- Local class shadows imported same-name class for unqualified constructor and unqualified type annotation.
- Qualified imported class usage (`util.Counter(...)` and `util.Counter` type annotation) resolves to imported class.
- Unqualified imported class usage with duplicate exported names across imports fails with deterministic ambiguity diagnostic.

### Exit Criteria
- Positive suite passes; negative suite fails with expected diagnostics.

---

## 5.5 Codegen Tests (Assembly + ABI)

### Must Cover
- SysV argument/return handling for integer, pointer, and double.
- Stack alignment before calls.
- Callee-saved register preservation.
- Control flow lowering correctness.

### Example Cases
- Multi-arg function with mixed primitive types.
- Nested calls requiring temporaries.
- Branch-heavy function with loops.

### Exit Criteria
- Generated binaries produce expected outputs and exit codes.
- ABI-specific edge tests pass consistently.

---

## 5.6 Runtime ABI Tests

### Must Cover
- Object header initialization correctness.
- Type metadata registration/access.
- Root frame push/pop correctness.
- Panic functions terminate reliably.

### Example Cases
- Allocate object and verify header fields in debug checks.
- Push two root frames then pop in LIFO order.
- Force panic path and assert non-zero exit.

### Exit Criteria
- Runtime entry points conform to ABI contract in [ABI_NOTES.md](ABI_NOTES.md).

---

## 5.7 GC Correctness Tests

### Must Cover
- Mark reachable objects from:
  - globals
  - shadow-stack roots
  - object graph edges
- Sweep unreachable objects.
- Correct behavior with cycles.
- Threshold-triggered collection behavior.

### Required Scenarios
1. **No roots**: allocated objects are reclaimed.
2. **Single root chain**: all transitively reachable objects survive.
3. **Cycle unreachable**: cycle reclaimed.
4. **Cycle reachable**: cycle survives.
5. **Nested containers** (`Vec`/`Map`) with object references.
6. **High churn**: repeated allocate/drop loops stabilize.

### Exit Criteria
- No use-after-free crashes in valid programs.
- Reachability outcomes match expected liveness.

---

## 5.8 Built-in Type Behavior Tests

## Str
- Creation, length, indexing/byte access (if exposed), immutability checks.
- Identity equality behavior is preserved.

## Vec (Obj)
- `push`, `get`, `set`, `len` semantics.
- Reallocation paths preserve existing elements.
- Stored references remain GC-visible.

## Map (Obj -> Obj)
- Put/get/update semantics.
- Identity-based key behavior (distinct equal-looking objects are distinct keys).
- Collision and resize behavior under load.

## Box Types
- Box/unbox semantics for each primitive wrapper.
- Use inside `Vec` and `Map`.

### Exit Criteria
- Built-ins match spec semantics exactly.

---

## 6) Diagnostics Quality Tests

Diagnostics are part of MVP quality.

### Must Validate
- Error category code (if present).
- Primary span location.
- Message text stability.
- Optional secondary notes.

### Example Cases
- Type mismatch with expected/actual types.
- Unknown symbol with module context.
- Invalid cast.

### Exit Criteria
- Golden diagnostic outputs remain stable unless intentionally updated.

---

## 7) Test Data and Layout (Suggested)

Suggested repository structure:

- `tests/lexer/`
- `tests/parser/`
- `tests/resolver/`
- `tests/typecheck/`
- `tests/codegen/`
- `tests/runtime/`
- `tests/gc/`
- `tests/integration/`
- `tests/stress/`

Conventions:
- One scenario per file.
- Pair each negative test with expected diagnostic snapshot.
- Keep integration programs minimal and focused.

---

## 8) Execution Strategy by Milestone

## M0-M2 (Frontend)
- Run unit + golden tests on each change.
- Keep parsing/type diagnostics snapshots up to date.

## M3 (Runtime + GC)
- Add runtime unit tests first.
- Then add GC scenario tests before integrating full compiler output.

## M4-M5 (Codegen + Built-ins)
- Prioritize end-to-end tests with tiny programs.
- Add regression test for every fixed backend/runtime bug.

## M6 (Stabilization)
- Run stress lane regularly.
- Freeze diagnostic snapshots for release candidate.

---

## 9) Minimum Release Gate for v0.1

Before declaring v0.1 complete:

1. All unit/golden tests passing.
2. All integration tests passing on Linux x86-64.
3. GC scenario suite passing, including cyclic reachability cases.
4. At least one long-running churn stress test passes without unbounded growth caused by GC correctness defects.
5. Core built-ins (`Str`, `Vec`, `Map`, boxes) pass behavioral suite.
6. Diagnostics snapshots stable and reviewed.

---

## 10) Initial High-Value Test Cases (Starter Set)

1. **Type cast rejection**: implicit `i64 -> double` assignment fails.
2. **Obj cast success/failure**: upcast then valid/invalid downcast runtime behavior.
3. **Null dereference**: deterministic panic path.
4. **Module privacy**: importing private symbol fails.
5. **ABI mixed args**: function with `i64`, `double`, and reference args returns correct value.
6. **GC root safety**: local reference survives allocation-triggered GC.
7. **GC cycle reclaim**: unreachable two-object cycle is reclaimed.
8. **Vec growth**: many `push` operations preserve identity references.
9. **Map identity**: two distinct boxed equal values are distinct keys.
10. **Long churn**: allocate/drop loop for N iterations keeps memory bounded by policy.

---

## 11) Regression Policy

- Every bug fix adds a reproducer test before/with the fix.
- Regressions in GC/codegen/rooting are tagged critical.
- Keep flaky tests out of default lane; fix or quarantine with owner and deadline.

---

## 12) Non-Goals for v0.1 Testing

- Benchmark-driven optimization validation.
- Multi-threaded correctness tests.
- Advanced optimizer equivalence testing.

These can be added in post-v0.1 phases.
