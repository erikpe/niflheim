# Niflheim MVP Spec v0.1

## 1) Purpose and Scope

This language is a learning-focused, statically typed compiled language with intentionally simple semantics.

Primary goals:
- Keep implementation straightforward over optimization.
- Support both short-running and long-running applications.
- Be practical enough for coding competition style problems as an initial motivator.

Out of scope for v0.1:
- Inheritance
- Interfaces
- Generics
- Concurrency
- Exceptions / recoverable errors
- Advanced optimization passes
- Moving/compacting GC

---

## 2) Target and Toolchain

- Target platform: Linux x86-64 only.
- ABI: SysV x86-64.
- Compiler stage-0 implementation language: Python.
- Backend output: Intel-syntax x86-64 assembly.
- Runtime: minimal C runtime linked with generated program.

---

## 3) Type System

### 3.1 Primitive Value Types

Primitive types are always call-by-value:
- `i64`
- `u64`
- `u8`
- `bool`
- `double`
- `unit`

Defaults:
- Numeric types default to zero.
- `bool` defaults to `false`.
- `unit` has a single value.

### 3.2 Reference Types

Reference types are always:
- Heap-allocated (for class instances and runtime objects)
- Call-by-reference
- Nullable

Built-in reference types for v0.1:
- `Obj` (universal reference supertype)
- `Str`
- `Vec` (dynamic vector of `Obj`)
- `Map` (hash map `Obj -> Obj`, identity hash/equality)
- `BoxI64`, `BoxU64`, `BoxU8`, `BoxBool`, `BoxDouble`
- User-defined class instance types

Defaults:
- All reference-typed variables default to `null` unless initialized.

### 3.3 Initialization and Safety

- Uninitialized values must not be observable.
- Language/runtime guarantees deterministic default initialization.

### 3.4 Cast Rules

- Primitive-to-primitive casts are always explicit.
- Any reference type can upcast to `Obj`.
- Downcast from `Obj` to a concrete reference type is explicit and runtime-checked.
- Failed downcast panics and aborts.

---

## 4) Classes and Object Semantics

### 4.1 Classes

- Classes support fields and methods.
- No inheritance in v0.1.
- No interfaces in v0.1 (may be added later).

### 4.2 Allocation and Identity

- Class instances are heap-allocated.
- References compare by identity by default.

### 4.3 Null Semantics

- References are nullable.
- `null` dereference panics and aborts.
- v0.1 does not perform compile-time static null-dereference analysis; null-dereference checks are runtime-only.

### 4.4 Equality

- Primitive types: value equality.
- Reference types: identity equality.
- `Map` uses identity hash and identity equality for keys.

---

## 5) Built-in Reference Types (v0.1)

### 5.1 Str

- `Str` is immutable.
- Recommended encoding: UTF-8 bytes.
- Immutability simplifies hashing and sharing.

### 5.2 Vec

- `Vec` is a dynamic array of `Obj`.
- Baseline operations: `len`, `push`, `get`, `set`.

### 5.3 Map

- `Map` is a hash map from `Obj` to `Obj`.
- Key semantics: identity only.
- Baseline operations: `len`, `put`, `get`, `contains`.

### 5.4 Box Types

- `BoxI64`, `BoxU64`, `BoxU8`, `BoxBool`, `BoxDouble` are heap wrappers for primitive values.
- Primary purpose: allow primitives in `Obj`-based containers.

### 5.5 Planned Early Extensions

Likely early additions after v0.1:
- `VecI64`
- `MapStrObj`

These are specialization/performance features and should not change core semantics.

---

## 6) Modules and Visibility

- Module system supports `import` and `export`.
- Frozen v0.1 module import syntax forms:
  - `import a.b;`
  - `export import a.b;` (re-export)
- Symbols are private by default to defining module.
- `export` makes symbol visible to importing module.
- Re-export of imported symbols/modules is allowed.
- No namespace feature beyond module boundaries.

### 6.1 Imported Class Name Resolution (Design Decision)

- Resolution is symmetric between constructor calls and type annotations.
- Unqualified class names are local-first:
  - If a local class `Counter` exists, `Counter(...)` and `Counter` (type annotation) resolve to the local class.
  - Imported classes with the same unqualified name do not override locals.
- Qualified names are explicit and select imported modules:
  - Constructor call: `util.Counter(...)`
  - Type annotation: `util.Counter`
- If no local class exists, unqualified imported class names may resolve from imports only when unique.
- If multiple imported modules export the same unqualified class name and no local class shadows it, unqualified usage is a compile-time ambiguity error.

---

## 7) Runtime Model and Memory Management

### 7.1 Runtime Scope

Minimal C runtime provides:
- Allocation APIs
- GC APIs
- Panic/abort
- Basic OS wrappers (read/write/malloc-level facilities)

### 7.2 GC Strategy

- GC type: stop-the-world, non-moving, mark-sweep.
- Single-threaded runtime.
- All heap reference objects are GC-managed.

### 7.3 Root Strategy

- Exact roots only.
- Root sources:
  - Globals
  - Compiler-managed shadow stack for function locals/temporaries of reference type
