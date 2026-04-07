# Inline Interface Dispatch Plan

This document defines a concrete plan for replacing helper-based interface method lookup with inline codegen that loads interface method tables directly from `RtType`.

## Purpose

The current interface call path is semantically correct but slower than class virtual dispatch for a structural reason: it calls a runtime helper that searches the receiver type's interface metadata before loading the final method pointer.

Today the hot path is:

1. evaluate receiver and arguments
2. call `rt_lookup_interface_method(obj, interface_descriptor, method_slot)`
3. inside the runtime helper, scan `RtType.interfaces[]` linearly to find the matching interface
4. load the selected method table entry
5. perform the indirect call

Class virtual dispatch is already cheaper because codegen emits the lookup inline from `header->type->class_vtable[slot]`.

The goal of this change is to make interface dispatch structurally similar to class virtual dispatch while keeping the current language model intact:

- interface values remain plain object references, not fat pointers or witness pairs
- interface method slots remain ordered within each interface declaration
- codegen emits interface dispatch inline without first calling a runtime lookup helper
- runtime metadata moves from search-based interface lookup to direct per-interface slots on `RtType`

## Current State

Current implementation points:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - emits interface calls by loading the interface descriptor symbol and calling `rt_lookup_interface_method`
- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - `RtType` stores `interfaces` and `interface_count`
  - `RtInterfaceImpl` stores `{ interface_type, method_table, method_count }`
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - `rt_find_interface_impl(...)` linearly scans `RtType.interfaces[]`
  - `rt_lookup_interface_method(...)` uses the scan result to find the method pointer
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - emits per-class interface implementation records and per-interface method tables
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - emits `RtInterfaceImpl[]` and `RtType.interfaces`
- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - currently assigns only method slots within an interface, not a whole-program slot for each interface

## Recommended Design

## 1. Assign A Stable Whole-Program Slot To Each Interface

Each interface should receive a stable integer slot during whole-program codegen preparation.

Recommended ownership:

- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)

Recommended result:

- `DeclarationTables.interface_slot(interface_id) -> int`

Rationale:

- interface calls need a constant slot index to inline the first lookup step
- the compiler already has whole-program visibility when building declaration tables
- this keeps the ABI simple without changing frontend or semantic IR call shapes

## 2. Extend `RtInterfaceType` With Its Global Slot Index

Recommended runtime descriptor shape in [runtime/include/runtime.h](../runtime/include/runtime.h):

```c
struct RtInterfaceType {
    const char* debug_name;
    uint32_t slot_index;
    uint32_t method_count;
    uint32_t reserved0;
};
```

Rationale:

- runtime cast/test helpers can use the same global slot numbering as codegen
- interface membership checks no longer need a linear descriptor search
- descriptor identity is preserved for diagnostics and metadata tests

## 3. Replace Search-Based Interface Metadata On `RtType` With Direct Slot Tables

Recommended `RtType` change in [runtime/include/runtime.h](../runtime/include/runtime.h):

```c
const void* const* interface_tables;
uint32_t interface_slot_count;
uint32_t reserved1;
```

or the moral equivalent, inserted where `interfaces/interface_count` currently live.

Each `interface_tables[i]` entry is either:

- `NULL` if the class does not implement the interface for slot `i`
- a pointer to that class's per-interface method table if it does

The existing per-interface method tables can stay as arrays of method labels ordered by the interface declaration's method order.

Rationale:

- class virtual dispatch uses one indexed load from `RtType`
- interface dispatch should gain the same property for the interface-selection step
- storing `NULL` for non-implemented interfaces is simpler than preserving a compact search array on the hot path

## 4. Keep Interface Method Tables Separate Per Interface

Do not flatten all interface methods into one global vtable in this plan.

Per-interface method tables should remain:

- one table per `(class, interface)` pair
- indexed by the existing per-interface method slot

Rationale:

- minimizes metadata redesign relative to the current implementation
- preserves current interface method ordering rules and tests
- gets most of the performance win by removing the search helper from the hot path

## 5. Inline Interface Dispatch In Codegen

Recommended call lowering in [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py):

1. evaluate and root the receiver just as today
2. null-check the receiver
3. load `receiver->type`
4. load `type->interface_tables[interface_slot]`
5. check for null table pointer and preserve the current bad-cast failure behavior
6. load `method_table[method_slot]`
7. perform the existing indirect call sequence

This should mirror the class virtual-dispatch structure as closely as practical.

Rationale:

- removes one helper call from the hot path
- removes the linear scan over implemented interfaces
- keeps the existing indirect-call ABI and temporary-root behavior unchanged

## 6. Move Runtime Interface Checks To Slot-Based Access Too

Recommended runtime follow-through in [runtime/src/runtime.c](../runtime/src/runtime.c):

