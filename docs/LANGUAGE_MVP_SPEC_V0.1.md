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
- `T[]` (fixed-size array type constructor)
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
- Fields and methods can be declared `private` for class-only access.
- Methods are instance methods by default.
- Static methods are declared explicitly with `static fn` and are called on the class name (`Counter.add(...)`).
- No inheritance in v0.1.
- No interfaces in v0.1 (may be added later).

Visibility details:

- `private` applies to class fields and class methods (instance or static).
- Private members are accessible only from methods declared inside the same class.
- Access from free functions, other classes, and importing modules is rejected by type checking.
- Leading underscore naming (for example `_value`) is convention-only and has no visibility semantics.

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
- `Str` stores raw `u8` bytes only (no encoding semantics in v0.1).
- String literals produce `Str` instances and support C-style escapes (`\"`, `\\`, `\n`, `\r`, `\t`, `\0`, `\xHH`).
- `Str` is indexable via `[]` with `i64` index and returns `u8`.
- `std.str::StrBuf` is a mutable byte-buffer companion type with explicit methods (for example: `from_str`, `len`, `get_u8`, `set_u8`, `to_str`).

### 5.2 Vec

- `Vec` is a dynamic array of `Obj`.
- Baseline operations: `len`, `push`, `get`, `set`.
- `len() -> u64`.
- `with_capacity(capacity: u64) -> Vec`.
- Index and slice parameters are signed: `get(index: i64)`, `set(index: i64, value: Obj)`, `slice(begin: i64, end: i64)`.

### 5.3 Map

- `Map` is a hash map from `Obj` to `Obj`.
- Key semantics: identity only.
- Baseline operations: `len`, `put`, `get`, `contains`.

### 5.4 Box Types

- `BoxI64`, `BoxU64`, `BoxU8`, `BoxBool`, `BoxDouble` are heap wrappers for primitive values.
- Primary purpose: allow primitives in `Obj`-based containers.
- Box instances are immutable in v0.1.

### 5.5 Planned Early Extensions

Likely early additions after v0.1:
- `VecI64`
- `MapStrObj`

These are specialization/performance features and should not change core semantics.

### 5.6 Arrays (Frozen Syntax and Semantics)

- Type syntax: `T[]`
  - Examples: `u8[]`, `i64[]`, `Person[]`.
- Construction syntax: `T[](len)`
  - Example: `var a: u8[] = u8[](23);`
  - Example: `var people: Person[] = Person[](64);`
- Size is fixed after construction.
- Default element initialization:
  - Primitive element type: zero value (`0`, `0u`, `0u8`, `false`, `0.0`).
  - Reference/class element type: `null`.
- Baseline operations:
  - `arr.len() -> u64`
  - `arr.get(index) -> T`, alias `arr[index]`
  - `arr.set(index, value) -> unit`, alias `arr[index] = value`
  - `arr.slice(start, end) -> T[]`, alias `arr[start:end]`
- Bounds violations panic and abort.
- `slice` semantics in v0.1: copying slice (new array allocation).
- Array assignability policy in v0.1: invariant (`A[]` is assignable only to `A[]`, except `null` to reference arrays).
- Nested arrays are deferred for now: `T[][]` and deeper are not part of the current MVP array rollout and should be rejected with a clear diagnostic.
- Nested arrays may be added in a later follow-up milestone.
- Although syntax is generic-like, `T[]` is a built-in type constructor, not user-defined generics.

