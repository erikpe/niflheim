# Niflheim MVP Spec v0.1

## 1) Purpose and Scope

This language is a learning-focused, statically typed compiled language with intentionally simple semantics.

Primary goals:
- Keep implementation straightforward over optimization.
- Support both short-running and long-running applications.
- Be practical enough for coding competition style problems as an initial motivator.

Out of scope for v0.1:
- Generics
- Concurrency
- Exceptions / recoverable errors
- Advanced optimization passes
- Moving/compacting GC
- Closures/captured-variable lambdas

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

Core reference types and standard-library reference classes used in v0.1:
- `Obj` (universal reference supertype)
- `Str`
- `T[]` (fixed-size array type constructor)
- `Vec` (dynamic vector of `Obj`, provided by `std.vec`)
- `Map` (hash map `Obj -> Obj`, provided by `std.map`; key lookup/update use `Hashable.hash_code()` and `Equalable.equals(Obj)`)
- User-defined class instance types

User-defined reference types also include interface types. Class types participate in nominal single inheritance, and classes may implement zero or more interfaces.

Defaults:
- All reference-typed variables default to `null` unless initialized.

### 3.3 Initialization and Safety

- Uninitialized values must not be observable.
- Language/runtime guarantees deterministic default initialization.

### 3.4 Cast Rules

- Primitive-to-primitive casts are always explicit.
- Any reference type can upcast to `Obj`.
- Subclass-to-base upcasts and class-to-implemented-interface upcasts are allowed.
- Checked casts between reference types are explicit and runtime-checked.
- Runtime class checks are subtype-aware for single inheritance, and interface checks use the effective implemented interface set, including inherited interfaces.
- `is` uses the same runtime relation as checked reference casts.
- `same_type` remains exact-type only.
- Failed checked casts panic and abort.

Primitive cast matrix:

| Source | `bool` | `i64` | `u64` | `u8` | `double` | `unit` |
| --- | --- | --- | --- | --- | --- | --- |
| `bool` | yes | yes | yes | yes | yes | no |
| `i64` | yes | yes | yes | yes | yes | no |
| `u64` | yes | yes | yes | yes | yes | no |
| `u8` | yes | yes | yes | yes | yes | no |
| `double` | yes | yes | yes | yes | yes | no |
| `unit` | no | no | no | no | no | no |

Primitive cast semantics:

- `bool -> integer`: `false -> 0`, `true -> 1`.
- `bool -> double`: `false -> 0.0`, `true -> 1.0`.
- `integer -> bool`: zero is `false`; any non-zero value is `true`.
- `double -> bool`: `0.0` and `-0.0` are `false`; every other value is `true`.
- `integer -> integer`: truncate to the target bit width, then interpret the bits in the target signedness. These casts never panic.
- `integer -> double`: numeric conversion using the source integer signedness. Precision loss is allowed.
- `double -> integer`: truncate toward zero, then check the truncated value against the target range. Panic on NaN, infinity, or out-of-range values.
- Casts involving `unit` are always invalid.

### 3.5 Operator Typing Rules (Current)

- Arithmetic operators (`+`, `-`, `*`, `/`, `%`) require matching numeric operand types.
- Signed integer `/` and `%` follow Python semantics: division rounds toward negative infinity, and the remainder has the divisor's sign.
- Exponent operator (`**`) is integer-only in v0.1: left operand must be `i64`, `u64`, or `u8`; right operand must be `u64`; result type is the left operand type.
- Unary minus (`-x`) is allowed only for signed numeric types: `i64`, `double`.
- Bitwise binary operators (`&`, `|`, `^`) are allowed for integer types `i64`, `u64`, `u8` and require matching operand types.
- Unary bitwise not (`~x`) is allowed for integer types `i64`, `u64`, `u8`.
- Shift operators (`<<`, `>>`) are allowed when left operand is `i64`, `u64`, or `u8` and right operand is `u64`.
- Shift result type is the left operand type.
- Right shift semantics: arithmetic for `i64`, logical for `u64` and `u8`.
- Shift count is runtime-checked; counts `>= bit_width` panic and abort (`64` for `i64`/`u64`, `8` for `u8`).
- Signed/unsigned mixing in binary operations is not allowed without explicit casts.

