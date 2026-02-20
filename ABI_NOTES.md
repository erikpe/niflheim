# ABI Notes (v0.1)

This document defines the compiler/runtime binary interface for Niflheim MVP v0.1.
It is intentionally minimal and optimized for implementation clarity, not performance.

## 1) Scope

- Target ABI: SysV x86-64 (Linux).
- Runtime language: C.
- Compiler stage-0: Python codegen to Intel-syntax x86-64 assembly.
- Runtime model: single-threaded, stop-the-world non-moving mark-sweep GC.

These notes are the source of truth for compiler <-> runtime interop.

---

## 2) Primitive and Reference Representation

### 2.1 Primitive values

- `i64`, `u64`: 64-bit integers in standard SysV integer registers/stack slots.
- `u8`, `bool`: carried in 8-bit logical domain but placed in 64-bit ABI slots (zero-extended unless operation-specific).
- `double`: IEEE-754 64-bit, passed/returned in SysV floating-point registers.
- `unit`: no payload; conventionally ignored in codegen and represented as zero if a slot is required.

### 2.2 References

- All language references are opaque object pointers at runtime.
- `null` is represented as zero pointer.
- Raw pointers are never exposed at source-language level.

---

## 3) Heap Object Layout

All GC-managed heap objects begin with a common header.

```c
#include <stdint.h>
#include <stddef.h>

typedef struct RtType RtType;

typedef struct RtObjHeader {
    const RtType* type;    // Type metadata pointer (trace info, debug name)
    uint64_t size_bytes;   // Total object size including header
    uint32_t gc_flags;     // Bit flags (mark/pin), remaining bits reserved
    uint32_t reserved0;    // Reserved for future use
} RtObjHeader;
```

Object pointer conventions:
- A language reference points to the object base (header address).
- Payload starts immediately after `RtObjHeader`.
- Objects are aligned to 8 bytes minimum.

Header size for v0.1 with the layout above is 24 bytes; runtime may pad object allocation to 8-byte boundary.

---

## 4) Type Metadata and Tracing

Type metadata drives GC tracing and optional diagnostics.

```c
typedef void (*RtTraceFn)(void* obj, void (*mark_ref)(void** slot));

typedef struct RtType {
    uint32_t type_id;
    uint32_t flags;          // Type flags (`HAS_REFS`, `VARIABLE_SIZE`, `LEAF`)
    uint32_t abi_version;    // Runtime ABI schema version for metadata
    uint32_t align_bytes;    // Required object alignment in bytes
    uint64_t fixed_size_bytes; // Full object size for fixed-size objects (0 if variable)
    const char* debug_name;  // Optional, may be NULL in release mode
    RtTraceFn trace_fn;      // Required for reference-containing objects
    const uint32_t* pointer_offsets; // Optional pointer-slot offsets from object base
    uint32_t pointer_offsets_count;  // Number of entries in pointer_offsets
    uint32_t reserved0;
} RtType;
```

Tracing contract:
- `obj` is the object base pointer (header address).
- `trace_fn` marks every pointer field owned by the object.
- `mark_ref` expects address of a pointer slot (`void**`) so GC can read/update consistently.
- For objects with no pointer fields, `trace_fn` may be a no-op.
- `pointer_offsets` may be used for simple descriptor-based tracing; if both descriptor and `trace_fn` are present, runtime may prefer `trace_fn`.

---

## 5) Shadow Stack Root ABI

v0.1 uses exact roots with a compiler-managed shadow stack.

```c
typedef struct RtRootFrame {
    struct RtRootFrame* prev;
    uint32_t slot_count;
    uint32_t reserved;
    void** slots;            // Array of pointer slots (each slot stores object ptr or NULL)
} RtRootFrame;
```

Runtime thread state:

```c
typedef struct RtThreadState {
    RtRootFrame* roots_top;
} RtThreadState;
```

Required runtime entry points:

```c
void rt_gc_register_global_root(void** slot);
void rt_gc_unregister_global_root(void** slot);

void rt_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count);
void rt_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref);
void* rt_root_slot_load(const RtRootFrame* frame, uint32_t slot_index);

void rt_push_roots(RtThreadState* ts, RtRootFrame* frame);
void rt_pop_roots(RtThreadState* ts);
```

Root frame ABI contract:
- Compiler registers/unregisters reference-typed globals with `rt_gc_register_global_root` / `rt_gc_unregister_global_root`.
- Compiler allocates one `RtRootFrame` per function activation that owns reference slots.
- Compiler allocates `void*` root slots in the same activation frame and calls `rt_root_frame_init` before pushing.
- `rt_root_slot_store` updates slots at safepoints and before runtime calls; out-of-bounds indices are runtime errors.
- `rt_push_roots` links the frame into thread-local root stack in prologue.
- `rt_pop_roots` must run on every function exit path and enforces underflow safety.

Compiler rules:
- Register each global reference slot exactly once during runtime/module initialization.
- Each function that can hold reference locals/temporaries allocates root slots in its stack frame.
- Function prologue initializes `RtRootFrame` and pushes it.
- Function epilogue pops it on all exits.
- Every live reference at a safepoint must be present in a root slot.