Implementation status note (current tree):
- Array features above are implemented and validated via parser/typecheck/codegen/runtime tests and golden tests.
- Ownership is currently compiler+runtime-first for arrays:
  - Compiler handles array syntax/desugaring and element-category runtime call routing.
  - Runtime provides storage/layout + `len/get/set/slice` primitives + bounds/GC behavior.
  - A stdlib-first array wrapper layer is a planned follow-up, not the current implementation state.

  ### 5.7 Indexing Sugar Canonicalization Policy (Direction)

  To support stdlib-first container implementations (starting with `Vec`), indexing sugar semantics are defined by canonical method lowering:

  - `x[i]` is equivalent to `x.get(i)`
  - `x[i] = v` is equivalent to `x.set(i, v)`
  - `x[a:b]` is equivalent to `x.slice(a, b)`

  Compiler implementation policy:

  - Keep a single semantic path (method-call semantics) rather than independent index/method paths.
  - Prefer structural eligibility over hard-coded type-name checks.
  - A type participates in sugar when it provides compatible methods (for example `get`, `set`, `slice` with `i64` index parameters).

  This policy is intentionally future-oriented for stdlib container families (for example specialized vectors), map-like classes, and potential stdlib implementations of `Str`/`StrBuf` backed by `u8[]`.

---

## 6) Modules and Visibility

- Module system supports `import` and `export`.
- Frozen v0.1 module import syntax forms:
  - `import a.b;`
  - `export import a.b;` (re-export)
- External function declaration forms:
  - `extern fn name(args...) -> type;`
  - `export extern fn name(args...) -> type;` (re-export)
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

### 6.2 Unsafe Systems Layer (Proposed Extension)

Goal: allow stdlib code to implement low-level runtime-adjacent logic (for example `Str`/`StrBuf`) in Nif while keeping normal user code safe by default.

#### 6.2.1 Safety Boundary

- Unsafe operations are only legal inside `unsafe { ... }` blocks or `unsafe fn` bodies.
- Outside unsafe context, all pointer and raw-memory operations are compile-time errors.
- Inside unsafe context, compiler restrictions are intentionally minimal: raw pointer operations, casts, arithmetic, and memory access are allowed.
- Unsafe author contract: invariants required by safe code must be re-established at the unsafe boundary (end of block / function return).
- Initial rollout policy: unsafe features are available to stdlib modules only.
- Optional later policy: user modules may opt in via explicit compiler flag/feature gate.

#### 6.2.2 C-style Pointer Model

- Add raw pointer types:
  - `*T` (all raw pointers are mutable in unsafe mode)
  - `*u8` for byte buffers
- There is no separate const/read-only raw pointer kind in MVP unsafe.
- `null` is a valid pointer value.
- Pointer equality is address equality.
- No implicit dereference in expression typing.

#### 6.2.3 C-style Pointer Operations

- Address-of: `&x` (yields pointer to local/field as allowed by borrowability rules).
- Dereference: `*p` (read/write requires non-null, properly aligned pointer).
- Pointer arithmetic:
  - `p + n`, `p - n` (scaled by `sizeof(T)`)
  - `p2 - p1` returns element-distance (`i64`) when same base element type.
- Explicit pointer casts only, for example `(*u8)p`.
- Integer/pointer casts are explicit and unsafe-only.

#### 6.2.4 Unsafe Intrinsics (Minimal Set)

Expose through `std.unsafe` (or equivalent reserved std module):

- Allocation:
  - `malloc(size: u64) -> *u8`
  - `free(ptr: *u8) -> unit`
- Raw memory:
  - `memcpy(dst: *u8, src: *u8, size: u64) -> unit`
  - `memmove(dst: *u8, src: *u8, size: u64) -> unit`
  - `memset(dst: *u8, byte: u8, size: u64) -> unit`
  - `memcmp(a: *u8, b: *u8, size: u64) -> i64`

Notes:
- `malloc` panics on OOM in MVP policy (no null-return contract).
- These APIs are intentionally low-level and unsafe-only.

#### 6.2.5 GC and Safepoint Rules for Unsafe Code

- Raw pointers to GC-managed object interiors are permitted in unsafe mode, but lifetime validity across safepoints is the unsafe author's responsibility.
- If such pointers can survive across safepoints, pinning or equivalent discipline is required by contract (violation is undefined behavior).
- Unsafe code may use `malloc` memory freely; GC does not trace it.
- Any operation that may trigger GC remains a safepoint.
- Compiler enforces existing root-spill policy before safepoints, including in unsafe code.
- Optional extension: `nogc` block/function attribute for regions that must not safepoint; calling safepoint-capable functions in `nogc` is a compile-time error.