---

## 4) Classes and Object Semantics

### 4.1 Classes

- Classes support fields and methods.
- Classes may declare one optional superclass with `extends`.
- Fields and methods can be declared `private` for class-only access.
- Fields can be declared `final`; final fields are write-once at construction and cannot be reassigned.
- Methods are instance methods by default.
- Ordinary instance methods are virtual by default.
- Static methods are declared explicitly with `static fn` and are called on the class name (`Counter.add(...)`).
- Subclasses may override inherited virtual instance methods with explicit `override`.
- Override compatibility is exact in v0.1: same name, parameter list, and return type.
- Private instance methods, static methods, and constructors are never virtual and cannot be overridden.
- `super(...)` is constructor-only in v0.1; `super.method(...)` and `super.field` are out of scope.
- Classes may implement zero or more interfaces, and subclasses inherit their base class's interfaces transitively.

Dispatch details:

- Ordinary instance calls dispatch through the runtime class of the receiver.
- Base methods calling other virtual methods through `__self` observe overrides.
- Static and private method calls remain direct.
- Interface dispatch uses the effective overridden implementation for the concrete runtime class.

Visibility details:

- `private` applies to class fields and class methods (instance or static).
- Private members are accessible only from methods declared inside the same class.
- Access from free functions, other classes, and importing modules is rejected by type checking.
- Leading underscore naming (for example `_value`) is convention-only and has no visibility semantics.

Constructor details (explicit + compatibility constructors in v0.1):

- Classes may declare zero or more explicit constructors, including `private` constructors.
- A class with no declared constructors gets a synthesized compatibility constructor.
- Compatibility constructor parameters cover required construction parameters in declaration order; for subclasses this includes inherited required construction parameters before subclass-required fields.
- Explicit subclass constructors must begin with `super(...)`; synthesized compatibility constructors chain automatically.
- Final-field note: final reference fields pin the reference value (the referenced object may still be mutated).

### 4.2 Allocation and Identity

- Class instances are heap-allocated.
- References compare by identity by default.

### 4.3 Null Semantics

- References are nullable.
- `null` dereference panics and aborts.
- v0.1 does not perform compile-time static null-dereference analysis; null-dereference checks are runtime-only.

### 4.4 Equality

- Primitive types: value equality.
- Reference types: identity equality by default.
- `Map` is a library-level exception: key lookup/update use `Hashable.hash_code()` and `Equalable.equals(Obj)` rather than reference identity, and missing protocol implementations surface as checked-cast panics.

---

## 5) Core and Standard Reference Types (v0.1)

### 5.1 Str

- `Str` is immutable.
- `Str` stores raw `u8` bytes only (no encoding semantics in v0.1).
- String literals produce `Str` instances and support C-style escapes (`\"`, `\\`, `\n`, `\r`, `\t`, `\0`, `\xHH`).
- `Str` is indexable via `[]` with `i64` index and returns `u8`.
- `std.str::StrBuf` is a mutable byte-buffer companion type with explicit methods (for example: `from_str`, `len`, `get_u8`, `set_u8`, `to_str`).

### 5.1.1 `std.math`

