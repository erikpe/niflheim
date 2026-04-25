# Backend IR Phase 1 Implementation Plan

Status: in progress.

This document expands phase 1 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 1 work only:

- backend package scaffolding
- backend IR model definitions
- canonical JSON serialization and parsing
- human-readable text dumps
- backend IR verification
- reserved CLI surface for backend IR flags and stop phases

It does not include backend lowering, backend analyses, or target emission.

## Implementation Rules

Use these rules for every phase-1 patch:

1. Keep each slice independently reviewable and shippable.
2. Do not change the default checked compiler path yet.
3. Do not route the compiler through backend IR in phase 1.
4. Keep speculative abstractions out; add only what phase 1 needs.
5. Put cross-node semantic validation in the verifier, not in dataclass constructors.
6. Add focused tests in the same patch or before the behavior change they describe.
7. Keep error messages deterministic so tests can assert them directly.
8. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [x] PR 1: Create the backend package skeleton, target API scaffold, and reserve the CLI flag surface.
2. [x] PR 2: Implement the backend IR core model and test fixture helpers.
3. [ ] PR 3: Implement canonical JSON serialization and parsing.
4. [ ] PR 4: Implement the deterministic human-readable text dump.
5. [ ] PR 5: Implement the backend IR verifier and malformed-fixture coverage.

## PR 1: Backend Package Skeleton, Target API, And Reserved CLI Surface

### Goal

Create the backend package layout, freeze the target-backend interface shape, and reserve the backend IR CLI surface without changing the checked backend path.

### Primary Files To Change

New files:

- `compiler/backend/__init__.py`
- `compiler/backend/ir/__init__.py`
- `compiler/backend/lowering/__init__.py`
- `compiler/backend/analysis/__init__.py`
- `compiler/backend/program/__init__.py`
- `compiler/backend/targets/__init__.py`
- `compiler/backend/targets/api.py`
- `tests/compiler/integration/test_cli_backend_ir_flags.py`
- `tests/compiler/backend/targets/test_api.py`

Existing files:

- [compiler/cli.py](../compiler/cli.py)
- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)
- [tests/compiler/integration/test_cli_errors.py](../tests/compiler/integration/test_cli_errors.py)

### What To Change

1. Create the `compiler/backend/` package tree exactly as planned in the transition document.
   Keep the `__init__.py` files minimal. They should establish package boundaries, not export large wildcard surfaces.

2. Add a target-backend API module in `compiler/backend/targets/api.py`.
   Define the smallest useful interface now:
   - a target options dataclass for target-specific switches
   - a target result dataclass or equivalent return shape for emitted assembly text
   - a `BackendTarget` protocol or abstract base class that consumes verified backend IR plus target options
   Do not add x86-64 implementation logic yet.

3. Reserve the CLI flag surface in [compiler/cli.py](../compiler/cli.py).
   Add:
   - `--dump-backend-ir` with allowed values `text` and `json`
   - `--dump-backend-ir-dir <dir>`
   - `backend-ir` and `backend-ir-passes` to `STOP_PHASES`

4. Keep the checked path unchanged when the new flags are not used.
   The default path must still go through semantic lowering, semantic optimization, semantic linking, executable lowering, and legacy assembly emission.

5. Add explicit reserved behavior for the new flags.
   If a user requests `--dump-backend-ir`, `--dump-backend-ir-dir`, `--stop-after backend-ir`, or `--stop-after backend-ir-passes` before lowering exists, the CLI should fail with a clear, stable message that says the backend IR surface is reserved but not implemented yet.
   Do not silently ignore the request.

6. Do not add any backend lowering call from [compiler/cli.py](../compiler/cli.py) in this patch.

### What To Test

1. The new flags appear in CLI help text.
2. The parser accepts the new flag names and stop-after values.
3. Using the new flags before backend lowering exists returns a clear non-zero error instead of silently succeeding.
4. The default CLI path still behaves exactly as before when the new flags are absent.
5. The target API module imports cleanly and exposes the expected surface.