- rewrite `rt_checked_cast_interface(...)` to use `expected_interface->slot_index`
- rewrite `rt_is_instance_of_interface(...)` to use the slot directly
- remove `rt_find_interface_impl(...)` if nothing else needs it
- remove `rt_lookup_interface_method(...)` once codegen and tests no longer depend on it

Rationale:

- avoids keeping two independent interface membership mechanisms alive
- keeps cast/type-test behavior aligned with call dispatch behavior
- reduces the chance of metadata drift between the compiler and runtime

## 7. Keep Semantic IR And Frontend Rules Unchanged

This plan does not require a frontend or semantic-model redesign.

Expected unchanged layers:

- frontend parsing and AST
- typecheck interface conformance rules
- semantic IR call targets for interface dispatch

Required compiler-side changes are metadata and codegen focused.

Rationale:

- the current semantic model already distinguishes interface calls explicitly
- the performance issue is in runtime metadata shape and emitted lookup strategy, not in resolution semantics

## What Should Change, And Where

## Compiler Metadata And Tables

- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
  - assign a stable whole-program slot to each interface
  - expose `interface_slot(interface_id)` on `DeclarationTables`
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - record interface slot indices in `InterfaceMetadataRecord`
  - change class metadata from compact `interface_impls` search records to a direct slot-array representation
  - keep per-interface method table symbol data for implemented interfaces
- [compiler/codegen/symbols.py](../compiler/codegen/symbols.py)
  - add or rename symbols for per-class interface slot arrays if needed

## Assembly Emission

- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - emit interface descriptors with slot index
  - emit per-class `interface_tables` arrays sized to the global interface slot count
  - emit `NULL` table entries for non-implemented slots
  - wire the new array into `RtType`
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
  - add ABI constants and operand helpers for `RtType.interface_tables`
  - add helper(s) for indexed interface-table loads if useful
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - remove helper-call-based interface method lookup from the hot path
  - inline interface table and method slot loads
  - preserve current panic behavior for null receivers and invalid interface access

## Runtime ABI And Helpers

- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - revise `RtInterfaceType`
  - revise `RtType`
  - delete or deprecate `RtInterfaceImpl`
  - remove `rt_lookup_interface_method(...)` from the public ABI once no longer needed
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - update interface cast/type-test helpers to use slot-based access
  - delete linear scan helpers if fully retired

## Tests

- [tests/compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
  - update interface dispatch assertions from `call rt_lookup_interface_method` to inline table loads
- [tests/compiler/codegen/test_emit_asm_calls.py](../tests/compiler/codegen/test_emit_asm_calls.py)
  - update interface call lowering expectations
- [tests/compiler/codegen/test_program_generator.py](../tests/compiler/codegen/test_program_generator.py)
  - assert stable whole-program interface slot assignment and new metadata shape
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
  - assert emitted `RtInterfaceType` and `RtType` layout changes
- [tests/runtime/test_interface_metadata.c](../tests/runtime/test_interface_metadata.c)
  - update runtime metadata layout tests to the slotted representation
- [tests/runtime/test_interface_dispatch.c](../tests/runtime/test_interface_dispatch.c)
  - replace helper-search-oriented assertions with direct slot-table expectations
- [tests/runtime/test_interface_dispatch_negative.c](../tests/runtime/test_interface_dispatch_negative.c)
  - update failure-mode coverage for missing table entries or invalid slots
- [tests/runtime/test_interface_casts.c](../tests/runtime/test_interface_casts.c)
  - ensure cast success still works with slot-based metadata
- [tests/runtime/test_interface_casts_negative.c](../tests/runtime/test_interface_casts_negative.c)
  - ensure invalid casts still fail correctly
- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)
  - validate end-to-end interface dispatch behavior
- [tests/compiler/integration/test_cli_semantic_codegen_runtime/test_virtual_dispatch_interface_override_alignment.py](../tests/compiler/integration/test_cli_semantic_codegen_runtime/test_virtual_dispatch_interface_override_alignment.py)
  - ensure interface dispatch still agrees with override-selected implementations

## Ordered Implementation Checklist

## Slice 1: Lock The New ABI And Metadata Shape

- [ ] decide the final `RtInterfaceType` and `RtType` field layout for slot-based interface tables
- [ ] decide whether `RtInterfaceImpl` is removed immediately or retained temporarily during migration
- [ ] define naming and symbol strategy for per-class interface table arrays

Change:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
- [compiler/codegen/symbols.py](../compiler/codegen/symbols.py)

Test:

- [tests/runtime/test_interface_metadata.c](../tests/runtime/test_interface_metadata.c)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)

## Slice 2: Assign Stable Whole-Program Interface Slots

- [ ] assign a stable integer slot to every interface in declaration-table construction
- [ ] expose the slot through declaration tables and metadata builders
- [ ] record the slot in interface descriptor metadata