#### 6.2.6 Operational Restrictions

- Dereferencing null is undefined behavior at unsafe level (implementation may panic in debug runtime builds).
- Out-of-bounds pointer arithmetic/dereference is undefined behavior.
- Alignment violations are undefined behavior unless unaligned load/store intrinsics are explicitly added.
- Double-free/use-after-free are undefined behavior.
- Any failure to restore safe-language invariants at unsafe boundary is undefined behavior.

#### 6.2.7 Intended Usage

- Primary target: stdlib implementation code for core containers/byte operations.
- Non-goal: replacing high-level safe APIs with pointer-first style in general user code.
- Safe wrappers over unsafe internals are encouraged as the public API surface.

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
- Raw pointers are not exposed in safe language mode. They are only available through the proposed unsafe systems layer.

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
- [x] Implement mark phase from globals + shadow stack roots.
- [x] Implement sweep phase and threshold trigger policy.
- [x] Add GC stress tests (including cyclic references).

## E. Backend / Codegen

- [x] Implement SysV-compliant prologue/epilogue emission.
- [x] Implement expression codegen for primitives and refs.
- [x] Implement control flow (`if`, loops, returns).
- [x] Implement function calls and argument passing.
- [x] Add codegen safepoint hooks around runtime-call sites.
- [x] Emit root slot updates at safepoints for allocations/runtime calls.
- [x] Ensure SysV stack alignment at every call site.
- [x] Wire full shadow-stack ABI calls (`rt_root_frame_init`, `rt_push_roots`, `rt_root_slot_store`, `rt_pop_roots`).
- [x] Restrict safepoint root-slot spills to exact reference-typed locals/temporaries.
- [x] Add end-to-end compile+run tests.
- [x] Add method callee lowering for call expressions.
- [x] Add constructor callee lowering for call expressions.

## F. Built-in Runtime Types

- [x] Implement `Str` (immutable).
- [x] Implement `Vec` (`Obj` elements).
- [ ] Implement `Map` (`Obj -> Obj`, identity key semantics).
- [x] Implement primitive box classes.
- [ ] Add API and behavioral tests for nested containers.

## G. Tooling and Diagnostics

- [ ] Implement stable diagnostic format with spans.
- [ ] Implement minimal CLI flow (`build`, optional `run`).
- [ ] Add sample programs for sanity checks.

## H. Early Post-MVP Extension Hook

- [ ] Add container specialization extension point.
- [ ] Prototype one specialized container (`VecI64` or `MapStrObj`) without changing language core.
- [ ] Extend call lowering to support >6 positional args (stack-passed args under SysV).
- [ ] Add indirect callee lowering for call expressions.
- [x] Add floating-point call/return ABI lowering (`xmm0`-`xmm7` path).
- [ ] Move local slot allocation from name-based to lexical-scope-aware slots (no shadow aliasing).
- [ ] Add unsafe systems layer (`unsafe` blocks/functions + stdlib-only gate).
- [ ] Add C-style raw pointer types and pointer arithmetic.
- [ ] Add minimal `std.unsafe` intrinsics (`malloc/free/memcpy/memmove/memset/memcmp`).
- [ ] Define and enforce GC/safepoint restrictions for unsafe and optional `nogc` regions.

---

## 12) Suggested Milestones

1. Frontend-only milestone: parse + typecheck + diagnostics.
2. Runtime milestone: C runtime + GC validated via hand-written C/asm harness.
3. First executable milestone: compile small program with classes and method calls.
4. Container milestone: `Str` + `Vec` + `Map` end-to-end.
5. Stability milestone: tests for long-running allocation/churn behavior.
