# Backend IR Phase 2 Implementation Plan

Status: proposed.

This document expands phase 2 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 2 work only:

- lowering `LinkedSemanticProgram` directly into `BackendProgram`
- CFG body construction and stable ID assignment during lowering
- lowering coverage for the supported semantic statement and expression families
- checked-path CLI dump and stop-after wiring for real backend IR lowering

It does not include backend IR optimization passes, backend IR analyses beyond the phase-1 verifier, or target emission from backend IR.

## Implementation Rules

Use these rules for every phase-2 patch:

1. Lower from `LinkedSemanticProgram` directly. Do not add a detour through `LoweredLinkedSemanticProgram`.
2. Keep the legacy assembly path as the default checked path. Phase 2 may wire `--dump-backend-ir` and `--stop-after backend-ir`, but `codegen` must still emit through `lower_linked_semantic_program()` plus the legacy assembly emitter.
3. Verify every freshly lowered backend program immediately with `verify_backend_program()` before dumping it, returning it from the lowering entrypoint, or using it for CLI stop-after behavior.
4. Keep stable callable, register, block, instruction, and data-blob ordering aligned with the frozen phase-1 contract.
5. Reuse the phase-1 backend IR serializer and text dumper directly. Do not create lowering-local dump formats.
6. Prefer explicit lowering contexts, allocators, and symbol tables over ad hoc mutable module globals.
7. Keep feature work partitioned by construct family so failures stay easy to localize.
8. Keep new helpers local to `compiler/backend/lowering/` unless a shared cross-package boundary is clearly needed.
9. Add focused lowering tests in the same slice as the construct family they describe.
10. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [x] PR 1: Add the backend lowering entrypoint, shared lowering context, and top-level declaration lowering.
2. [x] PR 2: Lower straight-line scalar bodies, locals, and direct or static call shapes.
3. [x] PR 3: Lower structured control flow to explicit CFG blocks and merge copies.
4. [x] PR 4: Lower receiver-aware bodies, constructors, object allocation, field access, and dispatch calls.
5. [x] PR 5: Lower arrays, slices, collection dispatch, casts, type tests, safety checks, and data blobs.
6. [x] PR 6: Wire checked-path CLI backend IR dump and stop-after behavior to the real lowering path.

## PR 1: Lowering Entrypoint, Shared Context, And Top-Level Declarations

### Goal

Create a stable `lower_to_backend_ir()` entrypoint and the shared lowering machinery needed for later body and CFG work.

This slice should establish deterministic top-level lowering for interfaces, classes, fields, callable declarations, and register-allocation scaffolding without attempting the full construct surface yet.

### Primary Files To Change

New files:

- `compiler/backend/lowering/program.py`
- `compiler/backend/lowering/functions.py`
- `compiler/backend/lowering/expressions.py`
- `tests/compiler/backend/lowering/helpers.py`
- `tests/compiler/backend/lowering/test_basics.py`

Existing files:

- `compiler/backend/lowering/__init__.py`
- [compiler/backend/ir/__init__.py](../compiler/backend/ir/__init__.py)
- [compiler/semantic/linker.py](../compiler/semantic/linker.py) only if a tiny helper is needed for cleaner lowering entrypoint boundaries
- [tests/compiler/codegen/helpers.py](../tests/compiler/codegen/helpers.py) only if a generic source-compilation helper is worth sharing instead of duplicating

### What To Change

1. Add a public lowering entrypoint in `compiler/backend/lowering/program.py`.
   The expected surface for this phase is `lower_to_backend_ir(program: LinkedSemanticProgram) -> BackendProgram`.

2. Introduce a shared lowering context that owns deterministic allocation and lookup.
   It should at least track:
   - callable declaration order
   - register allocation order by receiver, parameters, semantic locals, helper locals, then synthetic temporaries
   - block and instruction ordinal allocation
   - pooled data-blob allocation hooks for later slices

3. Lower top-level declarations from `LinkedSemanticProgram` into backend declarations.
   That includes:
   - `BackendInterfaceDecl` from linked semantic interfaces
   - `BackendClassDecl` and `BackendFieldDecl` from linked semantic classes
   - `BackendCallableDecl` headers for functions, methods, and constructors
   - signature, export, privacy, and static flags

4. Preserve callable metadata even before the full body surface is lowered.
   Extern callables should lower as bodyless backend callables immediately.
   Concrete callables should already allocate receiver and parameter registers with the correct `origin_kind` values.

5. Implement a minimal concrete-body smoke path so tiny representative callables can already lower end to end.
   Cover only the simplest necessary subset in this slice:
   - literal returns
   - local/parameter reads
   - trivial copies
   - empty constructor bodies that explicitly return the receiver