Change:

- [compiler/codegen/program_generator.py](../compiler/codegen/program_generator.py)
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
- [tests/compiler/codegen/test_program_generator.py](../tests/compiler/codegen/test_program_generator.py)

Test:

- assert per-interface slot indices are stable and inherited interface method tables still map to the selected implementation

## Slice 3: Emit Slotted Per-Class Interface Table Arrays

- [ ] emit one `interface_tables` array per class, indexed by global interface slot
- [ ] keep existing method-table emission for implemented interfaces
- [ ] emit null entries for non-implemented interface slots
- [ ] wire the new array into emitted `RtType` records

Change:

- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)

Test:

- assert emitted `.data` contains the descriptor slot index and the class interface table array with correct table pointers and null holes

## Slice 4: Inline Interface Dispatch In Expression Codegen

- [ ] replace `rt_lookup_interface_method` call emission with inline slot-table loads
- [ ] preserve null receiver behavior
- [ ] preserve invalid interface access failure behavior
- [ ] keep the existing indirect call ABI/rooting path unchanged after method pointer resolution

Change:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
- [tests/compiler/codegen/test_emit_asm_calls.py](../tests/compiler/codegen/test_emit_asm_calls.py)

Test:

- assert interface calls no longer emit `call rt_lookup_interface_method`
- assert emitted assembly performs direct slot-array and method-table loads before `call r11`

## Slice 5: Move Runtime Cast/Test Helpers To The Same Slot Model

- [ ] rewrite interface cast/type-test helpers to use descriptor slot indices
- [ ] remove the linear search helper if it becomes unused
- [ ] remove the public runtime lookup helper if codegen no longer uses it

Change:

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [tests/runtime/test_interface_casts.c](../tests/runtime/test_interface_casts.c)
- [tests/runtime/test_interface_casts_negative.c](../tests/runtime/test_interface_casts_negative.c)
- [tests/runtime/test_interface_dispatch.c](../tests/runtime/test_interface_dispatch.c)
- [tests/runtime/test_interface_dispatch_negative.c](../tests/runtime/test_interface_dispatch_negative.c)

Test:

- runtime harnesses for successful and failing interface casts and dispatch

## Slice 6: Revalidate Override And Interface Alignment End To End

- [ ] confirm interface dispatch still resolves overridden implementations selected by the class hierarchy
- [ ] confirm inherited implementations still populate the right interface method tables
- [ ] confirm interface dispatch works with stack arguments and mixed call shapes

Change:

- targeted integration and golden tests only if expectations need updating

Test:

- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)
- [tests/compiler/integration/test_cli_semantic_codegen_runtime/test_virtual_dispatch_interface_override_alignment.py](../tests/compiler/integration/test_cli_semantic_codegen_runtime/test_virtual_dispatch_interface_override_alignment.py)
- focused interface-related golden coverage if an end-to-end fixture is added or updated

## Slice 7: Cleanup And Documentation

- [ ] remove dead helper-oriented comments, tests, and symbol names
- [ ] update documentation to describe slot-based interface dispatch rather than runtime search-based lookup
- [ ] update test docs if runtime harness purpose changes

Change:

- [docs/INTERFACES_V1.md](../docs/INTERFACES_V1.md)
- [docs/ABI_NOTES.md](../docs/ABI_NOTES.md)
- [tests/README.md](../tests/README.md)
- [README.md](../README.md)

Test:

- full pytest suite
- runtime interface harnesses via `make -C runtime test-interface-metadata test-interface-casts test-interface-casts-negative test-interface-dispatch test-interface-dispatch-negative`

## Tradeoffs And Risks

## Metadata Size vs Faster Dispatch

Recommended choice:

- accept a denser `RtType` interface table array with null holes

Tradeoff:

- more metadata space per class when many interfaces exist globally
- significantly cheaper interface dispatch on the hot path

This is the right tradeoff for this plan because it eliminates the helper call and linear scan without changing source-language semantics.

## Keep Plain Interface Values vs Fat Interface Values

Recommended choice:

- keep interface values as plain object references in this plan

Tradeoff:

- interface calls still need to load runtime metadata from the receiver object
- avoids a much larger ABI and semantic redesign for interface-typed values

## Slotted Per-Interface Tables vs One Flat Global Interface VTable

Recommended choice:

- keep one method table per `(class, interface)` pair

Tradeoff:

- one extra indirection relative to a fully flattened global interface-method vtable
- much simpler migration from the current metadata layout

This plan intentionally optimizes the largest current cost first: the runtime helper plus linear search.

## Success Criteria

This plan is complete when:

- interface calls no longer emit `call rt_lookup_interface_method`
- interface membership checks and interface calls both use slot-based metadata
- interface override alignment remains correct
- all interface-related runtime harnesses pass under the new ABI
- the full pytest suite passes