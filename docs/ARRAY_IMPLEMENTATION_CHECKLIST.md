# Array Implementation Checklist

This checklist tracks implementation of fixed-size typed arrays with frozen syntax:
- Type form: `T[]`
- Constructor form: `T[](len)`

Use this as the execution reference while implementing parser, type checker, codegen, runtime, and tests.

---

## 0) Frozen Decisions (Do First)

- [x] Syntax frozen to `T[]` and `T[](len)`.
- [x] Arrays are fixed-size after construction.
- [x] Defaults are zero/false for primitives and `null` for references.
- [x] Baseline API frozen:
  - [x] `arr.len() -> u64`
  - [x] `arr.get(index) -> T` (alias: `arr[index]`)
  - [x] `arr.set(index, value) -> unit` (alias: `arr[index] = value`)
  - [x] `arr.slice(start, end) -> T[]` (alias: `arr[start:end]`)
- [x] Slice semantics in MVP: copying slice (new allocation).
- [x] Assignability in MVP: invariant (`A[]` only assignable to `A[]`).
- [x] Nested arrays are out of scope for current MVP array rollout (`T[][]` and deeper are disallowed for now).
- [x] Nested arrays may be added later in a dedicated follow-up phase.

---

## 1) AST + Grammar

### 1.1 Grammar
- [x] Add array type suffix syntax (`type := base_type { "[]" }`).
- [x] Add array constructor expression syntax (`array_ctor := ctor_type "[]" "(" expression ")"`).
- [x] Add slice postfix form (`[ [expr] : [expr] ]`).

### 1.2 AST model
- [x] Add AST representation for array constructor expression.
- [x] Extend type AST to represent single-dimensional arrays (`T[]`) in MVP.
- [x] Ensure source spans are preserved for new nodes.

---

## 2) Parser

- [x] Parse `T[]` in type positions (var declarations, params, returns, fields, casts).
- [x] Parse `T[](len)` in expression positions as array constructor.
- [x] Keep `expr[index]` and `expr[start:end]` behavior unchanged.
- [x] Reject nested array syntax (`T[][]`, `T[][](len)`) with a clear diagnostic (deferred feature).
- [x] Add parser diagnostics for malformed array syntax:
  - [x] missing `]`
  - [x] missing constructor `(...)`
  - [x] invalid empty constructor args
  - [x] invalid nested forms

---

## 3) Type Checker

### 3.1 Core typing
- [x] Represent array types in `TypeInfo` with element type metadata.
- [x] Type-check constructor `T[](len)`:
  - [x] element type must resolve
  - [x] `len` must be `u64` (or agreed conversion policy)
  - [x] result type is `T[]`

### 3.2 Operations
- [x] `arr[index]` and `arr.get(index)` return `T`.
- [x] `arr[index] = v` and `arr.set(index, v)` require `v` assignable to `T`.
- [x] `arr[start:end]` and `arr.slice(start,end)` return `T[]`.
- [x] `arr.len()` returns `u64`.

### 3.3 Assignment and compatibility
- [x] Enforce array invariance (`A[]` ≠ `B[]` unless exact match).
- [x] Keep nullability behavior consistent for reference elements.
- [x] Preserve local/imported class resolution symmetry for element type names.

---

## 4) Runtime API + Object Model

### 4.1 Runtime surface
- [x] Define runtime array object layout with `len` and element-kind metadata.
- [x] Add runtime constructors for primitive/reference array categories.
- [x] Add runtime APIs for `len/get/set/slice`.
- [x] Ensure bounds checks panic with stable error messages.

### 4.2 GC behavior
- [x] Primitive arrays are leaf objects (no tracing of payload).
- [x] Reference arrays trace each element slot.
- [x] Slice allocation and copy preserve tracing correctness.

---

## 5) Codegen

- [x] Lower `T[](len)` to the correct runtime constructor.
- [x] Lower index get/set and slice to runtime API calls.
- [x] Select runtime path by element category (primitive kind vs reference kind).
- [x] Keep existing safepoint and root-slot spill correctness around calls.

---

## 6) Standard Library Surface (if used)

- [x] Decide whether array methods are compiler-special-cased, stdlib methods, or mixed.
  - [x] Decision: **mixed, std-first** for MVP (minimize duplication without generics).
  - [x] Compiler owns structural syntax/desugaring and element-category call routing.
  - [x] Std/Nif owns user-facing API shape and semantics contract (Str-style surface).
  - [x] Runtime C stays minimal: storage/layout, bounds/slice safety, and GC tracing.
  - [x] Follow-up after generics: move more behavior from compiler routing into reusable std abstractions.
- [x] Keep user-visible API consistent with frozen aliases (`[]`, `[start:end]`) and method names.

---

## 7) Tests

### 7.1 Parser tests
- [x] Parse `u8[]` and `Person[]` types.
- [x] Reject nested `T[][]` with a clear deferred-feature diagnostic.
- [x] Parse constructor `T[](len)` in statements and expression contexts.
- [x] Parse index and slice with arrays without regressions.

### 7.2 Type checker tests
- [x] Positive: primitive arrays and class arrays construct/get/set/slice/len.
- [x] Negative: invariance violations (`Person[]` assigned to `Obj[]`).
- [x] Negative: wrong element assignment type.
- [x] Negative: invalid constructor length type.

### 7.3 Codegen/unit tests
- [x] Constructor lowering symbol selection.
- [x] Index get/set lowering shape.
- [x] Slice lowering shape and return type handling.

### 7.4 E2E + golden tests
- [x] Primitive array smoke cases (`u8[]`, `i64[]`).
- [x] Reference array smoke case (`Person[]` with default `null`).
- [x] Slice copy behavior check (modifying source after slice does not mutate slice).
- [x] Bounds panic cases for get/set/slice.

---

## 8) Documentation + Release Notes

- [ ] Keep spec and grammar docs aligned with implementation behavior.
- [ ] Add README usage examples for constructor, indexing, and slicing.
- [ ] Add migration notes if any old syntax/prototype is removed.

---

## 9) Suggested Implementation Order

1. AST + parser support for `T[]` and `T[](len)`.
2. Type checker support and invariance enforcement.
3. Runtime constructors/get/set/len for primitives and references.
4. Codegen lowering for constructor/get/set/len.
5. Runtime/codegen slice support.
6. Comprehensive tests + docs sync.

Deferred after MVP arrays:
- Enable nested arrays (`T[][]` and deeper) and recursive typing/runtime support.

---

## 10) Exit Criteria

- [ ] All new parser/typecheck/codegen/e2e tests pass.
- [ ] Full test suite passes via scripts/test.sh.
- [ ] Arrays work for both primitive and class/reference element types.
- [ ] No unresolved TODOs in this checklist for MVP scope.
