# Codegen Pipeline Refactor Plan

This document describes a concrete refactoring plan for moving awkwardly placed implementation work out of the codegen phase and into earlier compiler stages.

Goal:

- make codegen consume a fully linked, fully resolved, backend-ready program
- remove semantic and type-resolution policy from assembly emission
- stop earlier pipeline stages from importing codegen utilities
- reduce duplicated type and metadata reconstruction inside codegen
- keep the backend focused on layout, ABI, runtime calling conventions, and assembly emission

This plan is ordered by payoff first and risk second:

- highest-payoff, lowest-risk boundary fixes come first
- larger structural moves that touch semantic program shape come later
- backend-mechanical responsibilities stay in codegen

## Status

Partially implemented.

Completed so far:

- Step 1 is implemented and validated.
- Step 2 is implemented and validated.

In progress now:

- none

Not started yet:

- Steps 3 through 8

## Scope

This plan covers refactoring around the current codegen package:

- `compiler/codegen/linker.py`
- `compiler/codegen/program_generator.py`
- `compiler/codegen/emitter_module.py`
- `compiler/codegen/emitter_fn.py`
- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/emitter_stmt.py`
- `compiler/codegen/layout.py`
- `compiler/codegen/strings.py`
- `compiler/codegen/types.py`

It also covers the upstream stages that should own the moved responsibilities:

- frontend literal helpers
- typecheck type-name helpers
- semantic lowering
- semantic program linking / metadata preparation

This plan does not try to redesign the runtime ABI, GC root model, or assembly backend.

## Current Problem

The current codegen phase still performs several tasks that should have happened earlier:

1. program-level symbol merging happens in codegen linking
2. runtime type-metadata reachability is rediscovered by walking semantic expressions during module emission
3. semantic lowering and typecheck import helpers from `compiler.codegen.strings`
4. constructor emission synthesizes semantic IR inside codegen to reuse normal function machinery
5. codegen reconstructs expression result types and field offsets from names instead of consuming fully resolved IR
6. array builtin-vs-method dispatch is still decided inside expression/statement emitters
7. generic type-string parsing helpers live in codegen even though they are not backend-specific

These issues create the following problems:

- backend failures are mixed with earlier semantic/linking failures
- semantic policy is duplicated or reconstructed during emission
- upstream phases depend on codegen utilities, which inverts the pipeline boundary
- codegen APIs have to inspect names and ad hoc node shapes instead of using prepared backend inputs
- future features will keep leaking into codegen unless the ownership boundary is tightened

## Target Design

At the end of this refactor, the phase ownership should be:

### Frontend / Shared Literal Utilities

- decode string and char literal spellings
- own `Str` naming helpers only if they are truly lexical / language-level helpers

### Typecheck / Shared Type Utilities

- classify type names such as array, function, reference, and `Str`
- expose type utilities from a phase-neutral module rather than `compiler.codegen.types`

### Semantic Lowering / Semantic Linking

- produce a fully linked semantic program with duplicate-symbol resolution already complete
- produce explicit metadata requirements for runtime type records and interface descriptors
- normalize builtin array operations and synthetic helper operations into dedicated semantic forms
- attach resolved field identity or offset metadata where needed
- expose constructor bodies in backend-ready form without codegen fabricating semantic nodes

### Codegen

- consume linked semantic IR and metadata tables
- compute stack layout and root-slot layout
- choose ABI locations and runtime call sequences
- emit type metadata sections from prepared inputs
- emit assembly only from already-decided semantic operations

## Prioritized Refactor Order

### Tier 1: Highest Payoff, Lowest Risk

1. remove upstream imports from `compiler.codegen.strings`
2. move non-backend type-name helpers out of `compiler.codegen.types`

### Tier 2: High Payoff, Moderate Risk

3. precompute runtime metadata requirements before module emission
4. stop reconstructing expression result types and field offsets inside emitters

### Tier 3: High Payoff, Higher Risk

5. move program-level symbol merging out of `compiler/codegen/linker.py`
6. normalize builtin array operations before codegen

### Tier 4: Cleanup / Structural Polish

7. remove semantic-IR synthesis from constructor emission
8. simplify codegen walkers and declaration tables after upstream metadata is explicit

## Step-By-Step Plan

## Step 1: Extract Literal And String Helpers Out Of Codegen

Payoff:

- high

Risk:

- low

Problem:

- `compiler/semantic/lowering.py` imports `decode_char_literal`, `decode_string_literal`, and `is_str_type_name` from `compiler.codegen.strings`
- `compiler/typecheck/expressions.py` imports `is_str_type_name` from `compiler.codegen.strings`
- `compiler/typecheck/type_resolution.py` imports `STR_CLASS_NAME` from `compiler.codegen.strings`

That makes earlier phases depend on codegen.

Target ownership:

- move literal decoders to a frontend/shared literal utility module
- move `Str` type-name helpers to a phase-neutral type helper module

Suggested code areas:

- new module such as `compiler/frontend/string_literals.py` or `compiler/common/literals.py`
- new module such as `compiler/common/type_names.py`
- `compiler/semantic/lowering.py`
- `compiler/typecheck/expressions.py`
- `compiler/typecheck/type_resolution.py`
- `compiler/codegen/strings.py`

Concrete tasks:

- create a phase-neutral home for:
  - `decode_string_literal(...)`
  - `decode_char_literal(...)`
- create a phase-neutral home for:
  - `STR_CLASS_NAME`
  - `is_str_type_name(...)`
- update semantic lowering and typecheck to import from the new modules
- leave `escape_asm_string_bytes(...)` and `escape_c_string(...)` in codegen, because those are emission-specific
- reduce `compiler/codegen/strings.py` to backend-only responsibilities

What should be true after this step:

- no earlier compiler stage imports from `compiler.codegen.*`
- literal decoding is clearly a frontend/shared concern
- string type-name checks are clearly a type-system/shared concern

Validation:

- focused typecheck and semantic lowering tests
- codegen string literal tests
- full pytest

Validation for this step:

- Implemented by adding phase-neutral helpers under:
  - `compiler/common/literals.py`
  - `compiler/common/type_names.py`
- Updated earlier pipeline stages to import these shared helpers instead of `compiler.codegen.strings`
- Reduced `compiler/codegen/strings.py` to backend-owned string-emission helpers
- Added focused unit tests under:
  - `tests/compiler/common/test_literals.py`
  - `tests/compiler/common/test_type_shapes.py`
- Validation run results:
  - focused cross-phase slice: `98 passed`
  - full pytest: `525 passed`

## Step 2: Move Generic Type-Name Helpers Out Of Codegen

Payoff:

- high

Risk:

- low

Problem:

- `compiler.codegen.types` currently owns helpers such as:
  - `is_function_type_name(...)`
  - `function_type_return_type_name(...)`
  - `is_array_type_name(...)`
  - `array_element_type_name(...)`
  - `is_reference_type_name(...)`

Only `double_value_bits(...)` and backend-specific error formatting are truly codegen-specific.

Target ownership:

- move string-based type-shape helpers into a phase-neutral type utility module

Suggested code areas:

- new module such as `compiler/common/type_shapes.py`
- `compiler/codegen/types.py`
- `compiler/typecheck/**`
- `compiler/semantic/**`
- `compiler/codegen/**`

Concrete tasks:

- move non-backend type-name parsing/classification helpers into a shared module
- update codegen imports to use the shared module where appropriate
- keep backend-only helpers in `compiler/codegen/types.py` or rename that file to make its scope explicit
- remove duplicate or overlapping type-name helper implementations elsewhere if discovered during migration

What should be true after this step:

- codegen no longer acts as the source of truth for generic type-shape parsing
- type-string helpers can be reused by semantic/typecheck without violating phase boundaries

Validation:

- existing codegen type tests
- typecheck and semantic tests that rely on function/array type parsing

Validation for this step:

- Implemented by adding phase-neutral type-shape helpers under:
  - `compiler/common/type_shapes.py`
- Updated `compiler/codegen/types.py` so shared type-shape parsing now delegates to the common module while backend-specific helpers remain in codegen
- Preserved codegen-specific error adaptation for backend callers while moving the source of truth out of codegen
- Added focused shared-helper tests and trimmed `tests/compiler/codegen/test_types.py` to backend-owned behavior
- Validation run results:
  - focused cross-phase slice: `98 passed`
  - full pytest: `525 passed`

## Step 3: Precompute Runtime Metadata Requirements Before Emission

Payoff:

- very high

Risk:

- moderate

Problem:

- `emit_type_metadata_section(...)` currently walks the whole program and re-discovers which type records are needed by scanning casts and type tests
- it also re-derives interface-vs-class classification from module-local string tables during emission

Target ownership:

- semantic linking or a dedicated metadata-preparation pass should produce explicit metadata requirements ahead of codegen emission

Suggested code areas:

- `compiler/codegen/emitter_module.py`
- `compiler/codegen/program_generator.py`
- possibly a new semantic-side pass such as `compiler/semantic/metadata.py`
- `compiler/codegen/linker.py`

Concrete tasks:

- define an explicit metadata model for codegen input, for example:
  - class type records to emit
  - interface descriptors to emit
  - extra runtime-visible type names required by casts / type tests
  - pointer-offset metadata per class
  - interface implementation tables per class
- compute that metadata once before emission
- change `emit_type_metadata_section(...)` to serialize the prepared metadata rather than walking semantic bodies itself
- delete `collect_reference_cast_types(...)` and its statement/expression walkers from module emission once replaced

What should be true after this step:

- module emission is a serialization step, not an analysis step
- codegen no longer needs to rediscover semantic reachability for runtime type metadata

Validation:

- focused tests for casts, `is`, interfaces, and runtime metadata emission
- golden tests covering interface casts and type tests
- full test suite

## Step 4: Stop Reconstructing Type And Field Information Inside Emitters

Payoff:

- high

Risk:

- moderate

Problem:

- `infer_expression_type_name(...)` exists in multiple forms in codegen and depends on ad hoc node inspection
- `_resolve_field_offset(...)` scans declaration tables by class name and field name instead of consuming resolved field identity or offset information

Target ownership:

- semantic IR should expose canonical result types consistently
- field read/write nodes should carry enough resolved information for direct codegen lookup

Suggested code areas:

- `compiler/semantic/ir.py`
- `compiler/semantic/lowering.py`
- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/layout.py`
- `compiler/codegen/program_generator.py`

Concrete tasks:

- standardize semantic expression result typing so all expressions expose one canonical result-type field
- remove codegen-local `infer_expression_type_name(...)` helpers once semantic IR is consistent
- extend field access lvalues/expressions to carry resolved field identity or offset lookup key directly
- change codegen to use that resolved information directly rather than searching by string name

What should be true after this step:

- codegen does not need to infer expression types from node kinds
- codegen field emission becomes direct and deterministic

Validation:

- focused semantic lowering and codegen expression tests
- field access and assignment golden/integration tests

## Step 5: Move Program-Level Symbol Merging Out Of Codegen Linking

Payoff:

- very high

Risk:

- high

Problem:

- `build_codegen_program(...)` currently merges module functions and classes, resolves duplicate symbol ownership, and prefers concrete bodies over declarations
- this is semantic/program linking policy, not backend packaging

Target ownership:

- resolver or semantic program-linking should hand codegen a fully linked, already-merged program

Suggested code areas:

- `compiler/codegen/linker.py`
- `compiler/resolver.py`
- `compiler/semantic/symbols.py`
- possibly a new semantic-link stage module

Concrete tasks:

- define a pre-codegen linked-program representation whose symbols are already unique and chosen
- move duplicate symbol conflict detection and declaration/body selection into that earlier stage
- simplify `CodegenProgram` construction into ordering and packaging only
- rename `compiler/codegen/linker.py` if needed once it no longer performs semantic linking work

What should be true after this step:

- codegen receives a fully linked semantic program
- duplicate symbol errors arise before backend entry
- `build_codegen_program(...)` no longer decides semantic ownership

Validation:

- focused multi-module resolver/linking tests
- existing import/export integration tests
- full suite including AoC and goldens

## Step 6: Normalize Builtin Array Operations Before Codegen

Payoff:

- high

Risk:

- high

Problem:

- codegen still branches on whether index/slice operations are builtin array operations or resolved methods by checking `get_method` / `set_method` for `None`
- emitters still synthesize runtime function names from type names

Target ownership:

- semantic lowering should convert these into explicit operations with no remaining backend decision point

Suggested code areas:

- `compiler/semantic/ir.py`
- `compiler/semantic/lowering.py`
- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/emitter_stmt.py`

Concrete tasks:

- add explicit semantic node variants for builtin array get/set/slice operations, or add an explicit dispatch-kind enum
- ensure lowering decides builtin vs method dispatch exactly once
- make codegen emit the chosen operation directly without `None`-sentinel branching
- centralize runtime function-name selection in lowering or metadata prep rather than ad hoc string construction in emitters

What should be true after this step:

- codegen only emits already-normalized operations
- array builtin selection is not spread across statement and expression emitters

Validation:

- focused indexing/slicing tests
- stdlib array and indexing goldens
- full test suite

## Step 7: Stop Fabricating Semantic Functions In Constructor Emission

Payoff:

- moderate

Risk:

- moderate to high

Problem:

- `emit_constructor(...)` currently builds a synthetic `SemanticFunction` and `SemanticBlock` solely to reuse layout and frame logic

Target ownership:

- either constructors should be lowered into backend-ready semantic functions earlier, or codegen should have a dedicated constructor emission path that does not fabricate semantic IR

Suggested code areas:

- `compiler/semantic/ir.py`
- `compiler/semantic/lowering.py`
- `compiler/codegen/emitter_fn.py`
- `compiler/codegen/layout.py`

Concrete tasks:

- choose one of two directions:
  - lower constructors into explicit backend-ready semantic functions before codegen
  - or introduce constructor-specific layout/emission support that does not create fake semantic nodes
- keep root-slot and prologue logic shared without pretending constructors were authored semantic functions
- remove synthetic local such as `__nif_ctor_obj` from backend-generated semantic IR if possible

What should be true after this step:

- codegen consumes backend-ready constructor data instead of inventing semantic IR

Validation:

- constructor codegen tests
- class field initializer tests
- full suite

## Step 8: Final Cleanup Of Codegen APIs

Payoff:

- moderate

Risk:

- low to moderate

Problem:

- after earlier steps land, several codegen helper APIs and declaration tables will still reflect the old blurred boundary

Concrete tasks:

- remove duplicate walkers and now-dead metadata collectors
- trim `DeclarationTables` to only backend-necessary lookup tables
- rename modules or helpers whose names still reflect semantic migration history rather than current ownership
- tighten codegen tests so they operate only on backend-facing representations

What should be true after this step:

- codegen package contents match backend responsibilities cleanly

Validation:

- full `tests/compiler/codegen`
- full pytest
- full project test script

## Recommended Execution Order

Implement in this order:

1. move literal/string helpers out of codegen
2. move generic type-name helpers out of codegen
3. precompute runtime metadata requirements before emission
4. standardize semantic result-type and field-resolution data for codegen
5. move program-level symbol merging out of codegen linking
6. normalize builtin array operations before codegen
7. remove constructor-time semantic IR fabrication
8. do final cleanup and naming simplification

This order gives a good payoff gradient:

- Steps 1 and 2 fix inverted dependencies immediately and with low risk
- Steps 3 and 4 remove the biggest emission-time semantic reconstruction
- Steps 5 and 6 address the deepest remaining phase leaks
- Steps 7 and 8 finish structural cleanup after the core ownership model is correct

## Suggested Validation Strategy

After each step:

- run the smallest focused test slice that covers the changed ownership boundary
- then run the full `tests/compiler/codegen` suite

Recommended focused areas by step:

- Step 1:
  - semantic lowering literal tests
  - typecheck string-operation tests
  - codegen string literal tests
- Step 2:
  - shared type helper tests
  - codegen type/helper tests
- Step 3:
  - interface cast and `is` tests
  - metadata emission tests
- Step 4:
  - field access/assignment tests
  - semantic lowering tests
- Step 5:
  - multi-module linking/import tests
- Step 6:
  - array indexing and slicing tests
- Step 7:
  - constructor and field-initializer tests
- Step 8:
  - full codegen suite

Before considering the refactor complete:

- run full pytest
- run golden tests
- run the full project test script

## Completion Criteria

This refactor is complete when all of the following are true:

- no earlier phase imports from `compiler.codegen.*`
- codegen does not perform symbol-merging policy
- codegen does not walk semantic bodies to discover runtime metadata requirements
- codegen does not infer expression result types via ad hoc node inspection
- codegen does not choose between builtin array operations and method dispatch at emission time
- constructor emission no longer fabricates semantic IR to reuse function machinery
- codegen package contents are clearly backend-specific