6. Run `verify_backend_program()` at the end of lowering and fail eagerly if the partially implemented lowerer produces malformed IR.

7. Add shared test helpers that compile source through resolve, typecheck, semantic lowering, optimization, linking, and backend lowering.
   These helpers should return the lowered backend program plus convenient lookup helpers for callables, blocks, and instructions.

### What To Test

1. `lower_to_backend_ir()` returns a valid `BackendProgram` for a minimal linked semantic program.
2. Interfaces, classes, fields, functions, methods, and constructors preserve deterministic top-level ordering.
3. Receiver, parameter, and semantic-local metadata map to the expected backend register origins.
4. Extern callables lower without blocks and concrete callables lower with entry block `b0`.
5. Tiny function, method, and constructor fixtures verify cleanly after lowering.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/lowering/test_basics.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering/test_basics.py tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- `compiler/backend/lowering/` has a real lowering entrypoint.
- Linked semantic declarations lower into deterministic backend declarations.
- Minimal backend programs can already be produced and verified.
- Later slices can focus on construct families instead of re-laying shared lowering infrastructure.

### Checklist

- [x] Add `compiler/backend/lowering/program.py` with the public lowering entrypoint.
- [x] Add a shared lowering context and deterministic allocators.
- [x] Lower interfaces, classes, fields, and callable signatures.
- [x] Lower extern declarations and minimal concrete smoke bodies.
- [x] Add reusable backend lowering test helpers.
- [x] Add focused declaration and smoke lowering coverage.

## PR 2: Straight-Line Scalar Bodies, Locals, And Direct Or Static Calls

### Goal

Lower straight-line expression and statement bodies without CFG joins yet so ordinary scalar code can lower to valid backend IR.

This slice should make the backend lowerer useful for arithmetic-heavy and direct-call-heavy fixtures while still deferring structured control flow.

### Primary Files To Change

New files:

- `tests/compiler/backend/lowering/test_backend_calls.py`

Existing files:

- `compiler/backend/lowering/functions.py`
- `compiler/backend/lowering/expressions.py`
- `tests/compiler/backend/lowering/helpers.py`
- `tests/compiler/backend/lowering/test_basics.py`
- [compiler/semantic/ir.py](../compiler/semantic/ir.py) only if a tiny helper for dispatch-mode inspection reduces duplication cleanly

### What To Change

1. Lower straight-line local and temporary evaluation.
   Cover:
   - `SemanticVarDecl`
   - `SemanticAssign` to local targets
   - `SemanticExprStmt`
   - `SemanticReturn`

2. Lower scalar expression families to backend instructions.
   Cover:
   - `LiteralExprS`
   - `NullExprS`
   - `LocalRefExpr`
   - `UnaryExprS`
   - `BinaryExprS`
   - simple copy-style expression lowering where no new instruction is needed

3. Lower direct call shapes that do not require receiver-aware dispatch yet.
   Cover:
   - `FunctionCallTarget`
   - `StaticMethodCallTarget`
   - `CallableValueCallTarget` if the semantic type information is already sufficient to emit `BackendIndirectCallTarget`

4. Keep evaluation order explicit and deterministic.
   Nested expression lowering should allocate temporaries in one stable order so text snapshots stay reviewable.

5. Reuse the phase-1 verifier and text dump in the test suite rather than inventing lowering-local assertions for control-flow shape.

6. Do not lower structured `if`, `while`, `break`, `continue`, `for in`, or receiver-carrying dispatch in this slice.

### What To Test

1. Arithmetic and comparison expressions lower to the expected backend instruction families.
2. Local declarations and assignments produce deterministic register reuse or copy behavior.
3. Direct function calls lower to `BackendDirectCallTarget` with exact signatures.
4. Static method calls lower without receiver registers.
5. Nested expression evaluation order stays deterministic across runs.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/lowering/test_basics.py -q
pytest tests/compiler/backend/lowering/test_backend_calls.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering/test_basics.py tests/compiler/backend/lowering/test_backend_calls.py tests/compiler/backend/ir/test_text.py tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- Straight-line scalar code lowers end to end into readable backend IR.
- Direct and static call shapes are represented through backend call instructions.
- The lowerer has enough surface to cover simple backend IR dump fixtures from real source programs.

### Checklist

- [x] Lower local declarations, local assignments, expression statements, and returns.
- [x] Lower scalar literal, null, unary, and binary expressions.
- [x] Lower direct function and static method calls.
- [x] Add deterministic nested-expression snapshot coverage.
- [x] Keep structured CFG constructs deferred to the next slice.