- No conservative native stack scanning.
- Frozen v0.1 safepoint policy: every runtime call is a safepoint.
- Compiler requirement: before each runtime call, spill all live references into root slots.
- Ordinary language calls are not direct GC entry points, but for v0.1 codegen treat them as safepoint-adjacent and spill caller live references before the call unless callee is proven non-GC.

### 7.4 Trigger Policy

- Trigger GC when allocated bytes exceed threshold.
- After collection, next threshold is based on live bytes times growth factor.
- On allocation failure, force full GC; if still failing, panic/abort with OOM.

---

## 8) Object Layout ABI (v0.1)

- Non-moving object layout with stable pointers.
- Object header contains at minimum:
  - Type identifier
  - GC mark/flags
  - Object size
- 8-byte alignment for heap objects.
- Per-type metadata includes pointer layout information for tracing.
- Raw pointers are never exposed in source language.

---

## 9) Error Model

- Errors are unrecoverable in v0.1.
- Runtime/type violations panic and abort process.
- No exceptions and no recoverable error handling mechanism in v0.1.

---

## 10) Code Generation Requirements

- Emit SysV ABI-compatible function calling sequences.
- Generate x86-64 Intel syntax assembly.
- Insert GC-safe points around allocations/runtime calls.
- Maintain root slot correctness across expression evaluation and calls.

---

## 11) Implementation Checklist (Ordered)

## A. Spec Freeze

- [x] Freeze lexical grammar (tokens, literals, comments).
- [x] Freeze parser grammar (expressions, statements, declarations, modules).
- [x] Keep canonical EBNF in `compiler/grammar/niflheim_v0_1.ebnf`.
- [x] Freeze call syntax to positional arguments only in v0.1.
- [x] Freeze type rules (nullability, casts, equality semantics).
- [x] Freeze runtime ABI boundary (compiler <-> C runtime).

## B. Frontend

- [x] Implement lexer with source spans.
- [x] Add lexer golden tests and error tests.
- [x] Implement parser TokenStream + module-level AST parsing (`import`, `export import`, `class`, `fn`).
- [x] Add parser precedence and invalid-syntax tests.
- [x] Parse function/method bodies into statement/expression AST (replace block-span placeholders).
- [ ] Add parser error recovery + synchronization so one parse error does not abort all diagnostics.
- [x] Ensure source spans exist on all AST node types used by parser/type checker diagnostics.
- [x] Add AST debug-dump/serialization golden tests to detect parser shape regressions.
- [x] Implement symbol tables and module import/export resolution.
- [x] Add multi-module visibility tests.

## C. Type Checking

- [x] Implement primitive/reference typing rules.
- [x] Implement explicit primitive cast checks.
- [x] Implement `Obj` upcast + checked downcast.
- [x] Freeze policy: null-dereference checks are runtime-only in v0.1 (no compile-time static analysis).
- [x] Enforce non-`unit` return-path completeness (return required on all control-flow paths).
- [x] Enforce strict assignment target lvalue rules (`ident`, `field`, `index` only).
- [x] Add positive and negative type test suite.
- [x] Allow unqualified imported exported class names in type annotations when unique (local names shadow imports).
- [x] Support module-qualified type annotations (for example `util.Counter`) to disambiguate imported class name collisions.
- [x] Support unqualified imported constructor calls when unique, with local-first shadowing and ambiguity diagnostics.

## D. Runtime ABI + GC Foundation

- [x] Define C structs for object header and type metadata.
- [x] Define allocation and panic entry points.
- [x] Define shadow stack frame and root slot ABI.
- [ ] Implement mark phase from globals + shadow stack roots.
- [ ] Implement sweep phase and threshold trigger policy.
- [ ] Add GC stress tests (including cyclic references).

## E. Backend / Codegen

- [ ] Implement SysV-compliant prologue/epilogue emission.
- [ ] Implement expression codegen for primitives and refs.
- [ ] Implement control flow (`if`, loops, returns).
- [ ] Implement function calls and argument passing.
- [ ] Emit root slot updates and safe points for allocations/calls.
- [ ] Add end-to-end compile+run tests.

## F. Built-in Runtime Types

- [ ] Implement `Str` (immutable).
- [ ] Implement `Vec` (`Obj` elements).
- [ ] Implement `Map` (`Obj -> Obj`, identity key semantics).
- [ ] Implement primitive box classes.
- [ ] Add API and behavioral tests for nested containers.

## G. Tooling and Diagnostics

- [ ] Implement stable diagnostic format with spans.
- [ ] Implement minimal CLI flow (`build`, optional `run`).
- [ ] Add sample programs for sanity checks.

## H. Early Post-MVP Extension Hook

- [ ] Add container specialization extension point.
- [ ] Prototype one specialized container (`VecI64` or `MapStrObj`) without changing language core.

---

## 12) Suggested Milestones

1. Frontend-only milestone: parse + typecheck + diagnostics.
2. Runtime milestone: C runtime + GC validated via hand-written C/asm harness.
3. First executable milestone: compile small program with classes and method calls.
4. Container milestone: `Str` + `Vec` + `Map` end-to-end.
5. Stability milestone: tests for long-running allocation/churn behavior.