- `std.math` provides a grouped `double` math surface backed by runtime wrappers.
- Current implemented functions: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log10`, `pow`, `sqrt`, `cbrt`, `floor`, `ceil`, `round`, `trunc`, `abs`, `min`, `max`, `hypot`, `is_nan`, `is_infinite`.
- Semantics are intended to be Java-like where practical, but they follow the underlying runtime floating-point implementation rather than a bit-exact Java specification.

### 5.1.2 `std.io`

- `std.io` provides stdout printing helpers plus high-level whole-file and process-input helpers.
- Current implemented functions include `print`, `println`, scalar `println_*` helpers, `read_file(path: Str) -> Str`, `write_file(path: Str, content: Str) -> unit`, `read_stdin() -> Str`, and `read_program_args() -> Str[]`.
- `read_file` and `write_file` are intentionally high-level in v0.1; user code does not manage file handles directly.

### 5.1.3 `std.random`

- `std.random` provides a deterministic, seedable `Random` class implemented in stdlib.
- Current implemented methods: `next_u64`, `next_bool`, `next_double`, `next_bounded`, and `randint`.
- The current generator algorithm is SplitMix64. Sequence stability for a given seed is part of the public contract for the current stdlib surface.
- `next_bounded(bound)` panics for `bound == 0` and otherwise uses rejection sampling to avoid modulo bias.

### 5.2 Vec (`std.vec`)

- `Vec` is a standard-library class in `std.vec`, not a dedicated runtime-native container type.
- `Vec` stores `Obj` elements.
- Core operations implemented in the current tree: `len`, `push`, `clear`, `with_capacity`, `index_get`, `index_set`, `slice_get`, `slice_set`, `iter_len`, `iter_get`.
- Higher-order helpers implemented in the current tree: `map(func: fn(Obj) -> Obj)`, `filter(pred: fn(Obj) -> bool)`, `reduce(func: fn(Obj, Obj) -> Obj, initial: Obj)`.
- `len() -> u64`.
- `with_capacity(capacity: u64) -> Vec`.
- Index and slice parameters are signed: `index_get(index: i64)`, `index_set(index: i64, value: Obj)`, `slice_get(begin: i64, end: i64)`, `slice_set(begin: i64, end: i64, value: Vec)`.
- Negative indices and slice bounds are normalized relative to the current length before bounds checks.

### 5.3 Map (`std.map`)

- `Map` is a standard-library class in `std.map`, not a dedicated runtime-native container type.
- `Map` maps `Obj` keys to `Obj` values.
- Key semantics use `Hashable.hash_code()` and `Equalable.equals(Obj)`, not reference identity.
- Keys that do not implement the required interfaces fail through the same checked-cast panic path used by ordinary reference casts.
- Core operations implemented in the current tree: `len`, `contains`, `put`, `index_get`, `index_set`, `with_capacity`.
- `m[key]` and `m[key] = value` are indexing sugar over `index_get` and `index_set`.
- `index_get` panics when the key is absent.
- `put` and `index_set` overwrite the existing entry when an equal key is already present.

### 5.4 std.box Wrapper Types

- Primitive wrappers are provided by `std.box` as ordinary classes (`BoxI64`, `BoxU64`, `BoxU8`, `BoxBool`, `BoxDouble`).
- Primary purpose: allow primitives in `Obj`-based containers.
- Wrapper instances are immutable by convention (private field + getter method).

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
  - `arr.index_get(index) -> T`, alias `arr[index]`
  - `arr.index_set(index, value) -> unit`, alias `arr[index] = value`
  - `arr.slice_get(start, end) -> T[]`, alias `arr[start:end]`
  - `arr.slice_set(start, end, value: T[]) -> unit`, alias `arr[start:end] = value`
- Bounds violations panic and abort.
- `slice` semantics in v0.1: copying slice (new array allocation).
- Array assignability policy in v0.1: invariant (`A[]` is assignable only to `A[]`, except `null` to reference arrays).
- Nested arrays are supported: `T[][]` and deeper are treated as jagged arrays (array-of-arrays), not fixed-shape matrices.
- Although syntax is generic-like, `T[]` is a built-in type constructor, not user-defined generics.

Implementation status note (current tree):
- Array features above are implemented and validated via parser/typecheck/codegen/runtime tests and golden tests.
- Ownership is currently compiler+runtime-first for arrays:
  - Compiler handles array syntax/desugaring and element-category runtime call routing.
  - Runtime provides storage/layout + `len/get/set/slice` primitives + bounds/GC behavior.
  - A stdlib-first array wrapper layer is a planned follow-up, not the current implementation state.
- Current backend optimization note:
  - Structural `ref[]` indexed writes may be emitted as direct stores rather than `rt_array_set_ref`, but only through one centralized compiler helper.
  - This is valid under the current non-moving collector.
  - If collector upgrades later require mutation-side barriers or remembered-set maintenance, that centralized helper must be revised instead of permitting scattered raw `ref[]` stores.

### 5.7 Sugaring Protocols (Direction)

To support stdlib-first container implementations and avoid hard-coded container-name behavior, sugar eligibility is structural and split into distinct protocols.

Indexing/slicing protocol:

- `x[i]` is equivalent to `x.index_get(i)`
- `x[i] = v` is equivalent to `x.index_set(i, v)`
- `x[a:b]` is equivalent to `x.slice_get(a, b)`
- `x[a:b] = v` is equivalent to `x.slice_set(a, b, v)`
- Structural method shape: `index_get(K) -> R`, `index_set(K, W) -> unit`, `slice_get(i64, i64) -> U`, `slice_set(i64, i64, U) -> unit`
- `K` is method-signature driven (not hard-coded to `i64`)

For-in iteration protocol (planned lowering target):

- surface syntax: `for elem in collection { ... }`
- structural method shape: `iter_len() -> u64` and `iter_get(i64) -> T`
- lowering intent: evaluate collection once, snapshot `iter_len()`, iterate with `i64` index, infer `T` from `iter_get`

Design lock-in note:

- `index_get(K)` remains key/index-agnostic for indexing sugar.
- `for ... in` does not use `get`; it requires `iter_len/iter_get(i64)` specifically.
- Structural collection sugar follows ordinary instance-method dispatch semantics, so overriding `index_get`, `index_set`, `slice_get`, `slice_set`, `iter_len`, or `iter_get` affects the sugared forms as well.
- This prevents key-based maps (for example `index_get(u64)` for lookup) from becoming accidentally iterable via for-sugar.

---

## 6) Modules and Visibility

- Module system supports `import` and `export`.
- Frozen v0.1 module import syntax forms:
  - `import a.b;`
  - `import a.b as b;`
  - `import a.b as x.y;`
  - `import a.b as .;`
  - `export import a.b;` (re-export)
  - `export import a.b as b;`
  - `export import a.b as x.y;`
  - `export import a.b as .;`
- External function declaration forms:
  - `extern fn name(args...) -> type;`
  - `export extern fn name(args...) -> type;` (re-export)
- Symbols are private by default to defining module.
- `export` makes symbol visible to importing module.
- Re-export of imported symbols/modules is allowed.
- No namespace feature beyond module boundaries.

### 6.1 Bind Paths and Visibility

- `as PATH` always means “bind this module at `PATH` in the current namespace”.
- Adding `export` means “and make that same binding visible to downstream importers too”.
- `import foo.bar;` binds `foo.bar` locally at `foo.bar`.
- `import foo.bar as baz.qux;` binds `foo.bar` locally at `baz.qux`.
- `import foo.bar as .;` binds the exported surface of `foo.bar` at the current module root.
- `export import foo.bar;` exports that same `foo.bar` binding.
- `export import pop.corn as baz;` exports that same `baz` binding.
- `export import hej as .;` binds and exports `hej` at the current module root.
- `as .` merges both direct exported symbols and exported submodule paths from the imported module into the current module root.
- Canonical ownership of flattened classes, functions, and interfaces remains with the defining module for nominal identity and later compilation phases.

### 6.2 Imported Class Name Resolution (Design Decision)

- Resolution is symmetric between constructor calls and type annotations.
- Unqualified class names are local-first:
  - If a local class `Counter` exists, `Counter(...)` and `Counter` (type annotation) resolve to the local class.
  - Imported classes with the same unqualified name do not override locals.
- Qualified names are explicit and select imported modules:
  - Constructor call: `util.Counter(...)`
  - Type annotation: `util.Counter`
- If no local class exists, unqualified imported class names may resolve from imports only when unique.
- If multiple imported modules export the same unqualified class name and no local class shadows it, unqualified usage is a compile-time ambiguity error.

### 6.3 Unsafe Systems Layer (Proposed Extension)

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

### 6.3 Function Values (Current Surface: No Capture)

This subsection describes the first-class function-value surface implemented in the current tree.

#### 6.3.1 Scope

- Function values are supported without closures.
- Function values may reference top-level functions and static class methods.
- Function-typed locals, parameters, return values, and class fields are supported.
- Captured-variable lambdas and nested-function captures are out of scope.

#### 6.3.2 Type Syntax

- Function type syntax: `fn(T1, T2, ...) -> R`
- Function type syntax is valid anywhere a type annotation is valid:
  - variable declarations
  - function/method parameters
  - function/method return types
  - class fields

Examples:

- `var pred: fn(Obj) -> bool = is_empty;`
- `fn apply(f: fn(i64, i64) -> i64, x: i64, y: i64) -> i64 { ... }`

#### 6.3.3 Value Formation Rules

- Legal function values:
  - top-level function symbols, including module-qualified imports (for example `add`, `util.add`)
  - qualified static method symbols (for example `Math.add`, `util.Math.add`)
- Not part of the current surface:
  - instance method values (bound or unbound)
  - interface method values
  - inline lambda literals
  - nested local function values

#### 6.3.4 Call Semantics

- Function-typed expressions are callable: `f(a, b, ...)`.
- Function-typed fields are callable directly: `obj.fn_field(a, b, ...)`.
- Function values may be returned from functions and assigned back into variables or fields.
- Calls through function values use normal argument/return type checking.
- Codegen lowers function-valued callees to indirect calls.
- Existing SysV ABI integer/floating calling convention rules remain unchanged.

#### 6.3.5 Type Compatibility

- Function types are invariant and arity-exact in this MVP extension.
- Assignment requires exact parameter and return type matches.
- No implicit adaptation, currying, or variance.

#### 6.3.6 Interactions and Non-Goals

- Explicit casts involving function types are out of scope for this MVP extension.
- Array function types are not currently supported by the parser (`fn(...) -> T[]` is valid, but `fn(...)[]` is rejected).
- Arrays/containers of function values are deferred until post-MVP unless required by implementation constraints.
- Interface-style callable objects are out of scope for this extension.

---

## 7) Runtime Model and Memory Management

### 7.1 Runtime Scope

Minimal C runtime provides:
- Allocation APIs
- GC APIs
- Panic/abort
- Basic file/stdio byte-array wrappers plus allocation facilities

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
- [x] Wire full shadow-stack ABI frame publication and slot maintenance (compiler emits inline root-frame setup/pop and direct root-slot stores; `rt_dbg_*` helpers remain available for debug/test C code).
- [x] Restrict safepoint root-slot spills to exact reference-typed locals/temporaries.
- [x] Add end-to-end compile+run tests.
- [x] Add method callee lowering for call expressions.
- [x] Add constructor callee lowering for call expressions.

## F. Core / Standard Types

- [x] Implement `Str` (immutable).
- [x] Implement `Vec` (`Obj` elements).
- [x] Implement `Map` (`Obj -> Obj`, `Hashable`/`Equalable` key semantics).
- [x] Provide primitive wrapper classes in `std.box`.
- [ ] Add API and behavioral tests for nested containers.

## G. Tooling and Diagnostics

- [ ] Implement stable diagnostic format with spans.
- [x] Implement minimal CLI flow (`build`, optional `run`).
- [x] Add sample programs for sanity checks.

## H. Early Post-MVP Extension Hook

- [ ] Add container specialization extension point.
- [ ] Prototype one specialized container (`VecI64` or `MapStrObj`) without changing language core.
- [x] Extend call lowering to support >6 positional args (stack-passed args under SysV).
- [x] Add indirect callee lowering for call expressions.
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