## PR 3: Structured Control Flow To CFG Blocks And Merge Copies

### Goal

Translate structured control flow into explicit backend blocks and terminators so backend IR lowering becomes CFG-first in practice, not only in the model.

### Primary Files To Change

New files:

- `compiler/backend/lowering/control_flow.py`
- `tests/compiler/backend/lowering/test_control_flow.py`

Existing files:

- `compiler/backend/lowering/functions.py`
- `compiler/backend/lowering/expressions.py`
- `tests/compiler/backend/lowering/helpers.py`
- `tests/compiler/backend/lowering/test_basics.py`
- `tests/compiler/backend/lowering/test_backend_calls.py`

### What To Change

1. Add a control-flow lowering builder that owns block creation, branch targets, and loop-exit plumbing.

2. Lower the structured statement families into explicit CFG shape.
   Cover:
   - `SemanticIf`
   - `SemanticWhile`
   - `SemanticBreak`
   - `SemanticContinue`

3. Emit explicit join copies where values must survive control-flow merges.
   Follow the frozen non-SSA rule:
   - represent merge transfers with ordinary backend instructions
   - split critical edges when per-edge copies are required
   - keep the resulting block graph deterministic and verifier-friendly

4. Ensure every non-extern callable terminates explicitly with a backend terminator.
   Avoid implicit fallthrough assumptions.

5. Keep unreachable cleanup out of scope for this phase.
   The lowerer should emit valid CFG; later backend analysis passes can simplify it.

### What To Test

1. `if` with and without `else` lowers to explicit branch and join blocks.
2. Nested control flow lowers deterministically.
3. `while` loops lower to condition, body, and exit blocks with stable IDs.
4. `break` and `continue` target the correct loop blocks.
5. Control-flow joins that require copies express them with ordinary backend instructions.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/lowering/test_control_flow.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering/test_control_flow.py tests/compiler/backend/ir/test_text.py tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- Supported structured semantic control flow lowers into explicit backend CFGs.
- Join behavior follows the frozen non-SSA convention.
- Backend text dumps for branches and loops are stable enough to review directly.

### Checklist

- [x] Add `compiler/backend/lowering/control_flow.py`.
- [x] Lower `if`, `while`, `break`, and `continue` to explicit backend blocks.
- [x] Implement deterministic join-copy insertion and critical-edge splitting where needed.
- [x] Add CFG snapshot coverage for nested branches and loops.
- [x] Keep CFG cleanup passes deferred to phase 3.

## PR 4: Receiver-Aware Bodies, Constructors, Objects, And Dispatch Calls

### Goal

Finish the object-oriented call and receiver surface so instance methods, constructors, fields, and dispatch forms lower into the correct backend IR shapes.

### Primary Files To Change

New files:

- `tests/compiler/backend/lowering/test_objects.py`

Existing files:

- `compiler/backend/lowering/program.py`
- `compiler/backend/lowering/functions.py`
- `compiler/backend/lowering/expressions.py`
- `compiler/backend/lowering/control_flow.py`
- `tests/compiler/backend/lowering/helpers.py`
- `tests/compiler/backend/lowering/test_backend_calls.py`

### What To Change

1. Lower method and constructor bodies with correct receiver handling.
   That includes:
   - receiver register allocation
   - receiver-first argument layout for receiver-carrying calls
   - constructor return behavior that explicitly returns the receiver register

2. Lower object allocation and constructor invocation.
   `ConstructorCallTarget` should lower through the frozen init-style constructor convention rather than inventing extra backend callable kinds.
   `ConstructorInitCallTarget` should lower as the receiver-carrying form used for init flows such as `super(...)`.

3. Lower field reads and writes.
   Emit explicit `BackendFieldLoadInst` and `BackendFieldStoreInst` nodes, plus the required explicit null checks the verifier expects.

4. Lower receiver-carrying call targets.
   Cover:
   - `InstanceMethodCallTarget`
   - `VirtualMethodCallTarget`
   - `InterfaceMethodCallTarget`

5. Preserve dispatch metadata from semantic nodes.
   In particular, keep slot-owner, selected-method, and interface-method identity intact so later backend analyses and target lowering do not have to reconstruct it.

### What To Test

1. Instance method bodies lower with a real `receiver_reg`.
2. Constructor bodies and constructor calls obey the frozen init-style convention.
3. Field load and store operations lower to explicit backend field instructions.
4. Virtual dispatch lowers with slot-owner and selected-method metadata preserved.
5. Interface dispatch lowers with interface ID and interface-method ID preserved.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/lowering/test_backend_calls.py -q
pytest tests/compiler/backend/lowering/test_objects.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering/test_backend_calls.py tests/compiler/backend/lowering/test_objects.py tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- Receiver-aware semantic bodies lower into the receiver-aware backend IR shapes frozen in phase 1.
- Object allocation, constructors, fields, and dispatch calls are all represented explicitly in backend IR.
- Later backend passes can reason about receiver-carrying calls without peeking back into semantic nodes.

