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
- [ ] Add AST representation for array constructor expression.
- [ ] Extend type AST to represent single-dimensional arrays (`T[]`) in MVP.
- [ ] Ensure source spans are preserved for new nodes.

---

## 2) Parser

- [ ] Parse `T[]` in type positions (var declarations, params, returns, fields, casts).
- [ ] Parse `T[](len)` in expression positions as array constructor.
- [ ] Keep `expr[index]` and `expr[start:end]` behavior unchanged.
- [ ] Reject nested array syntax (`T[][]`, `T[][](len)`) with a clear diagnostic (deferred feature).
- [ ] Add parser diagnostics for malformed array syntax:
  - [ ] missing `]`
  - [ ] missing constructor `(...)`
  - [ ] invalid empty constructor args
  - [ ] invalid nested forms

---

## 3) Type Checker

### 3.1 Core typing
- [ ] Represent array types in `TypeInfo` with element type metadata.
- [ ] Type-check constructor `T[](len)`:
  - [ ] element type must resolve
  - [ ] `len` must be `u64` (or agreed conversion policy)
  - [ ] result type is `T[]`

### 3.2 Operations
- [ ] `arr[index]` and `arr.get(index)` return `T`.
- [ ] `arr[index] = v` and `arr.set(index, v)` require `v` assignable to `T`.
- [ ] `arr[start:end]` and `arr.slice(start,end)` return `T[]`.
- [ ] `arr.len()` returns `u64`.

### 3.3 Assignment and compatibility
- [ ] Enforce array invariance (`A[]` ≠ `B[]` unless exact match).
- [ ] Keep nullability behavior consistent for reference elements.
- [ ] Preserve local/imported class resolution symmetry for element type names.

---

## 4) Runtime API + Object Model

### 4.1 Runtime surface
- [ ] Define runtime array object layout with `len` and element-kind metadata.
- [ ] Add runtime constructors for primitive/reference array categories.
- [ ] Add runtime APIs for `len/get/set/slice`.
- [ ] Ensure bounds checks panic with stable error messages.

### 4.2 GC behavior
- [ ] Primitive arrays are leaf objects (no tracing of payload).
- [ ] Reference arrays trace each element slot.
- [ ] Slice allocation and copy preserve tracing correctness.

---

## 5) Codegen

- [ ] Lower `T[](len)` to the correct runtime constructor.
- [ ] Lower index get/set and slice to runtime API calls.
- [ ] Select runtime path by element category (primitive kind vs reference kind).
- [ ] Keep existing safepoint and root-slot spill correctness around calls.

---

## 6) Standard Library Surface (if used)

- [ ] Decide whether array methods are compiler-special-cased, stdlib methods, or mixed.
- [ ] Keep user-visible API consistent with frozen aliases (`[]`, `[start:end]`) and method names.

---

## 7) Tests

### 7.1 Parser tests
- [ ] Parse `u8[]` and `Person[]` types.
- [ ] Reject nested `T[][]` with a clear deferred-feature diagnostic.
- [ ] Parse constructor `T[](len)` in statements and expression contexts.
- [ ] Parse index and slice with arrays without regressions.

### 7.2 Type checker tests
- [ ] Positive: primitive arrays and class arrays construct/get/set/slice/len.
- [ ] Negative: invariance violations (`Person[]` assigned to `Obj[]`).
- [ ] Negative: wrong element assignment type.
- [ ] Negative: invalid constructor length type.

### 7.3 Codegen/unit tests
- [ ] Constructor lowering symbol selection.
- [ ] Index get/set lowering shape.
- [ ] Slice lowering shape and return type handling.

### 7.4 E2E + golden tests
- [ ] Primitive array smoke cases (`u8[]`, `i64[]`).
- [ ] Reference array smoke case (`Person[]` with default `null`).
- [ ] Slice copy behavior check (modifying source after slice does not mutate slice).
- [ ] Bounds panic cases for get/set/slice.

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