Safepoints in v0.1:
- Every runtime call is a safepoint (frozen policy for v0.1).
- Before each runtime call, all live reference values must be present in root slots.
- GC is therefore permitted to run at any runtime call boundary.
- Ordinary language function calls are not GC entry points by themselves.
- However, because a callee may execute runtime calls, v0.1 codegen must spill caller live references to root slots before ordinary calls too (unless the callee is proven non-GC).

---

## 6) Runtime API Surface (Minimum)

```c
// Process/runtime lifecycle
void rt_init(void);
void rt_shutdown(void);
RtThreadState* rt_thread_state(void);

// Allocation
void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes);

// GC
void rt_gc_collect(RtThreadState* ts);
void* rt_checked_cast(void* obj, const RtType* expected_type);

// Panic / abort
__attribute__((noreturn)) void rt_panic(const char* message);
__attribute__((noreturn)) void rt_panic_null_deref(void);
__attribute__((noreturn)) void rt_panic_bad_cast(const char* from_type, const char* to_type);
__attribute__((noreturn)) void rt_panic_oom(void);

// Optional minimal IO wrappers
int64_t rt_read(int64_t fd, void* buf, uint64_t count);
int64_t rt_write(int64_t fd, const void* buf, uint64_t count);
```

Allocation semantics:
- `payload_bytes` excludes header size.
- Runtime allocates `sizeof(RtObjHeader) + payload_bytes`.
- Runtime validates that type metadata pointer is non-null.
- Memory for object payload is zero-initialized in v0.1 to guarantee deterministic defaults.
- If threshold exceeded, runtime may trigger GC before/after allocation.
- On failed allocation after retrying post-GC, runtime panics with OOM.

---

## 7) GC Trigger Policy

Minimal policy:
- Keep counters: `allocated_bytes`, `next_gc_threshold`.
- Trigger collection when `allocated_bytes >= next_gc_threshold`.
- After sweep, compute `live_bytes`; set `next_gc_threshold = max(min_threshold, live_bytes * growth_factor)`.
- Suggested `growth_factor`: 1.5 to 2.0.

Current implementation status:
- Mark phase traces from both registered global roots and shadow-stack roots.
- Sweep/threshold policy remains TODO in runtime implementation.

This policy is intentionally simple and predictable.

---

## 8) Calling Convention Notes for Codegen

SysV x86-64 basics for generated assembly:
- Integer/pointer args: RDI, RSI, RDX, RCX, R8, R9.
- Floating-point args: XMM0-XMM7.
- Integer/pointer return: RAX.
- Floating-point return: XMM0.
- Callee-saved: RBX, RBP, R12-R15.
- Stack aligned to 16 bytes at call boundaries.

Compiler requirements:
- Preserve callee-saved registers when used.
- Maintain 16-byte stack alignment before `call`.
- Spill live reference temps into root slots before allocation/runtime calls.

---

## 9) Cast and Type-Check Runtime Hooks

Because all references can cast to/from `Obj`, runtime type checks are required for downcasts.

Suggested helper:

```c
void* rt_checked_cast(void* obj, const RtType* expected_type);
```

Behavior:
- If `obj == NULL`, return NULL (nullable cast semantics).
- If object runtime type matches `expected_type`, return object.
- Otherwise panic with bad-cast error.

Type identity in v0.1:
- Exact type match only.
- No subtype checks (no inheritance/interfaces in v0.1).

---

## 10) Built-in Type Layout Notes

### 10.1 Str

- Immutable object with payload fields such as length and byte buffer reference/inline storage.
- Equality at language level remains reference identity in v0.1 unless library helper used.

### 10.2 Vec (Obj elements)

Suggested payload fields:
- `uint64_t len`
- `uint64_t cap`
- `void** data` (pointer to object references, managed as GC-visible memory)

Tracing requirement:
- Trace each element in range `[0, len)` as a reference slot.

### 10.3 Map (Obj -> Obj)

- Identity hash and identity equality only.
- Buckets/entries must be fully traced by GC.
- If separate entry objects are used, all entry links and key/value references must be traced.

### 10.4 Box types

- Box payload stores primitive value only.
- No internal reference fields, so trace can be no-op.

---

## 11) Invariants and Debug Checks

Runtime debug-mode assertions recommended:
- Every object has valid header and known `type_id`.
- `size_bytes` is sane and aligned.
- Root frame push/pop forms a valid stack discipline.
- No invalid pointer outside heap passed to marker.

Compiler debug-mode checks recommended:
- All function exits pop roots exactly once.
- All safepoints have complete live reference rooting.

---

## 12) Versioning and Change Control

- This ABI is frozen for MVP v0.1.
- Any change to header layout, root frame layout, or runtime symbol signatures requires:
  1) Version bump note in this file,
  2) Compiler and runtime update in same change,
  3) ABI compatibility statement.

---

## 13) Minimal Bring-up Sequence

1. Implement runtime structs and `rt_init`, `rt_alloc_obj`, `rt_panic`.
2. Handwrite tiny assembly/C harness that allocates one object and exits.
3. Add root frame push/pop and verify root traversal works.
4. Add mark-sweep and threshold trigger.
5. Integrate compiler-generated prologue/epilogue root management.
6. Validate with allocation churn and nested object graphs.