### How To Test

Focused tests:

```text
pytest tests/compiler/integration/test_cli_backend_ir_flags.py -q
pytest tests/compiler/backend/targets/test_api.py -q
pytest tests/compiler/integration/test_cli_codegen.py -q
pytest tests/compiler/integration/test_cli_errors.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/backend/targets/test_api.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

### Expected Outcome

- `compiler/backend/` exists and imports cleanly.
- The CLI surface for backend IR is frozen and visible.
- Invoking reserved backend IR flags fails loudly and intentionally.
- The default checked compiler path is unchanged.

### Checklist

- [x] Create the `compiler/backend/` package tree and minimal `__init__.py` files.
- [x] Add `compiler/backend/targets/api.py` with the frozen target interface scaffold.
- [x] Extend [compiler/cli.py](../compiler/cli.py) with reserved backend IR flags and stop phases.
- [x] Add explicit not-yet-implemented behavior for backend IR flags.
- [x] Add CLI integration tests for the reserved surface.
- [x] Re-run existing CLI codegen and CLI error coverage to prove default behavior is unchanged.

## PR 2: Backend IR Core Model And Fixture Helpers

### Goal

Define the backend IR node model from [docs/BACKEND_IR_SPEC.md](BACKEND_IR_SPEC.md) and create shared fixture helpers so later serialization, text, and verifier tests can build representative programs without excessive duplication.

### Primary Files To Change

New files:

- `compiler/backend/ir/model.py`
- `tests/compiler/backend/ir/test_model.py`
- `tests/compiler/backend/ir/helpers.py`

Existing files:

- `compiler/backend/ir/__init__.py`
- [docs/BACKEND_IR_SPEC.md](BACKEND_IR_SPEC.md) only if the implementation uncovers a true schema mismatch

### What To Change

1. Implement the backend IR IDs, declarations, operands, constants, call targets, instructions, terminators, and top-level program nodes in `compiler/backend/ir/model.py`.
   Reuse the existing semantic IDs, `SemanticTypeRef`, and `SourceSpan` types exactly as frozen in the spec.

2. Keep constructor logic out of the model layer unless it is purely local shape validation.
   The model may reject obviously malformed local values such as negative ordinals or impossible alignment values if that improves safety, but do not put whole-program or cross-node validation in dataclass `__post_init__` methods.

3. Export a narrow public surface from `compiler/backend/ir/__init__.py`.
   Avoid wildcard re-exports that will make later refactors noisy.

4. Add shared test fixture helpers in `tests/compiler/backend/ir/helpers.py`.
   Include small builders for:
   - source spans
   - one-function backend programs
   - one-method backend programs
   - one-constructor backend programs
   - representative runtime-call and direct-call instructions

5. Keep the fixture builders readable.
   They will be reused by the serializer, text, and verifier test suites, so it is worth centralizing them early.

### What To Test

1. A representative function program can be constructed successfully.
2. A representative method program can be constructed successfully.
3. A representative constructor program can be constructed successfully with the chosen receiver and return conventions.
4. The fixture helpers produce stable IDs and spans.
5. Public imports from `compiler.backend.ir` stay narrow and predictable.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/ir/test_model.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/ir/test_model.py -q
```

### Expected Outcome

- The core backend IR schema is represented in Python.
- The model layer is importable and usable by later phase-1 patches.
- Test fixture helpers exist so later test modules do not have to hand-build full IR graphs repeatedly.

### Checklist

- [x] Add `compiler/backend/ir/model.py` with the phase-1 node set.
- [x] Add `tests/compiler/backend/ir/helpers.py` with reusable builders.
- [x] Add model construction coverage for function, method, and constructor shapes.
- [x] Keep model-layer validation narrow and defer cross-node checks to the verifier.
- [x] Export a narrow public surface from `compiler/backend/ir/__init__.py`.

## PR 3: Canonical JSON Serialization And Parsing

### Goal