### Checklist

- [x] Lower receiver allocation and receiver-first call argument layout.
- [x] Lower constructor call and init flows through the frozen constructor convention.
- [x] Lower field loads and stores with explicit null checks.
- [x] Lower virtual and interface dispatch metadata faithfully.
- [x] Add focused object and dispatch lowering coverage.

## PR 5: Arrays, Collection Dispatch, Casts, Safety Checks, And Data Blobs

### Goal

Complete the remaining lowering surface that depends on runtime-backed collection behavior, safety checks, and constant-data materialization.

### Primary Files To Change

New files:

- `tests/compiler/backend/lowering/test_arrays.py`

Existing files:

- `compiler/backend/lowering/program.py`
- `compiler/backend/lowering/functions.py`
- `compiler/backend/lowering/expressions.py`
- `compiler/backend/lowering/control_flow.py`
- [compiler/codegen/abi/runtime.py](../compiler/codegen/abi/runtime.py)
- [compiler/codegen/types.py](../compiler/codegen/types.py)
- `tests/compiler/backend/lowering/helpers.py`
- `tests/compiler/backend/lowering/test_objects.py`

### What To Change

1. Lower the array and slice expression families.
   Cover:
   - `ArrayCtorExprS`
   - `ArrayLenExpr`
   - `IndexReadExpr`
   - `SliceReadExpr`
   - index and slice l-value assignments

2. Lower explicit safety operations as first-class backend instructions.
   Emit the explicit `BackendNullCheckInst` and `BackendBoundsCheckInst` nodes required by the verifier before direct object or array access.

3. Lower `SemanticForIn` directly to CFG blocks instead of relying on the legacy executable-lowering form.
   Preserve the semantic distinction between:
   - direct array fast-path iteration
   - runtime-backed array iteration
   - collection protocol dispatch

4. Lower runtime-backed collection operations to `BackendRuntimeCallTarget` using the authoritative runtime metadata registry.
   Reuse existing runtime call names and array runtime-kind helpers instead of inventing new lowering-local tables.

5. Lower casts and type tests.
   Cover:
   - `CastExprS`
   - `TypeTestExprS`
   - any required trap behavior for bad casts

6. Lower constant data payloads that backend IR models as program-global data blobs.
   At minimum, handle `StringLiteralBytesExpr` by pooling deterministic byte-string data into `BackendDataBlob` plus `BackendDataOperand` references.

### What To Test

1. Array allocation, length, load, store, slice read, and slice write lower to the expected backend instructions.
2. `for in` lowers to explicit CFG and preserves its chosen dispatch strategy.
3. Runtime-backed collection operations use registered runtime call metadata and runtime kinds.
4. Casts and type tests lower to explicit backend cast or type-test instructions.
5. String literal byte payloads pool deterministically into backend data blobs.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/lowering/test_arrays.py -q
pytest tests/compiler/backend/lowering/test_objects.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering/test_arrays.py tests/compiler/backend/lowering/test_objects.py tests/compiler/backend/ir/test_serialize.py tests/compiler/backend/ir/test_text.py tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- Arrays, slices, `for in`, casts, and type tests all lower into explicit backend IR.
- Runtime-backed collection behavior is represented with real backend runtime-call nodes and verified metadata.
- Constant byte payloads are pooled into stable backend data blobs instead of being left implicit in semantic expressions.

### Checklist

- [x] Lower array, slice, and index operations.
- [x] Emit explicit null and bounds checks where required.
- [x] Lower `for in` directly to backend CFG.
- [x] Lower runtime-backed collection dispatch via registered runtime calls.
- [x] Lower casts, type tests, and bad-cast trap behavior.
- [x] Lower deterministic string-byte data blobs.

## PR 6: Checked-Path CLI Dump And Stop-After Wiring

### Goal

Make the reserved backend IR CLI surface real for phase 2 by lowering linked semantic programs on demand, verifying the result, and dumping or stopping after backend IR in the checked compiler path.

### Primary Files To Change

New files:

- `tests/compiler/integration/test_cli_backend_ir_dump.py`

Existing files:

- [compiler/cli.py](../compiler/cli.py)
- `compiler/backend/lowering/__init__.py`
- `compiler/backend/lowering/program.py`
- [compiler/backend/ir/text.py](../compiler/backend/ir/text.py)
- [compiler/backend/ir/serialize.py](../compiler/backend/ir/serialize.py)
- [compiler/backend/ir/verify.py](../compiler/backend/ir/verify.py)
- [tests/compiler/integration/test_cli_backend_ir_flags.py](../tests/compiler/integration/test_cli_backend_ir_flags.py)
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)
- [tests/compiler/integration/test_cli_errors.py](../tests/compiler/integration/test_cli_errors.py)
- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)

### What To Change

1. Wire `compiler/cli.py` so the checked path can lower linked semantic programs to backend IR when the backend IR surface is explicitly requested.
   The CLI should:
   - lower once
   - verify once
   - reuse the verified backend program for dumping and `--stop-after backend-ir`

2. Keep the default `codegen` path unchanged when backend IR flags are absent.
   The checked backend path should still go through `lower_linked_semantic_program()` and the legacy assembly emitter unless the user explicitly requests backend IR dumping or stopping.

3. Implement real checked-path behavior for:
   - `--dump-backend-ir text`
   - `--dump-backend-ir json`
   - `--dump-backend-ir-dir <dir>`
   - `--stop-after backend-ir`

4. Keep `--stop-after backend-ir-passes` intentionally reserved until phase 3.
   Update the error message so it no longer says backend lowering is missing; it should instead say that backend IR passes are not wired yet.

5. Keep dump output deterministic and non-ambiguous.
   Recommended behavior for this phase:
   - if stopping after backend IR and no dump directory is provided, print the requested dump to stdout
   - if continuing past backend IR, require `--dump-backend-ir-dir` so backend IR output does not mix with assembly output on stdout
   - use one deterministic whole-program file per compilation, such as `<input-stem>.backend-ir.txt` or `<input-stem>.backend-ir.json`

6. Add integration coverage that proves the new CLI path is real without changing the default assembly path.

### What To Test

1. `--stop-after backend-ir` returns success on real source programs and prints or writes valid backend IR.
2. `--dump-backend-ir text` and `json` produce stable whole-program dumps.
3. `--dump-backend-ir-dir` writes deterministic filenames and contents.
4. `--stop-after backend-ir-passes` still fails clearly and intentionally.
5. The default CLI codegen path is unchanged when backend IR flags are not used.

### How To Test

Focused commands:

```text
pytest tests/compiler/integration/test_cli_backend_ir_dump.py -q
pytest tests/compiler/integration/test_cli_backend_ir_flags.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering tests/compiler/backend/ir tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

### Expected Outcome

- The checked compiler path can lower and verify backend IR on demand.
- Users can inspect real backend IR text or JSON dumps from real source programs.
- `--stop-after backend-ir` is usable in the checked path.
- `backend-ir-passes` remains a clearly reserved phase boundary for phase 3.

### Checklist

- [x] Wire the CLI to lower and verify backend IR on demand.
- [x] Implement real `--dump-backend-ir` and `--stop-after backend-ir` behavior.
- [x] Keep `backend-ir-passes` intentionally reserved until phase 3.
- [x] Add deterministic whole-program dump file behavior.
- [x] Add CLI integration coverage for the real backend IR path.
- [x] Re-run existing CLI coverage to prove default codegen behavior is unchanged.

## Phase 2 Gate Checklist

Use this checklist when phase 2 is believed to be complete.

- [x] `compiler/backend/lowering/` exposes a stable `lower_to_backend_ir()` entrypoint.
- [x] Backend lowering consumes `LinkedSemanticProgram` directly.
- [x] Representative functions, methods, and constructors lower to verified backend IR.
- [x] Straight-line expressions and direct call shapes lower correctly.
- [x] Structured control flow lowers to explicit CFG blocks and terminators.
- [x] Receiver-aware calls, constructors, fields, and dispatch forms lower correctly.
- [x] Arrays, slices, `for in`, casts, type tests, and runtime-backed collection operations lower correctly.
- [x] Constant byte payloads lower to deterministic backend data blobs where required.
- [x] `--dump-backend-ir` and `--stop-after backend-ir` work on the checked CLI path.
- [x] `--stop-after backend-ir-passes` still fails clearly and intentionally until phase 3.
- [x] The default checked assembly path remains unchanged when backend IR flags are not used.

Recommended phase gate command:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering tests/compiler/backend/ir tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

Expected phase gate outcome:

- all new backend lowering tests pass
- real backend IR dumps work from the checked CLI path
- default checked assembly output remains on the legacy backend path when backend IR flags are not used
- the repository has a usable lowered backend IR seam ready for phase 3 analyses