Implement the canonical machine-readable JSON form, including exact source-span encoding, path normalization, and raw-bit double encoding.

### Primary Files To Change

New files:

- `compiler/backend/ir/serialize.py`
- `tests/compiler/backend/ir/test_serialize.py`

Existing files:

- `compiler/backend/ir/model.py`
- `tests/compiler/backend/ir/helpers.py`
- [compiler/common/span.py](../compiler/common/span.py)

### What To Change

1. Add serialization helpers that convert every backend IR node to canonical Python dict or list shapes and back.

2. Encode spans exactly as frozen in the spec.
   Preserve:
   - project-root-relative paths with `/` separators when possible
   - synthetic paths such as `<memory>` verbatim
   - zero-based `offset`
   - one-based `line` and `column`

3. Encode double constants using raw IEEE-754 binary64 bits.
   Do not serialize backend IR doubles as bare JSON numbers.

4. Canonicalize ordering in the serializer rather than trusting caller tuple order.
   The serializer should emit callables, registers, blocks, instructions, and data blobs in the deterministic order frozen in the transition plan and spec.

5. Add parsing helpers that reject malformed JSON cleanly.
   In particular, reject:
   - unsupported `schema_version`
   - malformed source positions or spans
   - malformed constant shapes
   - unsupported instruction discriminators

6. Keep the public API small.
   A reasonable phase-1 surface is:
   - program-to-dict
   - dict-to-program
   - JSON-string dump
   - JSON-string load

### What To Test

1. Function, method, and constructor programs round-trip through JSON without loss.
2. The exact JSON string for representative fixtures is deterministic.
3. Double constants preserve signed zero, infinities, and NaN-bearing raw bits.
4. Span and path encoding matches the frozen contract.
5. Malformed JSON fails with deterministic error messages.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/ir/test_serialize.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/ir/test_model.py tests/compiler/backend/ir/test_serialize.py -q
```

### Expected Outcome

- Canonical JSON dumps are stable enough for fixtures and snapshots.
- Parsing is strong enough to support round-trip tests and later CLI dumps.
- Source positions and doubles are encoded exactly as frozen before implementation.

### Checklist

- [ ] Add `compiler/backend/ir/serialize.py`.
- [ ] Encode spans and paths exactly as frozen.
- [ ] Encode double constants as raw binary64 bits.
- [ ] Canonicalize deterministic ordering in the serializer.
- [ ] Add positive and negative parser coverage.

## PR 4: Deterministic Human-Readable Text Dump

### Goal

Implement the human-readable backend IR text format used for review, debugging, and text snapshots.

### Primary Files To Change

New files:

- `compiler/backend/ir/text.py`
- `tests/compiler/backend/ir/test_text.py`

Existing files:

- `compiler/backend/ir/model.py`
- `compiler/backend/ir/serialize.py`
- `tests/compiler/backend/ir/helpers.py`

### What To Change

1. Implement the recommended text shape from the spec.
   Include callable headers, register declarations, block labels, instruction lines, and terminators.

2. Match the chosen receiver and constructor conventions.
   The dumper should print constructor callables as init-style bodies with an explicit receiver and a non-unit return type.

3. Canonicalize ordering in the text dumper the same way the JSON serializer does.
   Do not assume the caller already sorted every tuple.

4. Keep optional analysis sections behind an explicit parameter.
   Phase 1 can omit them by default, but the API should leave room for opt-in analysis rendering later.

5. Prefer small private formatting helpers over one monolithic function.
   This file will grow in later phases.

### What To Test

1. Representative function, method, and constructor fixtures render as stable text snapshots.
2. Registers, blocks, and instructions appear in deterministic order even if the input tuples are not pre-sorted.
3. Runtime calls and direct calls print in a readable and unambiguous way.
4. The text format is stable enough to serve as a golden-style fixture.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/ir/test_text.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/ir/test_model.py tests/compiler/backend/ir/test_serialize.py tests/compiler/backend/ir/test_text.py -q
```

### Expected Outcome

- Developers can inspect backend IR without reading raw JSON.
- The output is deterministic enough for snapshot tests and review diffs.
- The text format matches the constructor and receiver rules already frozen in the spec.

### Checklist

- [ ] Add `compiler/backend/ir/text.py`.
- [ ] Match the spec's callable, register, block, instruction, and terminator formatting.
- [ ] Reuse deterministic ordering in the dump path.
- [ ] Add text snapshots for function, method, and constructor fixtures.
- [ ] Keep optional analysis rendering opt-in.

## PR 5: Backend IR Verifier And Malformed-Fixture Coverage

### Goal

Implement the backend IR verifier as the source of truth for rejecting malformed IR before any lowering or target work begins.

### Primary Files To Change

New files:

- `compiler/backend/ir/verify.py`
- `tests/compiler/backend/ir/test_verify.py`

Existing files:

- `compiler/backend/ir/model.py`
- `compiler/backend/ir/serialize.py`
- `tests/compiler/backend/ir/helpers.py`
- [compiler/codegen/abi/runtime.py](../compiler/codegen/abi/runtime.py)

### What To Change

1. Add a backend IR verification entrypoint.
   A reasonable phase-1 API is `verify_backend_program(program)` plus a dedicated verification error type.

2. Implement the program-level, callable-level, CFG, typing, def/use, and safety checks frozen in the spec.

3. Use the existing repository runtime metadata registry in [compiler/codegen/abi/runtime.py](../compiler/codegen/abi/runtime.py) as the authority for runtime-call validation.
   Cross-check:
   - runtime call name existence
   - reference-argument indices
   - `may_gc`
   - `needs_safepoint_hooks`

4. Keep diagnostics precise.
   The verifier should report which callable, block, register, instruction, or runtime call failed and why.

5. Do not attempt phase-2 lowering validation yet.
   The verifier should focus on the IR contract, not on proving the future lowerer is complete.

### What To Test

1. A representative valid program verifies cleanly.
2. Duplicate register, block, and instruction IDs fail.
3. Constructor receiver and return-type mismatches fail.
4. Invalid block references and bad branch condition types fail.
5. Runtime call metadata mismatches fail.
6. Field references to missing class fields fail.
7. Call arity mismatches fail, including receiver-carrying call shapes.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/ir/test_verify.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/ir tests/compiler/integration/test_cli_backend_ir_flags.py -q
```

### Expected Outcome

- Malformed backend IR is rejected before any target backend can consume it.
- Runtime-call ownership is enforced against one authority.
- Phase 2 lowering work will have a stable verifier to target immediately.

### Checklist

- [ ] Add `compiler/backend/ir/verify.py` and a dedicated verification error type.
- [ ] Validate constructor-specific and receiver-specific rules.
- [ ] Validate runtime calls against [compiler/codegen/abi/runtime.py](../compiler/codegen/abi/runtime.py).
- [ ] Add positive and negative verifier coverage.
- [ ] Run the full phase-1 backend IR test slice.

## Phase 1 Gate Checklist

Use this checklist when phase 1 is believed to be complete.

- [ ] `compiler/backend/` exists and imports cleanly.
- [ ] The target API scaffold exists without pulling in target-specific implementation logic.
- [ ] The backend IR model matches the frozen schema.
- [ ] Canonical JSON serialization and parsing are stable.
- [ ] The human-readable text dump is stable.
- [ ] The verifier enforces the phase-1 IR contract.
- [ ] Reserved CLI flags and stop phases exist.
- [ ] Using reserved backend IR flags before lowering exists fails clearly and intentionally.
- [ ] The default checked compiler path remains unchanged when backend IR flags are not used.

Recommended phase gate command:

```text
pytest -n auto --dist loadfile tests/compiler/backend/ir tests/compiler/backend/targets/test_api.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

Expected phase gate outcome:

- all new backend IR phase-1 tests pass
- existing CLI behavior remains unchanged without backend IR flags
- the repository has a usable backend IR contract surface that phase 2 lowering can target next